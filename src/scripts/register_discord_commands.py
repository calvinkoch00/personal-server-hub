import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "discord_commands.json"
CACHE_PATH = BASE_DIR.parent / "personal_server_hub" / "commands_cache.txt"
ENV_PATH = BASE_DIR.parent.parent / ".env"
DISCORD_API_URL = "https://discord.com/api/v10"


def load_credentials(environment: dict[str, str], env_path: Path) -> tuple[str, str]:
    credentials = {
        "DISCORD_APPLICATION_ID": environment.get("DISCORD_APPLICATION_ID", "").strip(),
        "DISCORD_BOT_TOKEN": environment.get("DISCORD_BOT_TOKEN", "").strip(),
    }

    if not all(credentials.values()) and env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() in credentials and not credentials[name.strip()]:
                credentials[name.strip()] = value.strip().strip("\"'")

    app_id = credentials["DISCORD_APPLICATION_ID"]
    bot_token = credentials["DISCORD_BOT_TOKEN"]
    if not app_id or not bot_token:
        raise ValueError(
            "DISCORD_APPLICATION_ID und DISCORD_BOT_TOKEN müssen in der "
            "Umgebung oder in .env gesetzt sein."
        )
    if not app_id.isdecimal():
        raise ValueError("DISCORD_APPLICATION_ID muss eine numerische Discord-ID sein.")
    return app_id, bot_token


def load_commands(path: Path) -> list[dict]:
    commands = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(commands, list) or not commands:
        raise ValueError("Die Command-Datei muss ein nicht-leeres JSON-Array enthalten.")
    if not all(isinstance(command, dict) for command in commands):
        raise ValueError("Jeder Eintrag in der Command-Datei muss ein JSON-Objekt sein.")
    return commands


def build_command_cache(commands: list[dict]) -> str:
    lines = ["📖 **Verfügbare Server-Befehle:**", ""]

    def append_command(name: str, description: str, options: list[dict], parents: tuple[str, ...] = ()) -> None:
        subcommands = [option for option in options if option.get("type") in (1, 2)]
        if subcommands:
            for option in subcommands:
                append_command(
                    name,
                    option.get("description", ""),
                    option.get("options", []),
                    (*parents, option["name"]),
                )
            return

        path = " ".join((name, *parents))
        arguments = " ".join(
            f"<{option['name']}>" if option.get("required") else f"[{option['name']}]"
            for option in options
        )
        suffix = f" {arguments}" if arguments else ""
        lines.append(f"• `/{path}{suffix}` — {description}")

    for command in commands:
        append_command(
            command["name"],
            command.get("description", ""),
            command.get("options", []),
        )

    return "\n".join(lines) + "\n"


def register_commands(
    app_id: str,
    bot_token: str,
    commands: list[dict],
    opener: Callable = urllib.request.urlopen,
) -> list[dict]:
    url = f"{DISCORD_API_URL}/applications/{app_id}/commands"
    request = urllib.request.Request(
        url,
        data=json.dumps(commands).encode("utf-8"),
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/calvinkoch00/personal-server-hub, 1.0)",
        },
        method="PUT",
    )
    with opener(request, timeout=30) as response:
        registered_commands = json.loads(response.read().decode("utf-8"))

    if not isinstance(registered_commands, list) or not all(
        isinstance(command, dict) and isinstance(command.get("name"), str)
        for command in registered_commands
    ):
        raise ValueError("Discord API hat eine unerwartete Antwort zurückgegeben.")
    return registered_commands


def main(
    environment: dict[str, str] | None = None,
    env_path: Path = ENV_PATH,
    commands_path: Path = JSON_PATH,
    cache_path: Path = CACHE_PATH,
    opener: Callable = urllib.request.urlopen,
) -> int:
    try:
        app_id, bot_token = load_credentials(
            environment if environment is not None else os.environ,
            env_path,
        )
        commands = load_commands(commands_path)
        registered_commands = register_commands(app_id, bot_token, commands, opener)
        cache_path.write_text(
            build_command_cache(registered_commands),
            encoding="utf-8",
        )
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        print(
            f"Discord API HTTP-Fehler {error.code}: {details or error.reason}",
            file=sys.stderr,
        )
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, urllib.error.URLError) as error:
        print(f"Fehler bei der Discord-Command-Registrierung: {error}", file=sys.stderr)
        return 1

    print(f"{len(registered_commands)} Discord-Befehle erfolgreich registriert.")
    print(f"Befehls-Cache aktualisiert: {cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
