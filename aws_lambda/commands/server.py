import re
from services import hetzner
from services.agent import call_agent_remote


# ==========================================
# 1. Zentrale Geschäftslogik (für REST & Discord)
# ==========================================

def start_server_logic(game: str = "minecraft", duration_raw: str = "5m", server_type: str = "cpx32", log_mode: str = "none") -> dict:
    unit_map = {"m": 60, "h": 3600, "d": 86400}
    readable_map = {"m": "Minute(n)", "h": "Stunde(n)", "d": "Tag(e)"}

    match = re.match(r"^(\d+)\s*([mhd])$", str(duration_raw).lower().strip())
    if match:
        val, unit = int(match.group(1)), match.group(2)
        seconds = val * unit_map[unit]
        readable = f"{val} {readable_map[unit]}"
    else:
        seconds = 300
        readable = "5 Minute(n)"

    mode = str(log_mode).lower().strip()
    if mode in ["true", "1"]:
        mode = "game"
    elif mode in ["false", "0"]:
        mode = "none"

    res = hetzner.create_server(
        game=game,
        seconds=seconds,
        readable=readable,
        server_type=server_type,
        enable_logging=mode
    )
    return {
        "status": "ok",
        "data": res,
        "readable_duration": readable,
        "log_mode": mode
    }


def stop_server_logic(server_id: str = None) -> dict:
    servers = hetzner.list_servers()
    if not servers:
        return {"status": "error", "message": "Kein laufender Server zum Stoppen vorhanden."}

    target = next((s for s in servers if str(s["server_id"]) == str(server_id)), servers[0])
    target_ip = target.get("ip")
    target_id = str(target.get("server_id"))

    graceful_success = False
    if target_ip:
        try:
            if hasattr(hetzner, "trigger_server_graceful_stop"):
                hetzner.trigger_server_graceful_stop(target_ip, target_id)
                graceful_success = True
            else:
                call_agent_remote(target_ip, "stop")
                graceful_success = True
        except Exception:
            graceful_success = False

    delete_res = hetzner.delete_server(target_id)
    return {
        "status": "ok",
        "name": target["name"],
        "server_id": target_id,
        "graceful": graceful_success,
        "action": delete_res.get("action")
    }


def list_servers_logic() -> list:
    return hetzner.list_servers()


def toggle_log_logic(mode: str = "game") -> dict:
    servers = hetzner.list_servers()
    if not servers:
        return {"status": "error", "message": "Kein aktiver Server online."}
    
    target_ip = servers[0].get("ip")
    res = call_agent_remote(target_ip, "toggle-log", data={"mode": mode})
    return {
        "status": "ok" if res else "error",
        "mode": res.get("mode", mode) if res else mode
    }


# ==========================================
# 2. Discord-Handler (Exakt gleiche Antworten)
# ==========================================

def handle_status(body: dict, data: dict) -> str:
    servers = list_servers_logic()
    if not servers:
        return "⚪ Es läuft aktuell kein Server."
    lines = [
        f"• `{s['name']}` (ID: {s['server_id']}) — `{s.get('status', 'unknown')}` — IP: `{s['ip']}`"
        for s in servers
    ]
    return "🟢 **Aktive Server:**\n" + "\n".join(lines)


def handle_stop(body: dict, data: dict) -> str:
    result = stop_server_logic()
    if result["status"] == "error":
        return f"⚪ {result['message']}"

    if result.get("graceful"):
        return f"🛑 **Shutdown für `{result['name']}` eingeleitet.** (Container sichern & VM löschen)"
    return f"🛑 **Server `{result['name']}` direkt via Hetzner-API gelöscht.**"


def handle_start(body: dict, data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    game = str(options.get("game", "minecraft")).strip().lower()
    duration_raw = str(options.get("duration", "5m")).strip().lower()
    log_mode = str(options.get("log", "none")).strip().lower()

    try:
        outcome = start_server_logic(
            game=game,
            duration_raw=duration_raw,
            server_type="cpx32",
            log_mode=log_mode
        )
        res = outcome["data"]
        readable = outcome["readable_duration"]
        actual_log_mode = outcome["log_mode"]

        addr = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get("domain") else f"`{res.get('ip')}`"
        log_labels = {"none": "⚪ Aus", "game": "🎮 Nur Game", "all": "📡 Alles (Game + System)"}

        return (
            f"🟡 **Hardware wird hochgefahren!**\n"
            f"🎮 **Spiel:** {res.get('game', '').upper()}\n"
            f"🌐 **Adresse:** {addr}\n"
            f"⏳ **Laufzeit:** {readable}\n"
            f"📋 **Live-Logs:** {log_labels.get(actual_log_mode, actual_log_mode)}\n\n"
            f"*(Bereitschaftsmeldung folgt automatisch, sobald der Server beitretbar ist!)*"
        )
    except Exception as e:
        return f"❌ Fehler beim Starten des Servers: {e}"


def handle_log(body: dict, data: dict) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    mode = str(options.get("mode", "game")).strip().lower()

    result = toggle_log_logic(mode)
    if result["status"] == "error" and "Kein aktiver Server" in result.get("message", ""):
        return "⚪ Kein aktiver Server online."
    elif result["status"] == "error":
        return "⚠ Agent auf VM nicht erreichbar."

    cur_mode = result.get("mode", mode)
    return f"📡 **Live-Logs wurden umgestellt auf: `{cur_mode.upper()}`**"