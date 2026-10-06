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
                    k, v = k.strip(), v.strip().strip('"').strip("'")
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
                "type": 3,
                "name": "game",
                "description": "Spiel auswählen (Standard: minecraft)",
                "required": False,
                "choices": [{"name": "Minecraft", "value": "minecraft"}]
            },
            {
                "type": 3,
                "name": "duration",
                "description": "Laufzeit frei eingeben (z. B. 45m, 8h, 2d — Standard: 5m)",
                "required": False
            },
            {
                "type": 3,
                "name": "log",
                "description": "Live-Logs nach Discord streamen",
                "required": False,
                "choices": [
                    {"name": "Aus (Standard)", "value": "none"},
                    {"name": "Nur Game Logs", "value": "game"},
                    {"name": "Alles (Game + System & Agenten)", "value": "all"}
                ]
            }
        ]
    },
    {
        "name": "status",
        "description": "Zeigt alle aktiven Server samt IP an"
    },
    {
        "name": "log",
        "description": "Schaltet Live-Server-Logs im Discord-Kanal um",
        "options": [
            {
                "type": 3,
                "name": "mode",
                "description": "Log-Modus wählen",
                "required": True,
                "choices": [
                    {"name": "Alles (Game + System/Agenten)", "value": "all"},
                    {"name": "Nur Game Logs", "value": "game"},
                    {"name": "Deaktivieren", "value": "off"}
                ]
            }
        ]
    },
    {
        "name": "stop",
        "description": "Stoppt und löscht den laufenden Gameserver"
    },
    {
        "name": "costs",
        "description": "Zeigt die Kosten und Spielzeiten an",
        "options": [
            {
                "type": 3,
                "name": "timeframe",
                "description": "Zeitraum der Abrechnung",
                "required": False,
                "choices": [
                    {"name": "Diesen Monat", "value": "this month"},
                    {"name": "Letzten Monat", "value": "last month"},
                    {"name": "Dieses Jahr", "value": "this year"},
                    {"name": "Gesamte Laufzeit", "value": "all"}
                ]
            },
            {
                "type": 3,
                "name": "user",
                "description": "Nutzer filtern (all, me oder Username/ID)",
                "required": False
            }
        ]
    },
    {
        "name": "account",
        "description": "Zeigt das Guthaben bzw. den Kontostand an",
        "options": [
            {
                "type": 3,
                "name": "user",
                "description": "Nutzer auswählen (Standard: me, oder 'all', Username, Mention)",
                "required": False
            }
        ]
    },
    {
        "name": "cash",
        "description": "Guthaben-Verwaltung (Nur für Administratoren)",
        "default_member_permissions": "8",
        "options": [
            {
                "type": 1,
                "name": "add",
                "description": "Fügt einem Nutzer Guthaben hinzu (z. B. nach Twint / Revolut)",
                "options": [
                    {
                        "type": 3,
                        "name": "user",
                        "description": "Nutzer auswählen (@Mention, me, ID oder Username)",
                        "required": True
                    },
                    {
                        "type": 10,
                        "name": "amount",
                        "description": "Betrag der Zahlung",
                        "required": True
                    },
                    {
                        "type": 3,
                        "name": "currency",
                        "description": "Währung der Zahlung",
                        "required": False,
                        "choices": [
                            {"name": "CHF (Schweizer Franken)", "value": "CHF"},
                            {"name": "EUR (Euro)", "value": "EUR"}
                        ]
                    },
                    {
                        "type": 3,
                        "name": "note",
                        "description": "Notiz (z. B. 'Twint Zahlung')",
                        "required": False
                    }
                ]
            }
        ]
    },
    {
        "name": "addgameaccount",
        "description": "Verknüpft deinen Ingame-Namen mit deinem Discord-Profil",
        "options": [
            {
                "type": 3,
                "name": "game",
                "description": "Spielname (z. B. minecraft)",
                "required": True
            },
            {
                "type": 3,
                "name": "username",
                "description": "Dein Ingame-Name (z. B. gamesbond00)",
                "required": True
            }
        ]
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
        lines = [
            "📖 **Verfügbare Server-Befehle:**\n",
            "• `/start [game] [duration] [log]` — Startet den Server (Logs: none, game, all)",
            "• `/status` — Zeigt alle aktiven Server samt IP an",
            "• `/log <mode>` — Schaltet Logs um (`all`, `game`, `off`)",
            "• `/stop` — Stoppt und sichert den laufenden Server",
            "• `/costs [timeframe] [user]` — Zeigt Abrechnung & Spielzeiten",
            "• `/account [user]` — Zeigt Guthaben / Kontostand (`me`, `all`, `@user`)",
            "• `/cash add <user> <amount> [currency] [note]` — *(Admin)* Guthaben aufladen",
            "• `/addgameaccount <game> <username>` — Verknüpft dein Profil",
            "• `/help` — Zeigt diese Übersicht an"
        ]
        cache_content = "\n".join(lines)
        cache_path = os.path.join(os.path.dirname(__file__), "..", "aws_lambda", "commands_cache.txt")
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(cache_content)
        print(f"Befehls-Cache aktualisiert unter: {cache_path}")
except Exception as e:
    print("Fehler bei Discord-Registrierung:", e)
    exit(1)