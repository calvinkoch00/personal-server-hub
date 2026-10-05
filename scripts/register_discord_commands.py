import os
import json
import urllib.request
import urllib.error

APP_ID = os.environ.get("DISCORD_APPLICATION_ID")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if not APP_ID or not BOT_TOKEN:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "DISCORD_APPLICATION_ID" and not APP_ID:
                        APP_ID = v
                    elif k == "DISCORD_BOT_TOKEN" and not BOT_TOKEN:
                        BOT_TOKEN = v

if not APP_ID or not BOT_TOKEN:
    print("Fehler: Bitte DISCORD_APPLICATION_ID und DISCORD_BOT_TOKEN prüfen!")
    exit(1)

commands = [
    {
        "name": "start",
        "description": "Startet Server (z. B. '/start', '/start 2h' oder '/start csgo 1d')",
        "options": [
            {
                "type": 3,  # STRING
                "name": "args",
                "description": "Optional: z. B. '2h', 'csgo' oder 'csgo 3d' (Standard: minecraft 5m)",
                "required": False
            }
        ]
    },
    {
        "name": "status",
        "description": "Zeigt alle aktiven Server an"
    },
    {
        "name": "stop",
        "description": "Stoppt den laufenden Gameserver"
    },
    {
        "name": "help",
        "description": "Zeigt alle Befehle und Beispiele an"
    }
]

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
        print("Erfolgreich bei Discord registriert! Status:", resp.status)
        print(resp.read().decode())
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode()}")
    exit(1)