import json
import yaml
import os
import sys
import urllib.request
from pathlib import Path

# Lädt die App -> Führt alle Decorators aus
from personal_server_hub.api.main import app 
from personal_server_hub.api.discord_registry import DISCORD_COMMANDS_REGISTRY

BASE_DIR = Path(__file__).resolve().parent.parent
YAML_PATH = BASE_DIR / "personal_server_hub" / "adapters" / "discord" / "discord_responses.yaml"
DISCORD_API_URL = "https://discord.com/api/v10"

def extract_command_names_from_yaml(commands: list) -> set:
    names = set()
    for cmd in commands:
        subcommands = [opt for opt in cmd.get("options", []) if opt.get("type") in (1, 2)]
        if not subcommands:
            names.add(cmd["name"])
        else:
            for sub in subcommands:
                names.add(f"{cmd['name']} {sub['name']}")
    return names

def load_credentials():
    app_id = os.environ.get("DISCORD_APPLICATION_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    
    # Fallback auf .env (nur für lokales Ausführen)
    env_path = BASE_DIR.parent / ".env"
    if (not app_id or not bot_token) and env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                k = k.strip()
                if k == "DISCORD_APPLICATION_ID" and not app_id:
                    app_id = v.strip().strip("'\"")
                if k == "DISCORD_BOT_TOKEN" and not bot_token:
                    bot_token = v.strip().strip("'\"")

    return app_id, bot_token

def main():
    app_id, bot_token = load_credentials()
    if not app_id or not bot_token:
        print("❌ DISCORD_APPLICATION_ID oder DISCORD_BOT_TOKEN fehlen.", file=sys.stderr)
        sys.exit(1)

    # 1. YAML laden
    with open(YAML_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    payload = config.get("discord_commands", [])
    if not payload:
        print("❌ YAML enthält keine 'discord_commands'.", file=sys.stderr)
        sys.exit(1)

    # 2. Sanity Check (YAML vs Python Decorators)
    yaml_commands = extract_command_names_from_yaml(payload)
    python_commands = DISCORD_COMMANDS_REGISTRY

    missing_in_python = yaml_commands - python_commands
    missing_in_yaml = python_commands - yaml_commands

    if missing_in_python:
        print(f"⚠️ Warnung: Im YAML definiert, aber kein @discord_command in FastAPI: {missing_in_python}")
    if missing_in_yaml:
        print(f"⚠️ Warnung: In FastAPI dekoriert, aber fehlt im YAML: {missing_in_yaml}")

    # 3. Zu Discord pushen
    url = f"{DISCORD_API_URL}/applications/{app_id}/commands"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json"
        },
        method="PUT"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            print(f"✅ {len(payload)} Commands aus YAML erfolgreich bei Discord registriert!")
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"❌ Discord API Fehler ({e.code}): {err_msg}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()