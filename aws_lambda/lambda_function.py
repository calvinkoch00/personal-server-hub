import json
from auth import is_authorized, verify_discord_signature
from config import parse_start_args
import hetzner
import agent_client
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
        if raw_path.endswith("/start") or action == "start":
            game_in = body.get("game", "minecraft")
            duration_in = body.get("duration")
            server_type = body.get("server_type", "cpx32")
            enable_logging = body.get("logging", False)

            input_str = f"{game_in} {duration_in}" if duration_in else game_in
            game, seconds, readable, parsed_log = parse_start_args(input_str)

            result = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                server_type=server_type,
                enable_logging=(enable_logging or parsed_log)
            )
            return json_response(200, {
                "message": "Server gestartet",
                "discord_summary": f"🎮 {result['game'].upper()} gestartet! IP: `{result['ip']}` ({result['lifetime_readable']})",
                "data": result
            })

        if raw_path.endswith("/servers") or action == "list":
            return json_response(200, {"data": hetzner.list_servers()})

        if raw_path.endswith("/stop") or action == "stop":
            servers = hetzner.list_servers()
            if not servers:
                return json_response(400, {"error": "Kein aktiver Server vorhanden"})

            server_id = body.get("server_id")
            target = next((s for s in servers if str(s["server_id"]) == str(server_id)), servers[0])

            # Graceful Stop Versuch auf der VM
            if target.get("ip"):
                try:
                    agent_client.stop_remote_server(target["ip"])
                except Exception:
                    pass

            # Hetzner API Delete aufrufen und Bestätigung abwarten
            delete_res = hetzner.delete_server(str(target["server_id"]))
            return json_response(200, {
                "message": f"Server {target['name']} gelöscht",
                "hetzner_action": delete_res.get("action")
            })

        if raw_path.endswith("/log") or action == "log":
            servers = hetzner.list_servers()
            if not servers:
                return json_response(400, {"error": "Kein aktiver Server gefunden"})
            res = agent_client.toggle_remote_logging(servers[0]["ip"])
            return json_response(200, res)

        return json_response(404, {"error": f"Endpoint '{raw_path}' nicht gefunden"})

    except Exception as e:
        return json_response(500, {"error": str(e)})