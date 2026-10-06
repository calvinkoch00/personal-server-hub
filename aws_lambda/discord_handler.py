import os
import json
import urllib.request
from config import parse_start_args
import hetzner


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
            lines = [
                f"• `{s['name']}` (ID: {s['server_id']}) — `{s.get('status', 'unknown')}` — IP: `{s['ip']}`"
                for s in servers
            ]
            msg = "🟢 **Aktive Server:**\n" + "\n".join(lines)

    elif command == "stop":
        servers = hetzner.list_servers()
        if not servers:
            msg = "⚪ Kein laufender Server zum Stoppen vorhanden."
        else:
            target = servers[0]
            target_ip = target.get("ip")
            target_id = str(target.get("server_id"))

            try:
                # Versuche den Graceful-Stop über den Port 8080 Agenten auf der VM
                if hasattr(hetzner, "trigger_server_graceful_stop"):
                    hetzner.trigger_server_graceful_stop(target_ip, target_id)
                else:
                    # Direkter HTTP-Call an den Agenten falls kein Wrapper vorhanden
                    auth_secret = os.environ.get("AUTH_SECRET", "")
                    req = urllib.request.Request(
                        f"http://{target_ip}:8080/stop",
                        data=b"{}",
                        headers={"Content-Type": "application/json", "x-auth-token": auth_secret},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=3):
                        pass
                msg = f"🛑 **Shutdown für `{target['name']}` eingeleitet.** (Container sichern & VM löschen)"
            except Exception:
                # Fallback: Direktes Löschen über die Hetzner Cloud API
                hetzner.delete_server(target_id)
                msg = f"🛑 **Server `{target['name']}` direkt via Hetzner-API gelöscht.**"

    elif command == "start":
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
            addr = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get("domain") else f"`{res.get('ip')}`"
            msg = (
                f"🟡 **Hardware wird hochgefahren!**\n"
                f"🎮 **Spiel:** {res.get('game', '').upper()}\n"
                f"🌐 **Adresse:** {addr}\n"
                f"⏳ **Laufzeit:** {res.get('lifetime_readable', readable)}\n\n"
                f"*(Bereitschaftsmeldung folgt automatisch, sobald der Server beitretbar ist!)*"
            )
        except Exception as e:
            msg = f"❌ Fehler beim Starten des Servers: {e}"

    elif command == "log":
        servers = hetzner.list_servers()
        if not servers:
            msg = "⚪ Kein aktiver Server online."
        else:
            target_ip = servers[0].get("ip")
            try:
                auth_secret = os.environ.get("AUTH_SECRET", "")
                req = urllib.request.Request(
                    f"http://{target_ip}:8080/toggle-log",
                    data=b"",
                    headers={"x-auth-token": auth_secret},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res_data = json.loads(resp.read().decode())
                    state = "aktiviert" if res_data.get("logging") else "deaktiviert"
                    msg = f"📡 **Live-Logs wurden {state}.**"
            except Exception as e:
                msg = f"⚠ Agent auf VM nicht erreichbar: {e}"
    elif command == "addgameaccount":
        # Discord User ermitteln
        user_data = body.get("member", {}).get("user") or body.get("user", {})
        discord_user_id = str(user_data.get("id"))
        discord_username = str(user_data.get("username", "Unknown"))

        options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
        game = str(options.get("game", "")).strip().lower()
        username = str(options.get("username", "")).strip()

        if not game or not username:
            msg = "❌ Bitte gib Spiel und Ingame-Namen an: `/addgameaccount <game> <username>`"
        else:
            try:
                # 1. User in dim_users upserten
                supabase_client_request(
                    "dim_users",
                    method="POST",
                    data={"discord_user_id": discord_user_id, "discord_username": discord_username},
                    headers_extra={"Prefer": "resolution=merge-duplicates"}
                )

                # 2. Game-Account in dim_game_accounts verknüpfen
                res = supabase_client_request(
                    "dim_game_accounts",
                    method="POST",
                    data={
                        "discord_user_id": discord_user_id,
                        "game": game,
                        "ingame_username": username
                    },
                    headers_extra={"Prefer": "resolution=merge-duplicates,return=representation"}
                )

                if res.status_code in [200, 201]:
                    msg = f"✅ Ingame-Account `{username}` ({game.upper()}) wurde erfolgreich mit deinem Discord-Profil verknüpft!"
                else:
                    msg = f"⚠ Fehler beim Verknüpfen ({res.status_code}): {res.text}"
            except Exception as e:
                msg = f"❌ Datenbankfehler: {e}"

    else:
        msg = f"Unbekannter Befehl: `/{command}`"

    return {
        "statusCode": 200,
        "body": {
            "type": 4,
            "data": {"content": msg}
        }
    }