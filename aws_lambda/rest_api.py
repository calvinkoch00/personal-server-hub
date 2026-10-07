import os
import re
import json
from services import hetzner, agent, supabase, fx

def handle_start(payload: dict) -> tuple[int, dict]:
    game = payload.get("game", "minecraft").strip().lower()
    duration_raw = str(payload.get("duration", "5m")).strip().lower()
    server_type = payload.get("server_type", "cpx32")
    log_mode = str(payload.get("log", payload.get("logging", "none"))).strip().lower()

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

    result = hetzner.create_server(
        game=game,
        seconds=seconds,
        readable=readable,
        server_type=server_type,
        enable_logging=log_mode
    )
    return 200, {
        "message": "Server gestartet",
        "discord_summary": f"🎮 {result['game'].upper()} gestartet! IP: `{result['ip']}` ({result['lifetime_readable']})",
        "data": result,
        "log_mode": log_mode
    }

def handle_servers() -> tuple[int, dict]:
    return 200, {"data": hetzner.list_servers()}

def handle_stop(payload: dict) -> tuple[int, dict]:
    servers = hetzner.list_servers()
    if not servers:
        return 400, {"error": "Kein laufender Server vorhanden"}

    server_id = payload.get("server_id")
    target = next((s for s in servers if str(s["server_id"]) == str(server_id)), servers[0])
    target_ip = target.get("ip")
    target_id = str(target.get("server_id"))

    graceful_success = False
    if target_ip:
        try:
            res = agent.stop_remote_server(target_ip)
            if res.get("status") == "stopping":
                graceful_success = True
        except Exception as e:
            print(f"[REST_API] Agent auf {target_ip} nicht erreichbar: {e}")

    if graceful_success:
        return 200, {
            "message": f"Shutdown für {target['name']} eingeleitet",
            "target": target,
            "mode": "graceful"
        }
    else:
        delete_res = hetzner.delete_server(target_id)
        return 200, {
            "message": f"Server {target['name']} direkt via Hetzner-API gelöscht",
            "hetzner_action": delete_res.get("action"),
            "target": target,
            "mode": "direct"
        }
    
def handle_log(payload: dict) -> tuple[int, dict]:
    servers = hetzner.list_servers()
    if not servers:
        return 400, {"error": "Kein aktiver Server online."}

    mode = str(payload.get("mode", "game")).strip().lower()
    try:
        res = agent.toggle_remote_logging(servers[0]["ip"], mode=mode)
        return 200, res
    except Exception as e:
        return 500, {"error": f"Agent auf VM nicht erreichbar: {e}"}

def handle_costs(payload: dict) -> tuple[int, dict]:
    status, resp_text = supabase.supabase_client_request("rpc/get_costs_summary", method="POST", data=payload)
    if status not in [200, 201]:
        return status, {"error": f"Fehler beim Abrufen der Abrechnung ({status}): {resp_text}"}
    return 200, {"rows": json.loads(resp_text)}

def handle_account(payload: dict) -> tuple[int, dict]:
    user_param = payload.get("user", "me")
    if str(user_param).lower() == "all":
        status, resp_text = supabase.supabase_client_request("view_user_balances?select=*&order=current_balance_eur.asc", method="GET")
        if status == 200:
            return 200, {"mode": "all", "rows": json.loads(resp_text)}
        return status, {"error": f"Fehler beim Abrufen der Kontostände ({status}): {resp_text}"}

    target_uid = payload.get("target_uid")
    status, resp_text = supabase.supabase_client_request(f"view_user_balances?discord_user_id=eq.{target_uid}", method="GET")
    if status == 200:
        rows = json.loads(resp_text)
        return 200, {"mode": "single", "user": rows[0] if rows else None}
    return status, {"error": f"Fehler beim Abrufen des Kontos ({status}): {resp_text}"}

def handle_exchange_rate(payload: dict) -> tuple[int, dict]:
    base = payload.get("base") or payload.get("from") or "CHF"
    target = payload.get("target") or payload.get("to") or "EUR"
    rate, source, rate_id = fx.get_exchange_rate(base_currency=base, target_currency=target)
    return 200, {
        "base_currency": base.upper(),
        "target_currency": target.upper(),
        "rate": rate,
        "source": source,
        "rate_id": rate_id
    }

def handle_cash(payload: dict) -> tuple[int, dict]:
    target_uid = payload.get("target_uid")
    amount_orig = float(payload.get("amount", 0.0))
    currency = payload.get("currency", "CHF").upper()
    target_currency = payload.get("target_currency", "EUR").upper()
    note = payload.get("note", "Einzahlung")
    caller_name = payload.get("created_by", "Admin")

    fx_rate, fx_source, rate_id = fx.get_exchange_rate(
        base_currency=currency,
        target_currency=target_currency
    )

    if currency != target_currency:
        fx_text = f" *(Wechselkurs 1 {currency} = {fx_rate:.4f} {target_currency} [{fx_source}])* "
    else:
        fx_text = ""

    amount_target = round(amount_orig * fx_rate, 2)
    payment_data = {
        "discord_user_id": target_uid,
        "amount_original": amount_orig,
        "currency": currency,
        "exchange_rate": fx_rate,
        "exchange_rate_id": rate_id,
        "amount_eur": amount_target,
        "note": note,
        "created_by": caller_name
    }

    status_p, resp_p = supabase.supabase_client_request("fact_user_payments", method="POST", data=payment_data)
    if status_p in [200, 201]:
        return 200, {
            "payment": payment_data,
            "fx_text": fx_text
        }
    return status_p, {"error": f"Fehler beim Speichern der Zahlung ({status_p}): {resp_p}"}

def handle_addgameaccount(payload: dict) -> tuple[int, dict]:
    discord_user_id = str(payload.get("discord_user_id"))
    discord_username = str(payload.get("discord_username", "Unknown"))
    game = str(payload.get("game", "")).strip().lower()
    username = str(payload.get("username", "")).strip()

    if not game or not username:
        return 400, {"error": "Felder 'game' und 'username' sind erforderlich"}

    supabase.supabase_client_request(
        "dim_users",
        method="POST",
        data={"discord_user_id": discord_user_id, "discord_username": discord_username},
        headers_extra={"Prefer": "resolution=merge-duplicates"}
    )

    endpoint_check = f"dim_game_accounts?game=eq.{game}&ingame_username=ilike.{username}&select=discord_user_id"
    status_check, resp_check = supabase.supabase_client_request(endpoint_check, method="GET")
    existing_accounts = json.loads(resp_check) if status_check == 200 else []

    if existing_accounts:
        owner_id = str(existing_accounts[0].get("discord_user_id"))
        if owner_id == discord_user_id:
            return 200, {"status": "already_linked_self", "game": game, "username": username}
        return 403, {"status": "forbidden", "game": game, "username": username}

    status_a, resp_a = supabase.supabase_client_request(
        "dim_game_accounts",
        method="POST",
        data={
            "discord_user_id": discord_user_id,
            "game": game,
            "ingame_username": username
        },
        headers_extra={"Prefer": "return=representation"}
    )
    if status_a in [200, 201]:
        return 200, {"status": "created", "game": game, "username": username}
    return status_a, {"error": f"Fehler beim Verknüpfen ({status_a}): {resp_a}"}

def route_request(path: str, body: dict) -> tuple[int, dict]:
    raw_path = path or "/"
    action = body.get("action")

    if raw_path.endswith("/start") or action == "start":
        return handle_start(body)
    if raw_path.endswith("/servers") or action == "list":
        return handle_servers()
    if raw_path.endswith("/stop") or action == "stop":
        return handle_stop(body)
    if raw_path.endswith("/log") or action == "log":
        return handle_log(body)
    if raw_path.endswith("/costs"):
        return handle_costs(body)
    if raw_path.endswith("/account"):
        return handle_account(body)
    if raw_path.endswith("/cash"):
        return handle_cash(body)
    if raw_path.endswith("/exchange-rate") or action == "exchange_rate":
        return handle_exchange_rate(body)
    if raw_path.endswith("/addgameaccount") or action == "addgameaccount":
        return handle_addgameaccount(body)

    return 404, {"error": f"Endpoint '{raw_path}' nicht gefunden"}