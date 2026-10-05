import json
from auth import is_authorized, verify_discord_signature
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

def handle_discord_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    # Discord PING Handshake (Typ 1)
    if interaction_type == 1:
        return build_response(200, {"type": 1})

    # Discord APPLICATION_COMMAND (Typ 2 = Slash Command)
    if interaction_type == 2:
        data = body.get("data", {})
        command_name = data.get("name")

        if command_name == "start":
            res = hetzner.create_server(server_type="cpx32")
            msg = f"🚀 **Server gestartet!**\nIP: `{res.get('ip')}`\nTyp: `{res.get('server_type')}`\n⏱️ Auto-Shutdown nach {res.get('auto_kill_after_seconds')}s aktiv."
        elif command_name == "status":
            servers = hetzner.list_servers()
            if not servers:
                msg = "⚪ Es läuft aktuell kein Server."
            else:
                lines = [f"• `{s['name']}` (ID: {s['server_id']}) - Status: `{s['status']}` - IP: `{s['ip']}`" for s in servers]
                msg = "🟢 **Aktive Server:**\n" + "\n".join(lines)
        elif command_name == "stop":
            servers = hetzner.list_servers()
            if not servers:
                msg = "⚪ Kein laufender Server zum Stoppen vorhanden."
            else:
                target = servers[0]
                hetzner.delete_server(str(target["server_id"]))
                msg = f"🛑 Server `{target['name']}` (ID: {target['server_id']}) wird heruntergefahren."
        else:
            msg = f"Unbekannter Befehl: `/{command_name}`"

        # Typ 4 = Sofortige Kanalantwort
        return build_response(200, {
            "type": 4,
            "data": {"content": msg}
        })

    return build_response(400, {"error": "Unbekannter Interaktions-Typ"})

def lambda_handler(event, context):
    headers = event.get("headers", {}) or {}
    raw_body = event.get("body", "") or ""

    # 1. CORS Preflight
    http_method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
    if http_method == "OPTIONS":
        return build_response(200, {"message": "CORS OK"})

    # 2. Discord Handshake & Befehle
    if "x-signature-ed25519" in headers or "X-Signature-Ed25519" in headers:
        if not verify_discord_signature(headers, raw_body):
            return build_response(401, {"error": "Invalid Discord Signature"})
        try:
            discord_body = json.loads(raw_body)
            return handle_discord_interaction(discord_body)
        except Exception as e:
            return build_response(500, {"error": str(e)})

    # 3. Standard-Token-Prüfung für Website / curl
    if not is_authorized(headers):
        return build_response(401, {"error": "Unauthorized: Ungültiger Auth-Token"})

    # 4. REST Endpoints
    raw_path = event.get("rawPath") or event.get("path") or "/"
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body)
        except Exception:
            pass

    action = body.get("action")

    try:
        # POST /start
        if raw_path.endswith("/start") or action == "start":
            server_type = body.get("server_type", "cpx32")
            result = hetzner.create_server(server_type=server_type)
            return build_response(200, {
                "message": "Server-Start initiiert",
                "discord_summary": f"🎮 Server gestartet! IP: `{result['ip']}` (Laufzeit: 20s)",
                "data": result
            })

        # GET /servers
        elif raw_path.endswith("/servers") or action == "list":
            servers = hetzner.list_servers()
            count = len(servers)
            summary = f"🟢 Aktuell laufen {count} Server." if count > 0 else "⚪ Aktuell laufen keine Server."
            return build_response(200, {
                "message": f"{count} Server gefunden",
                "discord_summary": summary,
                "data": servers
            })

        # GET/POST /status
        elif raw_path.endswith("/status") or action == "status":
            server_id = body.get("server_id") or event.get("queryStringParameters", {}).get("server_id")
            if not server_id:
                return build_response(400, {"error": "server_id fehlt"})
            result = hetzner.get_server_status(str(server_id))
            return build_response(200, {"data": result})

        # POST /stop
        elif raw_path.endswith("/stop") or action == "stop":
            server_id = body.get("server_id")
            if not server_id:
                return build_response(400, {"error": "server_id fehlt"})
            result = hetzner.delete_server(str(server_id))
            return build_response(200, {
                "message": "Server wird heruntergefahren",
                "discord_summary": "🛑 Server wurde gestoppt.",
                "data": result
            })

        return build_response(404, {"error": f"Endpoint '{raw_path}' nicht gefunden"})

    except Exception as e:
        return build_response(500, {"error": str(e)})