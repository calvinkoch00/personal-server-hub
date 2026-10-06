import os
import re
import json
import urllib.request
import urllib.error
import hetzner

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


def supabase_client_request(endpoint: str, method: str = "POST", data: dict = None, headers_extra: dict = None) -> tuple[int, str]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL oder SUPABASE_KEY in AWS Lambda nicht konfiguriert")

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{endpoint}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    if headers_extra:
        headers.update(headers_extra)

    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, content
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        return e.code, err_body


def get_help_message() -> str:
    cache_path = os.path.join(os.path.dirname(__file__), "commands_cache.txt")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    return (
        "📖 **Verfügbare Server-Befehle:**\n\n"
        "• `/start` — Startet den Server (Felder: `game`, `duration`, `log`)\n"
        "• `/status` — Zeigt alle aktiven Server samt IP an\n"
        "• `/log <mode>` — Schaltet Logs um (`all`, `game`, `off`)\n"
        "• `/stop` — Stoppt und löscht den laufenden Server\n"
        "• `/addgameaccount` — Verknüpft deinen Ingame-Namen mit Discord\n"
        "• `/help` — Zeigt diese Übersicht an"
    )


def handle_interaction(body: dict) -> dict:
    interaction_type = body.get("type")

    if interaction_type == 1:
        return {"statusCode": 200, "body": {"type": 1}}

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
                if hasattr(hetzner, "trigger_server_graceful_stop"):
                    hetzner.trigger_server_graceful_stop(target_ip, target_id)
                else:
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
                hetzner.delete_server(target_id)
                msg = f"🛑 **Server `{target['name']}` direkt via Hetzner-API gelöscht.**"

    elif command == "start":
        options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
        game = str(options.get("game", "minecraft")).strip().lower()
        duration_raw = str(options.get("duration", "5m")).strip().lower()
        
        # Log-Modus: none, game, all
        log_mode = str(options.get("log", "none")).strip().lower()
        if log_mode in ["true", "1"]:
            log_mode = "game"
        elif log_mode in ["false", "0"]:
            log_mode = "none"

        unit_map = {"m": 60, "h": 3600, "d": 86400}
        readable_map = {"m": "Minute(n)", "h": "Stunde(n)", "d": "Tag(e)"}

        match = re.match(r"^(\d+)([mhd])$", duration_raw)
        if match:
            val, unit = int(match.group(1)), match.group(2)
            seconds = val * unit_map[unit]
            readable = f"{val} {readable_map[unit]}"
        else:
            seconds = 300
            readable = "5 Minute(n)"

        try:
            res = hetzner.create_server(
                game=game,
                seconds=seconds,
                readable=readable,
                server_type="cpx32",
                enable_logging=log_mode
            )
            addr = f"`{res.get('domain')}` (IP: `{res.get('ip')}`)" if res.get("domain") else f"`{res.get('ip')}`"
            log_labels = {"none": "⚪ Aus", "game": "🎮 Nur Game", "all": "📡 Alles (Game + System)"}
            msg = (
                f"🟡 **Hardware wird hochgefahren!**\n"
                f"🎮 **Spiel:** {res.get('game', '').upper()}\n"
                f"🌐 **Adresse:** {addr}\n"
                f"⏳ **Laufzeit:** {readable}\n"
                f"📋 **Live-Logs:** {log_labels.get(log_mode, log_mode)}\n\n"
                f"*(Bereitschaftsmeldung folgt automatisch, sobald der Server beitretbar ist!)*"
            )
        except Exception as e:
            msg = f"❌ Fehler beim Starten des Servers: {e}"

    elif command == "log":
        servers = hetzner.list_servers()
        if not servers:
            msg = "⚪ Kein aktiver Server online."
        else:
            options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
            mode = str(options.get("mode", "game")).strip().lower()
            target_ip = servers[0].get("ip")
            try:
                auth_secret = os.environ.get("AUTH_SECRET", "")
                payload = json.dumps({"mode": mode}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://{target_ip}:8080/toggle-log",
                    data=payload,
                    headers={"Content-Type": "application/json", "x-auth-token": auth_secret},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res_data = json.loads(resp.read().decode())
                    cur_mode = res_data.get("mode", mode)
                    msg = f"📡 **Live-Logs wurden umgestellt auf: `{cur_mode.upper()}`**"
            except Exception as e:
                msg = f"⚠ Agent auf VM nicht erreichbar: {e}"

    elif command == "addgameaccount":
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
                supabase_client_request(
                    "dim_users",
                    method="POST",
                    data={"discord_user_id": discord_user_id, "discord_username": discord_username},
                    headers_extra={"Prefer": "resolution=merge-duplicates"}
                )
                status_a, resp_a = supabase_client_request(
                    "dim_game_accounts",
                    method="POST",
                    data={
                        "discord_user_id": discord_user_id,
                        "game": game,
                        "ingame_username": username
                    },
                    headers_extra={"Prefer": "resolution=merge-duplicates,return=representation"}
                )
                if status_a in [200, 201]:
                    msg = f"✅ Ingame-Account `{username}` ({game.upper()}) wurde erfolgreich mit deinem Discord-Profil verknüpft!"
                else:
                    msg = f"⚠ Fehler beim Verknüpfen ({status_a}): {resp_a}"
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