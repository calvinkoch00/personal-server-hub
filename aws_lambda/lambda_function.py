import json
import urllib.request
from auth import is_authorized, verify_discord_signature
from config import parse_start_args, DISCORD_APPLICATION_ID, DISCORD_BOT_TOKEN
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
    """Holt die aktuell registrierten Commands dynamisch von der Discord API ab."""
    if not DISCORD_APPLICATION_ID or not DISCORD_BOT_TOKEN:
        return "⚠️ Bot-Credentials nicht vollständig konfiguriert."

    url = f"https://discord.com/api/v10/applications/{DISCORD_APPLICATION_ID}/commands"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
        method="GET"
    )

    try:
        with urllib.request.urlopen(req) as resp:
            commands = json.loads(resp.read().decode("utf-8"))

        lines = ["📖 **Verfügbare Server-Befehle:**\n"]
        for cmd in sorted(commands, key=lambda x: x["name"]):
            name = cmd.get("name")
            desc = cmd.get("description", "")
            opts = cmd.get("options", [])

            opt_str = ""
            if opts:
                opt_names = [f"[{o['name']}]" if not o.get("required") else f"<{o['name']}>" for o in opts]
                opt_str = " " + " ".join(opt_names)

            lines.append(f"• `/{name}{opt_str}` — {desc}")

        lines.append("\n💡 *Beispiele für `/start`:*\n"
                     "• `/start` *(Minecraft, 5 Minuten)*\n"
                     "• `/start 2h` *(Minecraft, 2 Stunden)*\n"
                     "• `/start csgo 1d` *(CS:GO, 1 Tag, max. 7d)*")

        return "\n".join(lines)
    except Exception as e:
        return f"Fehler beim Abrufen der Befehle: {e}"

def handle_discord_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    # Discord PING Handshake (Typ 1)
    if interaction_type == 1:
        return build_response(200, {"type": 1})

    # Discord APPLICATION_COMMAND (Typ 2)
    if interaction_type == 2:
        data = body.get("data", {})
        command_name = data.get("name")

        if command_name == "help":
            msg = get_registered_discord_commands()

        elif command_name == "start":
            options = {opt["name"]: opt["value"] for opt in data.get("options", [])}
            raw_input = options.get("args", "")

            game, seconds, readable = parse_start_args(raw_input)

            res = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                server_type="cpx32"
            )

            msg = (
                f"🚀 **{res['game'].upper()}-Server wird gestartet!**\n"
                f"• IP: `{res.get('ip')}`\n"
                f"• Typ: `{res.get('server_type')}`\n"
                f"⏱️ **Laufzeit:** {res.get('lifetime_readable')} (danach Auto-Shutdown)"
            )

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

    # 1. Discord Webhooks (Ed25519-Signaturprüfung)
    if "x-signature-ed25519" in headers or "X-Signature-Ed25519" in headers:
        if not verify_discord_signature(headers, raw_body):
            return build_response(401, {"error": "Invalid Discord Signature"})
        try:
            discord_body = json.loads(raw_body)
            return handle_discord_interaction(discord_body)
        except Exception as e:
            return build_response(500, {"error": str(e)})

    # 2. REST API (Prüfung auf x-auth-token)
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
        # Help Endpunkt
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

        # Start Endpunkt
        if raw_path.endswith("/start") or action == "start":
            game = body.get("game", "minecraft")
            duration_input = body.get("duration")
            server_type = body.get("server_type", "cpx32")

            # Freitext parsen ("csgo 2h" oder separate Felder)
            parsed_game, seconds, readable = parse_start_args(f"{game} {duration_input}" if duration_input else game)

            result = hetzner.create_server(
                game=parsed_game,
                seconds=seconds,
                readable=readable,
                server_type=server_type
            )
            return build_response(200, {
                "message": "Server gestartet",
                "discord_summary": f"🎮 {result['game'].upper()} gestartet! IP: `{result['ip']}` ({result['lifetime_readable']})",
                "data": result
            })

        # Liste aller aktiven Server
        if raw_path.endswith("/servers") or action == "list":
            servers = hetzner.list_servers()
            return build_response(200, {"data": servers})

        # Status einer bestimmten Instanz
        if raw_path.endswith("/status") or action == "status":
            query_params = event.get("queryStringParameters") or {}
            server_id = body.get("server_id") or query_params.get("server_id")
            if not server_id:
                return build_response(400, {"error": "server_id fehlt"})
            return build_response(200, {"data": hetzner.get_server_status(str(server_id))})

        # Stop Endpunkt
        if raw_path.endswith("/stop") or action == "stop":
            server_id = body.get("server_id")
            if not server_id:
                # Fallback: wenn keine ID übergeben wird, stoppe den ersten aktiven Server
                active = hetzner.list_servers()
                if not active:
                    return build_response(400, {"error": "Kein aktiver Server gefunden"})
                server_id = str(active[0]["server_id"])

            return build_response(200, {"data": hetzner.delete_server(str(server_id))})

        return build_response(404, {"error": f"Endpoint '{raw_path}' nicht gefunden"})
    except Exception as e:
        return build_response(500, {"error": str(e)})