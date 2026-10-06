import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from commands.server import start_server_logic, stop_server_logic, list_servers_logic, toggle_log_logic
from commands.finance import handle_costs, handle_account, handle_cash
from commands.accounts import handle_addgameaccount


def handle_discord_start(body: dict, data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    try:
        res = start_server_logic(
            game=str(options.get("game", "minecraft")),
            duration_raw=str(options.get("duration", "5m")),
            log_mode=str(options.get("log", "none"))
        )
        data_res = res["data"]
        addr = f"`{data_res.get('domain')}` (IP: `{data_res.get('ip')}`)" if data_res.get("domain") else f"`{data_res.get('ip')}`"
        return (
            f"🟡 **Hardware wird hochgefahren!**\n"
            f"🎮 **Spiel:** {data_res.get('game', '').upper()}\n"
            f"🌐 **Adresse:** {addr}\n"
            f"⏳ **Laufzeit:** {data_res.get('lifetime_readable')}\n\n"
            f"*(Bereitschaftsmeldung folgt automatisch!)*"
        )
    except Exception as e:
        return f"❌ Fehler beim Starten des Servers: {e}"


def handle_discord_stop(body: dict, data: dict) -> str:
    res = stop_server_logic()
    if res.get("status") == "error":
        return f"⚪ {res.get('message')}"
    return f"🛑 **Shutdown für `{res.get('name')}` eingeleitet.**"


def handle_discord_status(body: dict, data: dict) -> str:
    servers = list_servers_logic()
    if not servers:
        return "⚪ Es läuft aktuell kein Server."
    lines = [f"• `{s['name']}` (ID: {s['server_id']}) — `{s.get('status', 'unknown')}` — IP: `{s['ip']}`" for s in servers]
    return "🟢 **Aktive Server:**\n" + "\n".join(lines)


def handle_discord_log(body: dict, data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    mode = str(options.get("mode", "game")).strip().lower()
    res = toggle_log_logic(mode)
    if "error" in res:
        return f"⚠️ {res.get('error')}"
    return f"📡 **Live-Logs wurden umgestellt auf: `{mode.upper()}`**"


COMMAND_HANDLERS = {
    "start": handle_discord_start,
    "status": handle_discord_status,
    "stop": handle_discord_stop,
    "log": handle_discord_log,
    "costs": handle_costs,
    "account": handle_account,
    "cash": handle_cash,
    "addgameaccount": handle_addgameaccount,
}


def handle_interaction(body: dict) -> dict:
    if body.get("type") == 1:
        return {"statusCode": 200, "body": {"type": 1}}
    if body.get("type") != 2:
        return {"statusCode": 400, "body": {"error": "Unsupported interaction type"}}

    command = body.get("data", {}).get("name")
    handler = COMMAND_HANDLERS.get(command)
    msg = handler(body, body.get("data", {})) if handler else f"Unbekannter Befehl: `/{command}`"

    return {"statusCode": 200, "body": {"type": 4, "data": {"content": msg}}}