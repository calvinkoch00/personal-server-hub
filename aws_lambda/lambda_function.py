import json
from auth import is_authorized
import hetzner

def build_response(status_code: int, body: dict) -> dict:
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
    
    # 1. CORS Preflight für Browser
    http_method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
    if http_method == "OPTIONS":
        return build_response(200, {"message": "CORS OK"})

    # 2. Authentifizierung
    if not is_authorized(headers):
        return build_response(401, {"error": "Unauthorized: Ungültiger Auth-Token"})

    # 3. Path Routing
    raw_path = event.get("rawPath") or event.get("path") or "/"
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event.get("body"))
        except Exception:
            pass

    action = body.get("action")

    try:
        # Route 1: Server Starten (/start oder POST {"action": "start"})
        if raw_path.endswith("/start") or action == "start":
            server_type = body.get("server_type", "cpx32")
            result = hetzner.create_server(server_type=server_type)
            return build_response(200, {
                "message": "Server-Start initiiert",
                "discord_summary": f"🎮 Server gestartet! IP: `{result['ip']}` (Laufzeit: 20s)",
                "data": result
            })

        # Route 2: Server Status prüfen (/status oder POST {"action": "status"})
        elif raw_path.endswith("/status") or action == "status":
            server_id = body.get("server_id") or event.get("queryStringParameters", {}).get("server_id")
            if not server_id:
                return build_response(400, {"error": "server_id fehlt"})
            result = hetzner.get_server_status(server_id)
            return build_response(200, {"data": result})

        # Route 3: Server Manuell Löschen (/stop oder POST {"action": "stop"})
        elif raw_path.endswith("/stop") or action == "stop":
            server_id = body.get("server_id")
            if not server_id:
                return build_response(400, {"error": "server_id fehlt"})
            result = hetzner.delete_server(server_id)
            return build_response(200, {
                "message": "Server wird heruntergefahren",
                "discord_summary": "🛑 Server wurde gestoppt.",
                "data": result
            })

        else:
            return build_response(404, {"error": f"Endpoint '{raw_path}' nicht gefunden"})

    except Exception as e:
        return build_response(500, {"error": str(e)})