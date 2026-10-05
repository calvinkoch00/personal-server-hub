import os
import json
import urllib.request

env_vars = {}
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env_vars[k.strip()] = v.strip().strip('"').strip("'")

APP_ID = env_vars.get("DISCORD_APPLICATION_ID")
BOT_TOKEN = env_vars.get("DISCORD_BOT_TOKEN")

if not APP_ID or not BOT_TOKEN:
    print("Fehler: Bitte DISCORD_APPLICATION_ID und DISCORD_BOT_TOKEN in deiner .env eintragen!")
    exit(1)

commands = [
    {
        "name": "start",
        "description": "Startet den Minecraft-Server on demand"
    },
    {
        "name": "status",
        "description": "Zeigt alle aktiven Server an"
    },
    {
        "name": "stop",
        "description": "Stoppt den laufenden Minecraft-Server"
    }
]

url = f"https://discord.com/api/v10/applications/{APP_ID}/commands"
req = urllib.request.Request(
    url,
    data=json.dumps(commands).encode("utf-8"),
    headers={
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json"
    },
    method="PUT"
)

try:
    with urllib.request.urlopen(req) as resp:
        print("Erfolgreich bei Discord registriert:")
        print(resp.read().decode())
except Exception as e:
    print("Fehler bei der Registrierung:", e)