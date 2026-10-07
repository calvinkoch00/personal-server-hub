import os
import re
import json
from datetime import datetime, timezone
from services import hetzner, agent, supabase, fx, dns, mojang

def resolve_server_slug(raw_name: str | None, game: str = "minecraft") -> str:
    cleaned = str(raw_name or "").strip().lower().replace(" ", "_")
    if not cleaned or cleaned in ["default", f"{game}-default"]:
        return f"{game}-default"
    return cleaned

def handle_start(payload: dict) -> tuple[int, dict]:
    game = str(payload.get("game", "minecraft")).strip().lower()
    server_slug = resolve_server_slug(payload.get("server_name") or payload.get("name") or payload.get("server_slug"), game=game)
    duration_raw = str(payload.get("duration", "5m")).strip().lower()
    server_type = payload.get("server_type")
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

    try:
        result = hetzner.create_server(
            game=game,
            server_name=server_slug,
            seconds=seconds,
            readable=readable,
            server_type=server_type,
            enable_logging=log_mode
        )
        return 200, {
            "message": "Server gestartet",
            "discord_summary": f"🎮 `{result['name']}` gestartet! IP: `{result['ip']}` | DNS: `{result.get('domain')}` ({result['lifetime_readable']})",
            "data": result,
            "log_mode": log_mode
        }
    except Exception as e:
        return 500, {"error": f"Serverstart fehlgeschlagen: {str(e)}"}

def handle_servers() -> tuple[int, dict]:
    status, resp = supabase.supabase_client_request("dim_servers?status=neq.deleted&order=game.asc,server_slug.asc", method="GET")
    if status == 200:
        return 200, {"servers": json.loads(resp)}
    return 200, {"data": hetzner.list_servers()}

def handle_stop(payload: dict) -> tuple[int, dict]:
    servers = hetzner.list_servers()
    if not servers:
        return 400, {"error": "Kein laufender Server vorhanden"}

    raw_identifier = str(
        payload.get("server_id")
        or payload.get("server_name")
        or payload.get("name")
        or payload.get("server_slug")
        or ""
    ).strip().lower()

    target = None

    if raw_identifier:
        # 1. Direkter Abgleich über numerische Hetzner-ID
        for s in servers:
            if str(s.get("server_id")) == raw_identifier:
                target = s
                break

        # 2. Falls nicht über ID gefunden: Abgleich über Server-Name / Slug
        if not target:
            raw_slug = raw_identifier.replace(" ", "_")
            for s in servers:
                s_name = s.get("name", "").lower()
                if (
                    raw_identifier in s_name
                    or s_name.endswith(f"-{raw_slug}")
                    or s_name == f"server-minecraft-{raw_slug}"
                ):
                    target = s
                    break

        if not target:
            return 404, {"error": f"Kein laufender Server mit Namen oder ID '{raw_identifier}' gefunden."}
    else:
        target = servers[0]

    target_ip = target.get("ip")
    target_id = str(target.get("server_id"))

    # 1. Server in Supabase finden
    status_srv, resp_srv = supabase.supabase_client_request(
        f"dim_servers?full_name=eq.{target['name']}",
        method="GET"
    )
    db_servers = json.loads(resp_srv) if status_srv == 200 else []

    subdomains_to_reset = set()
    srv_id = None

    if db_servers:
        srv_row = db_servers[0]
        srv_id = srv_row.get("server_id")

        # Status auf offline setzen
        supabase.supabase_client_request(
            f"dim_servers?server_id=eq.{srv_id}",
            method="PATCH",
            data={"status": "offline"}
        )

        # 1. Prio: Verknüpfte Records über server_id
        status_dns, resp_dns = supabase.supabase_client_request(
            f"dim_dns_records?server_id=eq.{srv_id}&select=subdomain",
            method="GET"
        )
        if status_dns == 200 and json.loads(resp_dns):
            for d in json.loads(resp_dns):
                if d.get("subdomain"):
                    subdomains_to_reset.add(d["subdomain"])

    # 2. Prio: Alle DNS-Records finden, die aktuell auf die target_ip dieses Servers zeigen
    if target_ip:
        status_ip_dns, resp_ip_dns = supabase.supabase_client_request(
            f"dim_dns_records?record_value=eq.{target_ip}&select=subdomain",
            method="GET"
        )
        if status_ip_dns == 200 and json.loads(resp_ip_dns):
            for d in json.loads(resp_ip_dns):
                if d.get("subdomain"):
                    subdomains_to_reset.add(d["subdomain"])

    # Fallback, falls gar nichts gefunden wurde
    if not subdomains_to_reset:
        slug = db_servers[0].get("server_slug", "") if db_servers else ""
        if slug in ["minecraft-default", "default"]:
            subdomains_to_reset.add(os.environ.get("GODADDY_SUBDOMAIN", "mc"))
        elif slug:
            subdomains_to_reset.add(slug)

    # Alle ermittelten Subdomains auf 0.0.0.0 setzen
    for sub in subdomains_to_reset:
        dns.update_godaddy_dns("0.0.0.0", subdomain=sub, server_id=srv_id)

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

def handle_server_create(payload: dict) -> tuple[int, dict]:
    game = str(payload.get("game", "minecraft")).strip().lower()
    raw_slug = resolve_server_slug(payload.get("server_name") or payload.get("name") or payload.get("server_slug"), game=game)
    caller_id = str(payload.get("discord_user_id") or "")
    server_type = payload.get("server_type", "cpx32")
    custom_subdomain = payload.get("custom_subdomain") or payload.get("subdomain")

    if not raw_slug or not re.match(r"^[a-z0-9_-]+$", raw_slug):
        return 400, {"error": "Servername darf nur Kleinbuchstaben, Zahlen, - und _ enthalten"}

    status_c, resp_c = supabase.supabase_client_request(f"dim_servers?server_slug=eq.{raw_slug}&status=neq.deleted", method="GET")
    if status_c == 200 and json.loads(resp_c):
        return 400, {"error": f"Ein aktiver Server mit dem Namen '{raw_slug}' existiert bereits."}

    volume_name = f"vol-{game}-{raw_slug}"[:32]
    vol = hetzner.create_volume(name=volume_name, size_gb=20, location="nbg1")
    volume_id = vol.get("id")
    if not volume_id:
        return 500, {"error": "Hetzner Volume konnte nicht angelegt werden"}

    server_entry = {
        "game": game,
        "server_slug": raw_slug,
        "display_name": f"{game}-{raw_slug}",
        "hetzner_volume_id": volume_id,
        "hetzner_server_type": server_type,
        "status": "offline",
        "created_by": caller_id
    }
    status_sb, resp_sb = supabase.supabase_client_request("dim_servers", method="POST", data=server_entry)
    if status_sb not in [200, 201]:
        hetzner.delete_volume(volume_id)
        return status_sb, {"error": f"Fehler in dim_servers: {resp_sb}"}

    created_server = json.loads(resp_sb)[0]
    srv_id = created_server.get("server_id")

    # Alle Accounts des Erstellers für dieses Spiel automatisch als Admin auf die Whitelist setzen
    creator_accounts_added = []
    if caller_id and srv_id:
        status_acc, resp_acc = supabase.supabase_client_request(
            f"dim_game_accounts?discord_user_id=eq.{caller_id}&game=eq.{game}&select=id,ingame_username",
            method="GET"
        )
        if status_acc == 200:
            creator_accounts = json.loads(resp_acc)
            for acc in creator_accounts:
                acc_id = acc.get("id")
                uname = acc.get("ingame_username")
                if acc_id:
                    wl_payload = {
                        "server_id": srv_id,
                        "account_id": acc_id,
                        "discord_user_id": caller_id,
                        "role": "server-admin"
                    }
                    supabase.supabase_client_request("map_server_whitelist", method="POST", data=wl_payload)
                    creator_accounts_added.append(uname)

    sub_to_use = (custom_subdomain.strip().lower() if custom_subdomain else raw_slug)
    if srv_id and sub_to_use != f"{game}-default":
        dns.update_godaddy_dns("0.0.0.0", subdomain=sub_to_use, server_id=srv_id)

    created_server["subdomain"] = sub_to_use
    created_server["server_slug"] = raw_slug
    created_server["auto_whitelisted"] = creator_accounts_added

    return 201, {
        "message": f"Server '{raw_slug}' erfolgreich erstellt",
        "server": created_server,
        "subdomain": sub_to_use,
        "server_slug": raw_slug,
        "auto_whitelisted": creator_accounts_added
    }

def handle_server_delete(payload: dict) -> tuple[int, dict]:
    game = str(payload.get("game", "minecraft")).strip().lower()
    raw_slug = resolve_server_slug(payload.get("server_name") or payload.get("name") or payload.get("server_slug"), game=game)
    caller_id = payload.get("discord_user_id")

    if raw_slug == f"{game}-default":
        status_u, resp_u = supabase.supabase_client_request(f"dim_users?discord_user_id=eq.{caller_id}&select=role", method="GET")
        user_role = json.loads(resp_u)[0].get("role") if status_u == 200 and json.loads(resp_u) else "user"
        if user_role != "superadmin":
            return 403, {"error": "Nur der Superadmin darf den Default-Server löschen."}

    # Nur aktive (nicht bereits gelöschte) Server finden
    status_s, resp_s = supabase.supabase_client_request(f"dim_servers?game=eq.{game}&server_slug=eq.{raw_slug}&status=neq.deleted", method="GET")
    if status_s != 200 or not json.loads(resp_s):
        return 404, {"error": f"Server '{raw_slug}' nicht gefunden oder bereits gelöscht."}

    srv = json.loads(resp_s)[0]
    srv_id = srv["server_id"]

    # 1. Hetzner Volume löschen
    hetzner.delete_volume(srv["hetzner_volume_id"])

    # 2. DNS-Records ermitteln (über server_id ODER direkt über den Subdomain-Namen)
    subdomains_to_delete = set()
    
    # Abfrage per server_id
    status_dns, resp_dns = supabase.supabase_client_request(f"dim_dns_records?server_id=eq.{srv_id}&select=subdomain", method="GET")
    if status_dns == 200:
        for d in json.loads(resp_dns):
            if d.get("subdomain"):
                subdomains_to_delete.add(d["subdomain"])

    # Fallback: Falls Subdomain gleich raw_slug war
    subdomains_to_delete.add(raw_slug)

    # 3. DNS-Records bei GoDaddy und in dim_dns_records aufräumen
    for sub in subdomains_to_delete:
        if sub and sub != "mc":  # Standard-Domain mc nicht versehentlich löschen
            dns.delete_godaddy_dns(sub)
            supabase.supabase_client_request(f"dim_dns_records?subdomain=eq.{sub}", method="DELETE")

    # 4. In dim_servers auf deleted setzen
    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.supabase_client_request(
        f"dim_servers?server_id=eq.{srv_id}",
        method="PATCH",
        data={"status": "deleted", "deleted_at": now_iso}
    )
    return 200, {"message": f"Server '{srv['display_name']}' und zugehörige DNS-Einträge gelöscht"}

def handle_log(payload: dict) -> tuple[int, dict]:
    raw_mode = str(payload.get("mode", "game")).strip().lower()
    game = str(payload.get("game", "minecraft")).strip().lower()
    server_slug = resolve_server_slug(payload.get("server_name") or payload.get("server_slug") or payload.get("server"), game=game)

    mode = "none" if raw_mode in ["off", "none", "false", "0"] else raw_mode
    if mode not in ["all", "game", "none"]:
        mode = "game"

    status_s, resp_s = supabase.supabase_client_request(
        f"dim_servers?game=eq.{game}&server_slug=eq.{server_slug}&status=neq.deleted",
        method="GET"
    )
    if status_s != 200 or not json.loads(resp_s):
        return 404, {"error": f"Server '{server_slug}' nicht gefunden"}

    srv = json.loads(resp_s)[0]
    srv_id = srv["server_id"]
    vm_full_name = srv.get("full_name")

    supabase.supabase_client_request(
        f"dim_servers?server_id=eq.{srv_id}",
        method="PATCH",
        data={"log_status": mode}
    )

    live_synced = False
    active_servers = hetzner.list_servers()
    matched_vm = next((s for s in active_servers if s.get("name") == vm_full_name), None)

    if matched_vm and matched_vm.get("ip"):
        try:
            agent_mode = "off" if mode == "none" else mode
            res_agent = agent.toggle_remote_logging(matched_vm["ip"], mode=agent_mode)
            live_synced = True
        except Exception as e:
            print(f"[LOG SYNC ERROR] {e}")

    return 200, {
        "server": srv["display_name"],
        "server_slug": server_slug,
        "mode": mode,
        "live_synced": live_synced
    }

def handle_costs(payload: dict) -> tuple[int, dict]:
    status, resp_text = supabase.supabase_client_request("rpc/get_costs_summary", method="POST", data=payload)
    if status not in [200, 201]:
        return status, {"error": f"Fehler beim Abrufen der Abrechnung ({status}): {resp_text}"}
    return 200, {"rows": json.loads(resp_text)}

def handle_account(payload: dict) -> tuple[int, dict]:
    user_param = payload.get("user", "me")
    if str(user_param).lower() == "all":
        status, resp_text = supabase.supabase_client_request("view_user_balances?select=*&order=current_balance.asc", method="GET")
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
        "amount": amount_target,
        "currency": target_currency,
        "payment_amount": amount_orig,
        "payment_currency": currency,
        "exchange_rate": fx_rate,
        "exchange_rate_id": rate_id,
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
    raw_username = str(payload.get("username", "")).strip()

    if not game or not raw_username:
        return 400, {"error": "Felder 'game' und 'username' sind erforderlich"}

    mojang_uuid = None
    username = raw_username

    if game == "minecraft":
        mojang_uuid, official_name = mojang.get_mojang_profile(raw_username)
        if not mojang_uuid:
            return 404, {"error": f"Minecraft-Account `{raw_username}` existiert nicht bei Mojang."}
        username = official_name

    supabase.supabase_client_request(
        "dim_users",
        method="POST",
        data={"discord_user_id": discord_user_id, "discord_username": discord_username},
        headers_extra={"Prefer": "resolution=merge-duplicates"}
    )

    endpoint_check = f"dim_game_accounts?game=eq.{game}&ingame_username=ilike.{username}&select=discord_user_id,mojang_uuid"
    status_check, resp_check = supabase.supabase_client_request(endpoint_check, method="GET")
    existing_accounts = json.loads(resp_check) if status_check == 200 else []

    if existing_accounts:
        owner_id = str(existing_accounts[0].get("discord_user_id"))
        if owner_id == discord_user_id:
            if mojang_uuid and not existing_accounts[0].get("mojang_uuid"):
                supabase.supabase_client_request(
                    f"dim_game_accounts?discord_user_id=eq.{discord_user_id}&game=eq.{game}&ingame_username=ilike.{username}",
                    method="PATCH",
                    data={"mojang_uuid": mojang_uuid}
                )
            return 200, {
                "status": "already_linked_self",
                "game": game,
                "username": username,
                "mojang_uuid": mojang_uuid
            }
        return 403, {"status": "forbidden", "game": game, "username": username}

    account_payload = {
        "discord_user_id": discord_user_id,
        "game": game,
        "ingame_username": username,
        "mojang_uuid": mojang_uuid
    }
    status_a, resp_a = supabase.supabase_client_request(
        "dim_game_accounts",
        method="POST",
        data=account_payload,
        headers_extra={"Prefer": "return=representation"}
    )
    if status_a in [200, 201]:
        return 200, {
            "status": "created",
            "game": game,
            "username": username,
            "mojang_uuid": mojang_uuid
        }
    return status_a, {"error": f"Fehler beim Verknüpfen ({status_a}): {resp_a}"}

def handle_dns_sync(payload: dict) -> tuple[int, dict]:
    res = dns.sync_all_dns_from_godaddy()
    if "error" in res:
        return 500, res
    return 200, res

def handle_dns_records(payload: dict) -> tuple[int, dict]:
    status, resp = supabase.supabase_client_request("dim_dns_records?order=subdomain.asc", method="GET")
    if status == 200:
        return 200, {"records": json.loads(resp)}
    return status, {"error": f"Fehler beim Laden der DNS-Records: {resp}"}

def handle_whitelist_add(payload: dict) -> tuple[int, dict]:
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

    # Bestehenden Eintrag prüfen (Upsert/Rollen-Update)
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
            res_agent = agent.add_remote_whitelist(matched_vm["ip"], canonical_user, is_op=(target_role == "server-admin"))
            live_synced = res_agent.get("status") == "ok"
        except Exception as e:
            print(f"[WHITELIST SYNC ERROR] {e}")

    return 200, {
        "status": action_type,
        "username": canonical_user,
        "server": srv["display_name"],
        "role": target_role,
        "live_synced": live_synced
    }

def handle_whitelist_remove(payload: dict) -> tuple[int, dict]:
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
        "live_synced": live_synced
    }

def handle_whitelist_list(payload: dict) -> tuple[int, dict]:
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
        "entries": rows
    }

def handle_server_reload_files(payload: dict) -> tuple[int, dict]:
    game = str(payload.get("game", "minecraft")).strip().lower()
    raw_slug = resolve_server_slug(payload.get("server_name") or payload.get("server") or payload.get("name"), game=game)

    status_s, resp_s = supabase.supabase_client_request(
        f"dim_servers?game=eq.{game}&server_slug=eq.{raw_slug}&status=neq.deleted",
        method="GET"
    )
    if status_s != 200 or not json.loads(resp_s):
        return 404, {"error": f"Server '{raw_slug}' nicht in der Datenbank gefunden."}

    srv = json.loads(resp_s)[0]
    vm_full_name = srv.get("full_name")

    active_servers = hetzner.list_servers()
    matched_vm = next((s for s in active_servers if s.get("name") == vm_full_name), None)

    if not matched_vm or not matched_vm.get("ip"):
        return 400, {"error": f"Server '{raw_slug}' läuft aktuell nicht. Dateien werden beim nächsten Start automatisch frisch gezogen."}

    res_agent = agent.reload_remote_files(matched_vm["ip"])
    if res_agent.get("status") == "ok":
        return 200, {
            "message": f"Dateien auf `{srv['display_name']}` erfolgreich neu geladen & Dienste neu gestartet!",
            "details": res_agent
        }
    return 500, {"error": f"Reload fehlgeschlagen: {res_agent.get('error', res_agent.get('message'))}"}

def route_request(path: str, body: dict) -> tuple[int, dict]:
    raw_path = path or "/"
    action = body.get("action")

    if raw_path.endswith("/server/start") or raw_path.endswith("/start") or action == "start":
        return handle_start(body)
    if raw_path.endswith("/server/stop") or raw_path.endswith("/stop") or action == "stop":
        return handle_stop(body)
    if raw_path.endswith("/server/create") or action == "server_create":
        return handle_server_create(body)
    if raw_path.endswith("/server/delete") or action == "server_delete":
        return handle_server_delete(body)
    if raw_path.endswith("/servers") or action == "list":
        return handle_servers()

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

    if raw_path.endswith("/dns/sync") or action == "dns_sync":
        return handle_dns_sync(body)
    if raw_path.endswith("/dns/records") or action == "dns_records":
        return handle_dns_records(body)

    if raw_path.endswith("/whitelist/add") or action == "whitelist_add":
        return handle_whitelist_add(body)
    if raw_path.endswith("/whitelist/remove") or action == "whitelist_remove":
        return handle_whitelist_remove(body)
    if raw_path.endswith("/whitelist/list") or action == "whitelist_list":
        return handle_whitelist_list(body)
    if raw_path.endswith("/server/reload-files") or action == "server_reload_files":
        return handle_server_reload_files(body)

    return 404, {"error": f"Endpoint '{raw_path}' nicht gefunden"}