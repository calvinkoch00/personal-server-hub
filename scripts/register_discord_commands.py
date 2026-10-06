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
        "description": "Startet einen Gameserver On-Demand",
        "options": [
            {
                "type": 3,  # STRING
                "name": "game",
                "description": "Spiel auswählen (Standard: minecraft)",
                "required": False,
                "choices": [
                    {"name": "Minecraft", "value": "minecraft"}
                ]
            },
            {
                "type": 3,  # STRING
                "name": "duration",
                "description": "Laufzeit auswählen oder eingeben (Standard: 5m)",
                "required": False,
                "choices": [
                    {"name": "5 Minuten (Test)", "value": "5m"},
                    {"name": "30 Minuten", "value": "30m"},
                    {"name": "1 Stunde", "value": "1h"},
                    {"name": "2 Stunden", "value": "2h"},
                    {"name": "4 Stunden", "value": "4h"},
                    {"name": "1 Tag", "value": "1d"}
                ]
            },
            {
                "type": 5,  # BOOLEAN
                "name": "log",
                "description": "Live-Logs nach Discord streamen? (Standard: False)",
                "required": False
            }
        ]
    },
    {
        "name": "status",
        "description": "Zeigt alle aktiven Server samt IP an"
    },
    {
        "name": "log",
        "description": "Schaltet Live-Server-Logs im Discord-Kanal ein oder aus (Toggle)"
    },
    {
        "name": "stop",
        "description": "Stoppt und löscht den laufenden Gameserver"
    },
    {
        "name": "help",
        "description": "Zeigt alle Befehle und Beispiele an"
    },
    {
        "name": "addgameaccount",
        "description": "Verknüpft deinen Ingame-Namen mit deinem Discord-Account für das Session-Tracking",
        "options": [
            {
                "type": 3,  # STRING
                "name": "game",
                "description": "Das Spiel (z. B. minecraft)",
                "required": True
            },
            {
                "type": 3,  # STRING
                "name": "username",
                "description": "Dein Ingame-Name (z. B. gamesbond00)",
                "required": True
            }
        ]
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
        registered = json.loads(resp.read().decode())

        lines = ["📖 **Verfügbare Server-Befehle:**\n"]
        for cmd in sorted(registered, key=lambda x: x["name"]):
            name = cmd.get("name")
            desc = cmd.get("description", "")
            opts = cmd.get("options", [])
            opt_str = ""
            if opts:
                opt_names = [f"[{o['name']}]" if not o.get("required") else f"<{o['name']}>" for o in opts]
                opt_str = " " + " ".join(opt_names)
            lines.append(f"• `/{name}{opt_str}` — {desc}")

        lines.append(
            "\n💡 **Beispiele für `/start` & `/log`:**\n"
            "• `/start` *(Minecraft, 5 Minuten)*\n"
            "• `/start args: 2h` *(Minecraft, 2 Stunden)*\n"
            "• `/start args: 2h log=true` *(Minecraft, 2 Stunden mit Live-Logs)*\n"
            "• `/log` *(Toggelt Live-Logs während der Server läuft)*\n"
            "• `/start args: <spiel> 4h` *(Anderes Spiel aus dem Speicher)*"
        )
        cache_content = "\n".join(lines)

        cache_path = os.path.join(os.path.dirname(__file__), "..", "aws_lambda", "commands_cache.txt")
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(cache_content)
        print(f"Befehls-Cache erfolgreich aktualisiert unter: {cache_path}")

except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode()}")
    exit(1)
except Exception as e:
    print("Fehler:", e)
    exit(1)