import os
import re
import json
import datetime
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


def parse_timeframe(tf_str: str) -> tuple[datetime.datetime | None, datetime.datetime | None, str]:
    now = datetime.datetime.now(datetime.timezone.utc)
    tf = (tf_str or "this month").strip().lower()

    if tf == "this month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, None, "Diesen Monat"
    elif tf == "last month":
        first_of_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day_prev = first_of_this - datetime.timedelta(days=1)
        start_last = last_day_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start_last, first_of_this, "Letzten Monat"
    elif tf == "this year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, None, "Dieses Jahr"
    elif tf == "all":
        return None, None, "Gesamte Laufzeit"
    else:
        parts = tf.split()
        try:
            start = datetime.datetime.fromisoformat(parts[0]).replace(tzinfo=datetime.timezone.utc)
            end = datetime.datetime.fromisoformat(parts[1]).replace(tzinfo=datetime.timezone.utc) if len(parts) > 1 else None
            return start, end, f"{parts[0]} bis {parts[1] if len(parts) > 1 else 'jetzt'}"
        except Exception:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, None, "Diesen Monat"


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
        "• `/costs` — Zeigt Serverkosten und Spielzeiten an (`timeframe`, `user`)\n"
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

        match = re.match(r"^(\d+)\s*([mhd])$", duration_raw)
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

    elif command == "costs":
        options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
        user_param = str(options.get("user", "all")).strip()
        timeframe_param = str(options.get("timeframe", "this month")).strip()

        caller_user_id = str((body.get("member", {}).get("user") or body.get("user", {})).get("id"))
        if user_param.lower() == "me":
            filter_user = caller_user_id
        else:
            filter_user = user_param.lstrip("@")

        start_dt, end_dt, label_tf = parse_timeframe(timeframe_param)

        payload = {
            "filter_user": filter_user,
            "from_date": start_dt.isoformat() if start_dt else None,
            "to_date": end_dt.isoformat() if end_dt else None
        }

        status, resp_text = supabase_client_request("rpc/get_costs_summary", method="POST", data=payload)
        if status not in [200, 201]:
            msg = f"⚠️ Fehler beim Abrufen der Abrechnung ({status}): {resp_text}"
        else:
            try:
                rows = json.loads(resp_text)
                if not rows:
                    msg = f"ℹ️ Keine Kosten oder Spielzeiten für **{label_tf}** gefunden."
                else:
                    total_server = rows[0].get("total_server_costs", 0.0)
                    header = f"📊 **Kostenaufstellung ({label_tf})**\n*Server-Gesamtkosten: {float(total_server):.2f} €*\n"
                    table = "```asciidoc\n"
                    table += f"{'Spieler':<16} | {'Zeit':<7} | {'Anteil':<8} | {'Betrag'}\n"
                    table += "-" * 42 + "\n"
                    for r in rows:
                        name = str(r.get("discord_username") or "Unknown")[:15]
                        hours = f"{float(r.get('hours_played', 0)):.1f}h"
                        share = f"{float(r.get('share_percent', 0)):.1f}%"
                        cost = f"{float(r.get('amount_due_euro', 0)):.2f} €"
                        table += f"{name:<16} | {hours:<7} | {share:<8} | {cost}\n"
                    table += "```"
                    msg = header + table
            except Exception as e:
                msg = f"❌ Fehler beim Formatieren der Abrechnung: {e}"

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
                # 1. Sicherstellen, dass User in dim_users existiert
                supabase_client_request(
                    "dim_users",
                    method="POST",
                    data={"discord_user_id": discord_user_id, "discord_username": discord_username},
                    headers_extra={"Prefer": "resolution=merge-duplicates"}
                )

                # 2. Prüfen, ob der Ingame-Account bereits registriert ist
                endpoint_check = f"dim_game_accounts?game=eq.{game}&ingame_username=ilike.{username}&select=discord_user_id"
                status_check, resp_check = supabase_client_request(endpoint_check, method="GET")
                existing_accounts = json.loads(resp_check) if status_check == 200 else []

                if existing_accounts:
                    owner_id = str(existing_accounts[0].get("discord_user_id"))
                    if owner_id == discord_user_id:
                        msg = f"ℹ️ Der Ingame-Account `{username}` ({game.upper()}) ist bereits mit deinem Profil verknüpft."
                    else:
                        msg = f"⛔ **Zugriff verweigert:** Der Ingame-Account `{username}` ({game.upper()}) ist bereits mit einem anderen Discord-Account verknüpft!"
                else:
                    # 3. Neu anlegen
                    status_a, resp_a = supabase_client_request(
                        "dim_game_accounts",
                        method="POST",
                        data={
                            "discord_user_id": discord_user_id,
                            "game": game,
                            "ingame_username": username
                        },
                        headers_extra={"Prefer": "return=representation"}
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