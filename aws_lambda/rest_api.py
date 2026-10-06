import re
from services import hetzner
from services.agent import call_agent_remote
from services.supabase import supabase_client_request, upsert_game_account


def handle_rest_request(raw_path: str, body: dict) -> tuple[int, dict]:
    path = (raw_path or "").rstrip("/").lower()
    action = body.get("action", "")

    # ==========================
    # 1. Server Start
    # ==========================
    if path.endswith("/start") or action == "start":
        game = body.get("game", "minecraft").strip().lower()
        duration_raw = str(body.get("duration", "5m")).strip().lower()
        server_type = body.get("server_type", "cpx32")
        log_mode = str(body.get("log", body.get("logging", "none"))).strip().lower()

        if log_mode in ["true", "1"]:
            log_mode = "game"
        elif log_mode in ["false", "0"]:
            log_mode = "none"

        unit_map = {"m": 60, "h": 3600, "d": 86400}
        readable_map = {"m": "Minute(n)", "h": "Stunde(n)", "d": "Tag(e)"}
        match = re.match(r"^(\d+)\s*([mhd])$", duration_raw)
        if match:
            val, unit = int(match.group(1)), match.group(2)
            seconds = val * unit_map[unit]
            readable = f"{val} {readable_map[unit]}"
        else:
            seconds = 300
            readable = "5 Minute(n)"

        try:
            res = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                server_type=server_type,
                enable_logging=log_mode
            )
            return 200, {
                "message": "Server gestartet",
                "data": res,
                "readable_duration": readable,
                "log_mode": log_mode
            }
        except Exception as e:
            return 500, {"error": f"Fehler beim Starten: {e}"}

    # ==========================
    # 2. Server Liste / Status
    # ==========================
    if path.endswith("/servers") or path.endswith("/status") or action == "list":
        try:
            servers = hetzner.list_servers()
            return 200, {"servers": servers}
        except Exception as e:
            return 500, {"error": str(e)}

    # ==========================
    # 3. Server Stop
    # ==========================
    if path.endswith("/stop") or action == "stop":
        servers = hetzner.list_servers()
        if not servers:
            return 404, {"error": "Kein aktiver Server vorhanden"}

        server_id = body.get("server_id")
        target = next((s for s in servers if str(s["server_id"]) == str(server_id)), servers[0])
        target_ip = target.get("ip")
        target_id = str(target.get("server_id"))

        graceful = False
        if target_ip:
            try:
                if hasattr(hetzner, "trigger_server_graceful_stop"):
                    hetzner.trigger_server_graceful_stop(target_ip, target_id)
                    graceful = True
                else:
                    call_agent_remote(target_ip, "stop")
                    graceful = True
            except Exception:
                graceful = False

        delete_res = hetzner.delete_server(target_id)
        return 200, {
            "message": f"Server {target['name']} gelöscht",
            "name": target["name"],
            "server_id": target_id,
            "graceful": graceful,
            "action": delete_res.get("action")
        }

    # ==========================
    # 4. Logs Umschalten
    # ==========================
    if path.endswith("/log") or action == "log":
        servers = hetzner.list_servers()
        if not servers:
            return 404, {"error": "Kein aktiver Server online"}

        mode = body.get("mode", "game")
        res = call_agent_remote(servers[0]["ip"], "toggle-log", data={"mode": mode})
        if not res:
            return 502, {"error": "Agent auf VM nicht erreichbar"}
        return 200, res

    # ==========================
    # 5. Ingame-Account Verknüpfung
    # ==========================
    if path.endswith("/addgameaccount") or action == "addgameaccount":
        discord_user_id = body.get("discord_user_id")
        discord_username = body.get("discord_username", "Unknown")
        game = body.get("game")
        username = body.get("username")

        if not discord_user_id or not game or not username:
            return 400, {"error": "Felder 'discord_user_id', 'game' und 'username' sind erforderlich"}

        res = upsert_game_account(discord_user_id, discord_username, game, username)
        return 200, res

    return 404, {"error": f"Endpoint '{raw_path}' nicht gefunden"}