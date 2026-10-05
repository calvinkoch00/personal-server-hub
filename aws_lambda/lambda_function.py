import os
import json
from auth import is_authorized, verify_discord_signature
from config import parse_start_args
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

def get_registered_discord_commands() -> str:
    cache_path = os.path.join(os.path.dirname(__file__), "commands_cache.txt")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass

    return (
        "📖 **Verfügbare Server-Befehle:**\n\n"
        "• `/start [args]` — Startet den Server (Standard: Minecraft, 5m)\n"
        "• `/status` — Zeigt alle aktiven Server samt IP an\n"
        "• `/stop` — Stoppt und löscht den laufenden Server\n"
        "• `/help` — Zeigt diese Übersicht an"
    )

def handle_discord_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    # Type 1: Discord PING -> PONG
    if interaction_type == 1:
        return build_response(200, {"type": 1})

    # Type 2: Slash Command
    if interaction_type == 2:
        data = body.get("data", {})
        command_name = data.get("name")

        if command_name == "help":
            msg = get_registered_discord_commands()

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
                hetzner.graceful_stop_and_delete(str(target["server_id"]))
                msg = (
                    f"🛑 Server `{target['name']}` (ID: {target['server_id']}) wurde sauber beendet!\n"
                    f"💾 *Minecraft gespeichert, Volume unmounted und Instanz gelöscht.*"
                )

        elif command_name == "start":
            options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
            raw_input = options.get("args")
            game, seconds, readable = parse_start_args(raw_input)

            try:
                res = hetzner.create_server(
                    game=game,
                    seconds=seconds,
                    readable=readable,
                    server_type="cpx32"
                )
                domain_info = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get('domain') else f"`{res.get('ip')}`"
                msg = (
                    f"🎮 **{res.get('game', '').upper()}-Server wird gestartet!**\n"
                    f"🌐 **Adresse:** {domain_info}\n"
                    f"⚡ **Typ:** `{res.get('server_type')}`\n"
                    f"⏳ **Laufzeit:** {res.get('lifetime_readable')} *(danach Auto-Shutdown)*"
                )
            except Exception as e:
                msg = f"❌ Fehler beim Starten des Servers: {e}"

        else:
            msg = f"Unbekannter Befehl: `/{command_name}`"

        # Direkte Antwort mit Type 4 (in einem einzigen HTTP-Turn)
        return build_response(200, {
            "type": 4,
            "data": {"content": msg}
        })

    return build_response(400, {"error": "Unbekannter Interaktions-Typ"})

def lambda_handler(event, context):
    headers = event.get("headers", {}) or {}
    raw_body = event.get("body", "") or ""

    http_method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
    if http_method == "OPTIONS":
        return build_response(200, {"message": "CORS OK"})

    # Discord Webhook Signature
    if "x-signature-ed25519" in headers or "X-Signature-Ed25519" in headers:
        if not verify_discord_signature(headers, raw_body):
            return build_response(401, {"error": "Invalid Discord Signature"})
        try:
            discord_body = json.loads(raw_body)
            return handle_discord_interaction(discord_body)
        except Exception as e:
            return build_response(500, {"error": str(e)})

    # REST API Auth
    if not is_authorized(headers):
        return build_response(401, {"error": "Unauthorized"})

    raw_path = event.get("rawPath") or event.get("path") or "/"
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body)
        except Exception:
            pass

    action = body.get("action")

    try:
        if raw_path.endswith("/help") or action == "help":
            help_text = get_registered_discord_commands()
            return build_response(200, {
                "message": "Befehlsübersicht",
                "help": help_text,
                "endpoints": [
                    {"path": "POST /start", "description": "Startet Server (Body: game, duration, server_type)"},
                    {"path": "GET /status?server_id=<id>", "description": "Status einer spezifischen Instanz"},
                    {"path": "GET /servers", "description": "Liste aller aktiven Instanzen"},
                    {"path": "POST /stop", "description": "Löscht Server (Body: server_id)"},
                    {"path": "GET /help", "description": "Zeigt diese Hilfeübersicht"}
                ]
            })

        if raw_path.endswith("/start") or action == "start":
            game_input = body.get("game", "minecraft")
            duration_input = body.get("duration")
            server_type = body.get("server_type", "cpx32")

            input_str = f"{game_input} {duration_input}" if duration_input else game_input
            game, seconds, readable = parse_start_args(input_str)

            result = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                server_type=server_type
            )
            return build_response(200, {
                "message": "Server gestartet",
                "discord_summary": f"🎮 {result['game'].upper()} gestartet! IP: `{result['ip']}` ({result['lifetime_readable']})",
                "data": result
            })

        if raw_path.endswith("/servers") or action == "list":
            servers = hetzner.list_servers()
            return build_response(200, {"data": servers})

        if raw_path.endswith("/status") or action == "status":
            query_params = event.get("queryStringParameters") or {}
            server_id = body.get("server_id") or query_params.get("server_id")
            if not server_id:
                return build_response(400, {"error": "server_id fehlt"})
            return build_response(200, {"data": hetzner.get_server_status(str(server_id))})

        if raw_path.endswith("/stop") or action == "stop":
            server_id = body.get("server_id")
            if not server_id:
                active = hetzner.list_servers()
                if not active:
                    return build_response(400, {"error": "Kein aktiver Server gefunden"})
                server_id = str(active[0]["server_id"])

            return build_response(200, {"data": hetzner.delete_server(str(server_id))})

        return build_response(404, {"error": f"Endpoint '{raw_path}' nicht gefunden"})
    except Exception as e:
        return build_response(500, {"error": str(e)})