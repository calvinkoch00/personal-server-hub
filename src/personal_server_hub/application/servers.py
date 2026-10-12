import json
import re
from datetime import datetime, timezone

from personal_server_hub.services import agent, dns, hetzner, supabase


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
            enable_logging=log_mode,
        )
        return 200, {
            "message": "Server gestartet",
            "discord_summary": f"🎮 `{result['name']}` gestartet! IP: `{result['ip']}` | DNS: `{result.get('domain')}` ({result['lifetime_readable']})",
            "data": result,
            "log_mode": log_mode,
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
        for s in servers:
            if str(s.get("server_id")) == raw_identifier:
                target = s
                break

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

    subdomains_to_reset = set()
    srv_id = None

    status_srv, resp_srv = supabase.supabase_client_request(
        f"dim_servers?full_name=eq.{target['name']}&status=neq.deleted",
        method="GET",
    )
    db_servers = json.loads(resp_srv) if status_srv == 200 else []

    if not db_servers:
        slug_guess = target["name"].replace("server-minecraft-", "").replace("server-", "")
        status_srv, resp_srv = supabase.supabase_client_request(
            f"dim_servers?server_slug=eq.{slug_guess}&status=neq.deleted",
            method="GET",
        )
        db_servers = json.loads(resp_srv) if status_srv == 200 else []

    if db_servers:
        srv_row = db_servers[0]
        srv_id = srv_row.get("server_id")

        supabase.supabase_client_request(
            f"dim_servers?server_id=eq.{srv_id}",
            method="PATCH",
            data={"status": "offline"},
        )

        status_dns, resp_dns = supabase.supabase_client_request(
            f"dim_dns_records?server_id=eq.{srv_id}&select=subdomain",
            method="GET",
        )
        if status_dns == 200 and json.loads(resp_dns):
            for d in json.loads(resp_dns):
                if d.get("subdomain"):
                    subdomains_to_reset.add(d["subdomain"])

    if target_ip:
        live_matched = dns.find_subdomains_by_ip(target_ip)
        for sub in live_matched:
            subdomains_to_reset.add(sub)

    if target_ip and not subdomains_to_reset:
        status_ip_dns, resp_ip_dns = supabase.supabase_client_request(
            f"dim_dns_records?record_value=eq.{target_ip}&select=subdomain",
            method="GET",
        )
        if status_ip_dns == 200 and json.loads(resp_ip_dns):
            for d in json.loads(resp_ip_dns):
                if d.get("subdomain"):
                    subdomains_to_reset.add(d["subdomain"])

    if not subdomains_to_reset:
        server_row = db_servers[0] if db_servers else {}
        slug = server_row.get("server_slug", "")
        if slug:
            subdomains_to_reset.add(
                dns.fallback_server_subdomain(server_row.get("game", "minecraft"), slug)
            )

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
            "mode": "graceful",
        }
    else:
        delete_res = hetzner.delete_server(target_id)
        return 200, {
            "message": f"Server {target['name']} direkt via Hetzner-API gelöscht",
            "hetzner_action": delete_res.get("action"),
            "target": target,
            "mode": "direct",
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
    location = "nbg1"
    vol = hetzner.create_volume(name=volume_name, size_gb=20, location=location)
    volume_id = vol.get("id")
    if not volume_id:
        return 500, {"error": "Hetzner Volume konnte nicht angelegt werden"}

    server_entry = {
        "game": game,
        "server_slug": raw_slug,
        "display_name": f"{game}-{raw_slug}",
        "hetzner_volume_id": volume_id,
        "hetzner_server_type": server_type,
        "hetzner_location": location,
        "status": "offline",
        "created_by": caller_id,
    }
    status_sb, resp_sb = supabase.supabase_client_request("dim_servers", method="POST", data=server_entry)
    if status_sb not in [200, 201]:
        hetzner.delete_volume(volume_id)
        return status_sb, {"error": f"Fehler in dim_servers: {resp_sb}"}

    created_server = json.loads(resp_sb)[0]
    srv_id = created_server.get("server_id")

    creator_accounts_added = []
    if caller_id and srv_id:
        status_acc, resp_acc = supabase.supabase_client_request(
            f"dim_game_accounts?discord_user_id=eq.{caller_id}&game=eq.{game}&select=id,ingame_username",
            method="GET",
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
                        "role": "server-admin",
                    }
                    supabase.supabase_client_request("map_server_whitelist", method="POST", data=wl_payload)
                    creator_accounts_added.append(uname)

    sub_to_use = dns.environment_subdomain(
        custom_subdomain.strip().lower() if custom_subdomain else raw_slug
    )
    if srv_id and (custom_subdomain or raw_slug != f"{game}-default"):
        dns.update_godaddy_dns("0.0.0.0", subdomain=sub_to_use, server_id=srv_id)

    created_server["subdomain"] = sub_to_use
    created_server["server_slug"] = raw_slug
    created_server["auto_whitelisted"] = creator_accounts_added

    return 201, {
        "message": f"Server '{raw_slug}' erfolgreich erstellt",
        "server": created_server,
        "subdomain": sub_to_use,
        "server_slug": raw_slug,
        "mode": "direct",
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

    status_s, resp_s = supabase.supabase_client_request(f"dim_servers?game=eq.{game}&server_slug=eq.{raw_slug}&status=neq.deleted", method="GET")
    if status_s != 200 or not json.loads(resp_s):
        return 404, {"error": f"Server '{raw_slug}' nicht gefunden oder bereits gelöscht."}

    srv = json.loads(resp_s)[0]
    srv_id = srv["server_id"]

    hetzner.delete_volume(srv["hetzner_volume_id"])

    subdomains_to_delete = set()
    status_dns, resp_dns = supabase.supabase_client_request(f"dim_dns_records?server_id=eq.{srv_id}&select=subdomain", method="GET")
    if status_dns == 200:
        for d in json.loads(resp_dns):
            if d.get("subdomain"):
                subdomains_to_delete.add(dns.environment_subdomain(d["subdomain"]))

    subdomains_to_delete.add(dns.environment_subdomain(raw_slug))

    for sub in subdomains_to_delete:
        if sub and sub != "mc":
            dns.delete_godaddy_dns(sub)
            supabase.supabase_client_request(f"dim_dns_records?subdomain=eq.{sub}", method="DELETE")

    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.supabase_client_request(
        f"dim_servers?server_id=eq.{srv_id}",
        method="PATCH",
        data={"status": "deleted", "deleted_at": now_iso},
    )
    return 200, {"message": f"Server '{srv['display_name']}' und zugehörige DNS-Einträge gelöscht"}

