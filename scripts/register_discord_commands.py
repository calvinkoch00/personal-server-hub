import os
import json
import urllib.request
import urllib.error

# .env einlesen
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
    print("Fehler: Bitte DISCORD_APPLICATION_ID und DISCORD_BOT_TOKEN in der .env hinterlegen!")
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

# Globaler Endpunkt (ohne Guild-ID)
url = f"https://discord.com/api/v10/applications/{APP_ID}/commands"
data = json.dumps(commands).encode("utf-8")

req = urllib.request.Request(
    url,
    data=data,
    headers={
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": f"DiscordBot (https://github.com, 1.0)"
    },
    method="PUT"
)

try:
    with urllib.request.urlopen(req) as resp:
        print("Erfolgreich global registriert! Status:", resp.status)
        print(resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    error_body = e.read().decode("utf-8")
    print(f"HTTP Error {e.code}: {e.reason}")
    print("Antwort von Discord Details:", error_body)
except Exception as e:
    print("Allgemeiner Fehler:", e)