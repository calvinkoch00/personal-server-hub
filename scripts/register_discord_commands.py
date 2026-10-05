import os
import json
import urllib.request
import urllib.error

# 1. Zuerst System-Umgebungsvariablen prüfen (GitHub Actions)
APP_ID = os.environ.get("DISCORD_APPLICATION_ID")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# 2. Falls leer: Lokale .env einlesen (lokal auf deinem Mac)
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
        "description": "Startet einen Gameserver on demand",
        "options": [
            {
                "type": 3,  # STRING
                "name": "game",
                "description": "Spiel-Server (Standard: minecraft, z.B. csgo)",
                "required": False
            },
            {
                "type": 3,  # STRING
                "name": "duration",
                "description": "Laufzeit z. B. '5m', '4h', '7d' (Standard: 5m, Max: 7d)",
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
except Exception as e:
    print("Fehler:", e)
    exit(1)