import os
import sys

# Sicherstellen, dass relative Unterordner in Lambda sauber importiert werden
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from commands.server import handle_start, handle_stop, handle_status, handle_log
from commands.finance import handle_costs, handle_account, handle_cash
from commands.accounts import handle_addgameaccount

def get_help_message() -> str:
    cache_path = os.path.join(os.path.dirname(__file__), "commands_cache.txt")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    return (
        "📖 **Verfügbare Server-Befehle:**\n\n"
        "• `/start` — Startet den Server (Felder: `game`, `duration`, `log`)\n"
        "• `/status` — Zeigt alle aktiven Server samt IP an\n"
        "• `/log <mode>` — Schaltet Logs um (`all`, `game`, `off`)\n"
        "• `/stop` — Stoppt und löscht den laufenden Server\n"
        "• `/costs` — Zeigt Serverkosten und Spielzeiten an (`timeframe`, `user`)\n"
        "• `/account` — Zeigt dein aktuelles Guthaben / Kontostand\n"
        "• `/cash add` — *(Admin)* Guthabeneinzahlung für einen Nutzer buchen\n"
        "• `/addgameaccount` — Verknüpft deinen Ingame-Namen mit Discord\n"
        "• `/help` — Zeigt diese Übersicht an"
    )


COMMAND_HANDLERS = {
    "start": handle_start,
    "status": handle_status,
    "stop": handle_stop,
    "log": handle_log,
    "costs": handle_costs,
    "account": handle_account,
    "cash": handle_cash,
    "addgameaccount": handle_addgameaccount,
    "help": lambda body, data: get_help_message(),
}


def handle_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    # Type 1: Discord PING -> PONG
    if interaction_type == 1:
        return {"statusCode": 200, "body": {"type": 1}}

    if interaction_type != 2:
        return {"statusCode": 400, "body": {"error": "Unsupported interaction type"}}

    data = body.get("data", {})
    command = data.get("name")
    handler = COMMAND_HANDLERS.get(command)

    if not handler:
        msg = f"Unbekannter Befehl: `/{command}`"
    else:
        msg = handler(body, data)

    return {
        "statusCode": 200,
        "body": {
            "type": 4,
            "data": {"content": msg}
        }
    }