import os
import json
import urllib.request
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
    return (
        "📖 **Verfügbare Server-Befehle:**\n\n"
        "• `/start [args]` — Startet den Server (z. B. `2h log=true`)\n"
        "• `/status` — Zeigt alle aktiven Server samt IP an\n"
        "• `/log` — Schaltet Live-Logs im Discord-Kanal ein/aus\n"
        "• `/stop` — Stoppt und löscht den laufenden Server\n"
        "• `/help` — Zeigt diese Übersicht an"
    )

def handle_discord_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    if interaction_type == 1:
        return build_response(200, {"type": 1})

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
                hetzner.delete_server(str(target["server_id"]))
                msg = f"🛑 **Server `{target['name']}` wird heruntergefahren und gelöscht.**"

        elif command_name == "start":
            options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
            raw_input = options.get("args")
            game, seconds, readable, enable_logging = parse_start_args(raw_input)

            try:
                res = hetzner.create_server(
                    game=game,
                    seconds=seconds,
                    readable=readable,
                    server_type="cpx32",
                    enable_logging=enable_logging
                )
                domain_info = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get('domain') else f"`{res.get('ip')}`"
                msg = (
                    f"🟡 **Hardware wird hochgefahren!**\n"
                    f"🎮 **Spiel:** {res.get('game', '').upper()}\n"
                    f"🌐 **Adresse:** {domain_info}\n"
                    f"⏳ **Laufzeit:** {res.get('lifetime_readable')}\n\n"
                    f"*(Eine Benachrichtigung folgt, sobald der Server beitretbar ist!)*"
                )
            except Exception as e:
                msg = f"❌ Fehler beim Starten des Servers: {e}"

        elif command_name == "log":
            servers = hetzner.list_servers()
            if not servers:
                msg = "⚪ Kein aktiver Server online."
            else:
                target_ip = servers[0]["ip"]
                try:
                    req = urllib.request.Request(
                        f"http://{target_ip}:8080/toggle-log",
                        data=b"",
                        headers={"x-auth-token": os.environ.get("AUTH_SECRET", "")},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=5) as response:
                        res_data = json.loads(response.read().decode())
                        state = "aktiviert" if res_data.get("logging") else "deaktiviert"
                        msg = f"📡 **Live-Logs wurden {state}.**"
                except Exception as e:
                    msg = f"⚠️ Konnte Agenten nicht erreichen: {e}"

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

    if "x-signature-ed25519" in headers or "X-Signature-Ed25519" in headers:
        if not verify_discord_signature(headers, raw_body):
            return build_response(401, {"error": "Invalid Discord Signature"})
        try:
            return handle_discord_interaction(json.loads(raw_body))
        except Exception as e:
            return build_response(500, {"error": str(e)})

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
        if raw_path.endswith("/start") or action == "start":
            game_input = body.get("game", "minecraft")
            duration_input = body.get("duration")
            server_type = body.get("server_type", "cpx32")
            enable_logging = body.get("logging", False)

            input_str = f"{game_input} {duration_input}" if duration_input else game_input
            game, seconds, readable, parsed_log = parse_start_args(input_str)
            final_logging = enable_logging or parsed_log

            result = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                server_type=server_type,
                enable_logging=final_logging
            )
            return build_response(200, {
                "message": "Server gestartet",
                "discord_summary": f"🎮 {result['game'].upper()} gestartet! IP: `{result['ip']}` ({result['lifetime_readable']})",
                "data": result
            })

        if raw_path.endswith("/servers") or action == "list":
            return build_response(200, {"data": hetzner.list_servers()})

        if raw_path.endswith("/stop") or action == "stop":
            server_id = body.get("server_id")
            if not server_id:
                active = hetzner.list_servers()
                if not active:
                    return build_response(400, {"error": "Kein aktiver Server gefunden"})
                server_id = str(active[0]["server_id"])
            return build_response(200, {"data": hetzner.delete_server(str(server_id))})

        if raw_path.endswith("/log") or action == "log":
            servers = hetzner.list_servers()
            if not servers:
                return build_response(400, {"error": "Kein aktiver Server gefunden"})
            target_ip = servers[0]["ip"]
            req = urllib.request.Request(
                f"http://{target_ip}:8080/toggle-log",
                data=b"",
                headers={"x-auth-token": os.environ.get("AUTH_SECRET", "")},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode())
                return build_response(200, res_data)

        return build_response(404, {"error": f"Endpoint '{raw_path}' nicht gefunden"})
    except Exception as e:
        return build_response(500, {"error": str(e)})