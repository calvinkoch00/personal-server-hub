from config import parse_start_args
import hetzner
import agent_client


def get_help_message() -> str:
    return (
        "📖 **Verfügbare Server-Befehle:**\n\n"
        "• `/start [args]` — Startet den Server (z. B. `2h log=true`)\n"
        "• `/status` — Zeigt alle aktiven Server samt IP an\n"
        "• `/log` — Schaltet Live-Logs im Discord-Kanal ein/aus\n"
        "• `/stop` — Stoppt und löscht den laufenden Server\n"
        "• `/help` — Zeigt diese Übersicht an"
    )


def handle_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    # Type 1: Discord PING Check (Ack)
    if interaction_type == 1:
        return {"statusCode": 200, "body": {"type": 1}}

    # Type 2: Application Command (Slash Commands)
    if interaction_type != 2:
        return {"statusCode": 400, "body": {"error": "Unsupported interaction type"}}

    data = body.get("data", {})
    command = data.get("name")

    if command == "help":
        msg = get_help_message()

    elif command == "status":
        servers = hetzner.list_servers()
        if not servers:
            msg = "⚪ Es läuft aktuell kein Server."
        else:
            lines = [f"• `{s['name']}` (ID: {s['server_id']}) — `{s['status']}` — IP: `{s['ip']}`" for s in servers]
            msg = "🟢 **Aktive Server:**\n" + "\n".join(lines)

    elif command == "stop":
        servers = hetzner.list_servers()
        if not servers:
            msg = "⚪ Kein laufender Server zum Stoppen vorhanden."
        else:
            target = servers[0]
            try:
                agent_client.stop_remote_server(target["ip"])
                msg = f"🛑 **Shutdown für `{target['name']}` eingeleitet.** (Container sichern & VM löschen)"
            except Exception:
                hetzner.delete_server(str(target["server_id"]))
                msg = f"🛑 **Server `{target['name']}` direkt via API gelöscht.**"

    elif command == "start":
        options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
        raw_input = options.get("args")
        game, seconds, readable, enable_logging = parse_start_args(raw_input)

        try:
            res = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                enable_logging=enable_logging
            )
            addr = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get("domain") else f"`{res.get('ip')}`"
            msg = (
                f"🟡 **Hardware wird hochgefahren!**\n"
                f"🎮 **Spiel:** {res.get('game', '').upper()}\n"
                f"🌐 **Adresse:** {addr}\n"
                f"⏳ **Laufzeit:** {res.get('lifetime_readable')}\n\n"
                f"*(Bereitschaftsmeldung folgt automatisch, sobald der Server beitretbar ist!)*"
            )
        except Exception as e:
            msg = f"❌ Fehler beim Starten des Servers: {e}"

    elif command == "log":
        servers = hetzner.list_servers()
        if not servers:
            msg = "⚪ Kein aktiver Server online."
        else:
            target_ip = servers[0]["ip"]
            try:
                res = agent_client.toggle_remote_logging(target_ip)
                state = "aktiviert" if res.get("logging") else "deaktiviert"
                msg = f"📡 **Live-Logs wurden {state}.**"
            except Exception as e:
                msg = f"⚠️️ Agent auf VM nicht erreichbar: {e}"
    else:
        msg = f"Unbekannter Befehl: `/{command}`"

    return {
        "statusCode": 200,
        "body": {
            "type": 4,
            "data": {"content": msg}
        }
    }