import os
import json
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(__file__)
JSON_PATH = os.path.join(BASE_DIR, "discord_commands.json")
CACHE_PATH = os.path.join(BASE_DIR, "..", "aws_lambda", "commands_cache.txt")
ENV_PATH = os.path.join(BASE_DIR, "..", ".env")

# 1. Credentials laden
APP_ID = os.environ.get("DISCORD_APPLICATION_ID")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if (not APP_ID or not BOT_TOKEN) and os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "DISCORD_APPLICATION_ID" and not APP_ID:
                    APP_ID = v
                elif k == "DISCORD_BOT_TOKEN" and not BOT_TOKEN:
                    BOT_TOKEN = v

if not APP_ID or not BOT_TOKEN:
    print("Fehler: Bitte DISCORD_APPLICATION_ID und DISCORD_BOT_TOKEN prüfen!")
    exit(1)

# 2. Commands aus JSON laden
with open(JSON_PATH, "r", encoding="utf-8") as f:
    commands = json.load(f)

# 3. Bei Discord registrieren
url = f"https://discord.com/api/v10/applications/{APP_ID}/commands"
req = urllib.request.Request(
    url,
    data=json.dumps(commands).encode("utf-8"),
    headers={
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com, 1.0)"
    },
    method="PUT"
)

try:
    with urllib.request.urlopen(req) as resp:
        registered_commands = json.loads(resp.read().decode("utf-8"))
        print(f"Erfolgreich {len(registered_commands)} Befehle bei Discord registriert! Status: {resp.status}")

        # 4. Help-Cache dynamisch aus den Befehlen generieren
        lines = ["📖 **Verfügbare Server-Befehle:**\n"]
        for cmd in registered_commands:
            name = cmd["name"]
            desc = cmd.get("description", "")
            opts = cmd.get("options", [])

            # Prüfen auf Subcommands (Type 1)
            subcommands = [o for o in opts if o.get("type") == 1]
            if subcommands:
                for sub in subcommands:
                    sub_name = sub["name"]
                    sub_desc = sub.get("description", "")
                    sub_args = " ".join(
                        f"<{arg['name']}>" if arg.get("required") else f"[{arg['name']}]"
                        for arg in sub.get("options", [])
                    )
                    args_str = f" {sub_args}" if sub_args else ""
                    lines.append(f"• `/{name} {sub_name}{args_str}` — {sub_desc}")
            else:
                arg_list = " ".join(
                    f"<{o['name']}>" if o.get("required") else f"[{o['name']}]"
                    for o in opts
                )
                args_str = f" {arg_list}" if arg_list else ""
                lines.append(f"• `/{name}{args_str}` — {desc}")

        cache_content = "\n".join(lines)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            f.write(cache_content)
        print(f"Befehls-Cache automatisch generiert unter: {CACHE_PATH}")

except urllib.error.HTTPError as e:
    err_body = e.read().decode("utf-8")
    print(f"HTTP Fehler bei Discord API: {e.code} - {err_body}")
    exit(1)
except Exception as e:
    print(f"Fehler bei Discord-Registrierung: {e}")
    exit(1)