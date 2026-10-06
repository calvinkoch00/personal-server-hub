import os
import re
import json
import urllib.request
import urllib.error
from auth import is_authorized, verify_discord_signature
import hetzner
import discord_handler


def json_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*"
        },
        "body": json.dumps(body)
    }


def call_agent_remote(target_ip: str, endpoint: str, data: dict = None) -> dict:
    """Sendet einen HTTP-Request an die Control-API des Agenten auf Port 8080."""
    auth_secret = os.environ.get("AUTH_SECRET", "")
    url = f"http://{target_ip}:8080/{endpoint.lstrip('/')}"
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-auth-token": auth_secret
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        content = resp.read().decode("utf-8")
        return json.loads(content) if content else {}


def upsert_game_account(discord_user_id: str, discord_username: str, game: str, ingame_username: str) -> dict:
    """Schreibt Benutzer und Ingame-Account in das Supabase Star-Schema."""
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")

    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL oder SUPABASE_KEY in AWS Lambda nicht konfiguriert")

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    # 1. User in dim_users anlegen/aktualisieren
    user_url = f"{supabase_url.rstrip('/')}/rest/v1/dim_users"
    user_payload = {
        "discord_user_id": str(discord_user_id),
        "discord_username": str(discord_username)
    }
    req_user = urllib.request.Request(
        user_url,
        data=json.dumps(user_payload).encode("utf-8"),
        headers={**headers, "Prefer": "resolution=merge-duplicates"},
        method="POST"
    )
    with urllib.request.urlopen(req_user, timeout=5):
        pass

    # 2. Account in dim_game_accounts verknüpfen
    acc_url = f"{supabase_url.rstrip('/')}/rest/v1/dim_game_accounts"
    acc_payload = {
        "discord_user_id": str(discord_user_id),
        "game": game.strip().lower(),
        "ingame_username": ingame_username.strip()
    }
    req_acc = urllib.request.Request(
        acc_url,
        data=json.dumps(acc_payload).encode("utf-8"),
        headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
        method="POST"
    )
    with urllib.request.urlopen(req_acc, timeout=5) as resp:
        content = resp.read().decode("utf-8")
        return json.loads(content) if content else {}


def lambda_handler(event, context):
    headers = event.get("headers", {}) or {}
    raw_body = event.get("body", "") or ""

    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod", "GET")
    )
    if http_method == "OPTIONS":
        return json_response(200, {"message": "CORS OK"})

    # 1. Discord Webhook Entrypoint (Signaturprüfung & Routing)
    if "x-signature-ed25519" in headers or "X-Signature-Ed25519" in headers:
        if not verify_discord_signature(headers, raw_body):
            return json_response(401, {"error": "Invalid Discord Signature"})
        try:
            interaction_res = discord_handler.handle_interaction(json.loads(raw_body))
            return json_response(interaction_res["statusCode"], interaction_res["body"])
        except Exception as e:
            return json_response(500, {"error": str(e)})

    # 2. REST API Entrypoint (Token Auth erforderlich)
    if not is_authorized(headers):
        return json_response(401, {"error": "Unauthorized"})

    raw_path = event.get("rawPath") or event.get("path") or "/"
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body)
        except Exception:
            pass

    action = body.get("action")

    try:
        # Start-Endpunkt (Direkter REST-Aufruf)
        if raw_path.endswith("/start") or action == "start":
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

            result = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                server_type=server_type,
                enable_logging=log_mode
            )
            return json_response(200, {
                "message": "Server gestartet",
                "discord_summary": f"🎮 {result['game'].upper()} gestartet! IP: `{result['ip']}` ({result['lifetime_readable']})",
                "data": result
            })

        # Server-Übersicht
        if raw_path.endswith("/servers") or action == "list":
            return json_response(200, {"data": hetzner.list_servers()})

        # Stop-Endpunkt
        if raw_path.endswith("/stop") or action == "stop":
            servers = hetzner.list_servers()
            if not servers:
                return json_response(400, {"error": "Kein aktiver Server vorhanden"})

            server_id = body.get("server_id")
            target = next((s for s in servers if str(s["server_id"]) == str(server_id)), servers[0])

            # Graceful Stop Versuch auf der VM
            if target.get("ip"):
                try:
                    if hasattr(hetzner, "trigger_server_graceful_stop"):
                        hetzner.trigger_server_graceful_stop(target["ip"], str(target["server_id"]))
                    else:
                        call_agent_remote(target["ip"], "stop")
                except Exception:
                    pass

            # Hetzner API Delete aufrufen
            delete_res = hetzner.delete_server(str(target["server_id"]))
            return json_response(200, {
                "message": f"Server {target['name']} gelöscht",
                "hetzner_action": delete_res.get("action")
            })

        # Log Toggle-Endpunkt
        if raw_path.endswith("/log") or action == "log":
            servers = hetzner.list_servers()
            if not servers:
                return json_response(400, {"error": "Kein aktiver Server gefunden"})
            mode = body.get("mode", "game")
            res = call_agent_remote(servers[0]["ip"], "toggle-log", data={"mode": mode})
            return json_response(200, res)

        # Game-Account Whitelist / Linking Endpunkt (REST)
        if raw_path.endswith("/addgameaccount") or action == "addgameaccount":
            discord_user_id = body.get("discord_user_id")
            discord_username = body.get("discord_username", "Unknown")
            game = body.get("game")
            username = body.get("username")

            if not discord_user_id or not game or not username:
                return json_response(400, {
                    "error": "Felder 'discord_user_id', 'game' und 'username' sind erforderlich"
                })

            res = upsert_game_account(
                discord_user_id=str(discord_user_id),
                discord_username=str(discord_username),
                game=game,
                ingame_username=username
            )
            return json_response(200, {
                "message": f"Account '{username}' für '{game}' erfolgreich mit Discord-User '{discord_user_id}' verknüpft",
                "data": res
            })

        return json_response(404, {"error": f"Endpoint '{raw_path}' nicht gefunden"})

    except Exception as e:
        return json_response(500, {"error": str(e)})