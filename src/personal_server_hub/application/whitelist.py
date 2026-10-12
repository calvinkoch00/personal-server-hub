import json

from personal_server_hub.integrations import agent, hetzner, supabase


def resolve_server_slug(raw_name: str | None, game: str = "minecraft") -> str:
    cleaned = str(raw_name or "").strip().lower().replace(" ", "_")
    if not cleaned or cleaned in ["default", f"{game}-default"]:
        return f"{game}-default"
    return cleaned



def add_whitelist(payload: dict) -> tuple[int, dict]:
    game = str(payload.get("game", "minecraft")).strip().lower()
    server_slug = resolve_server_slug(payload.get("server") or payload.get("server_name") or payload.get("server_slug"), game=game)
    raw_user = str(payload.get("username", "")).strip()
    caller_id = str(payload.get("discord_user_id", ""))
    target_role = "server-admin" if payload.get("role") in ["server-admin", "admin"] else "player"

    if not raw_user:
        return 400, {"error": "Parameter 'username' fehlt"}

    status_s, resp_s = supabase.supabase_client_request(
        f"dim_servers?game=eq.{game}&server_slug=eq.{server_slug}&status=neq.deleted", method="GET"
    )
    if status_s != 200 or not json.loads(resp_s):
        return 404, {"error": f"Server '{server_slug}' nicht gefunden"}
    srv = json.loads(resp_s)[0]
    srv_id = srv["server_id"]
    vm_full_name = srv.get("full_name")

    status_u, resp_u = supabase.supabase_client_request(f"dim_users?discord_user_id=eq.{caller_id}&select=role", method="GET")
    caller_global_role = json.loads(resp_u)[0].get("role") if status_u == 200 and json.loads(resp_u) else "user"

    is_superadmin = caller_global_role == "superadmin"
    is_server_creator = srv.get("created_by") == caller_id

    status_acc, resp_acc = supabase.supabase_client_request(
        f"dim_game_accounts?game=eq.{game}&ingame_username=ilike.{raw_user}&select=id,discord_user_id,ingame_username", method="GET"
    )
    accounts = json.loads(resp_acc) if status_acc == 200 else []
    if not accounts:
        return 404, {"error": f"Account '{raw_user}' ist noch nicht via /addgameaccount registriert."}
    acc = accounts[0]
    acc_id = acc["id"]
    acc_discord_id = str(acc["discord_user_id"])
    canonical_user = acc["ingame_username"]

    if not (is_superadmin or is_server_creator):
        if srv.get("whitelist_policy") == "admin_only":
            return 403, {"error": "Nur Administratoren dürfen Spieler zu diesem Server hinzufügen."}
        if acc_discord_id != caller_id:
            return 403, {"error": "Du kannst dich bei dieser Policy nur selbst hinzufügen."}

    status_exist, resp_exist = supabase.supabase_client_request(
        f"map_server_whitelist?server_id=eq.{srv_id}&account_id=eq.{acc_id}&select=id,role",
        method="GET"
    )
    existing_wl = json.loads(resp_exist) if status_exist == 200 else []

    action_type = "added"
    if existing_wl:
        wl_id = existing_wl[0]["id"]
        status_w, resp_w = supabase.supabase_client_request(
            f"map_server_whitelist?id=eq.{wl_id}",
            method="PATCH",
            data={"role": target_role}
        )
        action_type = "updated"
    else:
        wl_payload = {
            "server_id": srv_id,
            "account_id": acc_id,
            "discord_user_id": acc_discord_id,
            "role": target_role
        }
        status_w, resp_w = supabase.supabase_client_request(
            "map_server_whitelist",
            method="POST",
            data=wl_payload
        )

    if status_w not in [200, 201, 204]:
        return status_w, {"error": f"Fehler beim Speichern der Whitelist: {resp_w}"}

    live_synced = False
    active_servers = hetzner.list_servers()
    matched_vm = next((s for s in active_servers if s.get("name") == vm_full_name), None)

    if matched_vm and matched_vm.get("ip"):
        try:
            is_op = (target_role == "server-admin")
            res_agent = agent.add_remote_whitelist(matched_vm["ip"], canonical_user, is_op=is_op)
            live_synced = res_agent.get("status") == "ok"
            if srv.get("status") == "offline" and res_agent.get("status") == "ok":
                supabase.supabase_client_request(
                    f"dim_servers?server_id=eq.{srv_id}",
                    method="PATCH",
                    data={"status": "online"}
                )
        except Exception as e:
            print(f"[WHITELIST SYNC ERROR] {e}")

    return 200, {
        "status": action_type,
        "username": canonical_user,
        "server": srv["display_name"],
        "role": target_role,
        "live_synced": live_synced,
    }


def remove_whitelist(payload: dict) -> tuple[int, dict]:
    game = str(payload.get("game", "minecraft")).strip().lower()
    server_slug = resolve_server_slug(payload.get("server") or payload.get("server_name") or payload.get("server_slug"), game=game)
    raw_user = str(payload.get("username", "")).strip()
    caller_id = str(payload.get("discord_user_id", ""))

    if not raw_user:
        return 400, {"error": "Parameter 'username' fehlt"}

    status_s, resp_s = supabase.supabase_client_request(
        f"dim_servers?game=eq.{game}&server_slug=eq.{server_slug}&status=neq.deleted", method="GET"
    )
    if status_s != 200 or not json.loads(resp_s):
        return 404, {"error": f"Server '{server_slug}' nicht gefunden"}
    srv = json.loads(resp_s)[0]
    srv_id = srv["server_id"]
    vm_full_name = srv.get("full_name")

    status_u, resp_u = supabase.supabase_client_request(f"dim_users?discord_user_id=eq.{caller_id}&select=role", method="GET")
    caller_global_role = json.loads(resp_u)[0].get("role") if status_u == 200 and json.loads(resp_u) else "user"
    if caller_global_role != "superadmin" and srv.get("created_by") != caller_id:
        return 403, {"error": "Nur Server-Admins können Spieler von der Whitelist entfernen."}

    status_acc, resp_acc = supabase.supabase_client_request(
        f"dim_game_accounts?game=eq.{game}&ingame_username=ilike.{raw_user}&select=id,ingame_username", method="GET"
    )
    accounts = json.loads(resp_acc) if status_acc == 200 else []
    if not accounts:
        return 404, {"error": f"Account '{raw_user}' nicht gefunden"}
    acc_id = accounts[0]["id"]
    canonical_user = accounts[0]["ingame_username"]

    supabase.supabase_client_request(
        f"map_server_whitelist?server_id=eq.{srv_id}&account_id=eq.{acc_id}",
        method="DELETE"
    )

    live_synced = False
    active_servers = hetzner.list_servers()
    matched_vm = next((s for s in active_servers if s.get("name") == vm_full_name), None)

    if matched_vm and matched_vm.get("ip"):
        try:
            res_agent = agent.remove_remote_whitelist(matched_vm["ip"], canonical_user)
            live_synced = res_agent.get("status") == "ok"
        except Exception as e:
            print(f"[WHITELIST SYNC ERROR] {e}")

    return 200, {
        "status": "removed",
        "username": canonical_user,
        "server": srv["display_name"],
        "live_synced": live_synced,
    }


def list_whitelist(payload: dict) -> tuple[int, dict]:
    game = str(payload.get("game", "minecraft")).strip().lower()
    server_slug = resolve_server_slug(payload.get("server") or payload.get("server_name") or payload.get("server_slug"), game=game)

    status_s, resp_s = supabase.supabase_client_request(
        f"dim_servers?game=eq.{game}&server_slug=eq.{server_slug}&status=neq.deleted", method="GET"
    )
    if status_s != 200 or not json.loads(resp_s):
        return 404, {"error": f"Server '{server_slug}' nicht gefunden"}
    srv = json.loads(resp_s)[0]

    status_w, resp_w = supabase.supabase_client_request(
        f"map_server_whitelist?server_id=eq.{srv['server_id']}&select=role,dim_game_accounts(ingame_username,mojang_uuid)",
        method="GET"
    )
    rows = json.loads(resp_w) if status_w == 200 else []
    return 200, {
        "server": srv["display_name"],
        "policy": srv["whitelist_policy"],
        "entries": rows,
    }

