import os
import re
import json
import datetime
import urllib.request
import urllib.error
import hetzner

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
FX_CHF_TO_EUR = float(os.environ.get("FX_CHF_TO_EUR", "0.95"))


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


def resolve_discord_user_id(user_param: str, caller_id: str) -> tuple[str | None, str]:
    val = (user_param or "").strip()
    if not val or val.lower() == "me":
        return caller_id, "me"

    mention_match = re.match(r"^<@!?(\d+)>$", val)
    if mention_match:
        uid = mention_match.group(1)
        return uid, f"<@{uid}>"

    if val.isdigit():
        return val, val

    username_clean = val.lstrip("@")
    status, resp = supabase_client_request(f"dim_users?discord_username=ilike.{username_clean}&select=discord_user_id,discord_username", method="GET")
    if status == 200:
        rows = json.loads(resp)
        if rows:
            return str(rows[0]["discord_user_id"]), rows[0].get("discord_username", username_clean)

    return None, val


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
        "• `/account` — Zeigt dein aktuelles Guthaben / Kontostand\n"
        "• `/cash add` — *(Admin)* Guthabeneinzahlung für einen Nutzer buchen\n"
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
    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id"))
    caller_name = str(caller_data.get("username", "Admin"))

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

        target_uid, display_name = resolve_discord_user_id(user_param, caller_id)
        filter_user = target_uid if target_uid else user_param.lstrip("@")

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
                    header = f"📊 **Kostenaufstellung ({label_tf})** *(inkl. 8.1% MWST)*\n*Server-Gesamtkosten: {float(total_server):.2f} €*\n"
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

    elif command == "account":
        options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
        user_param = str(options.get("user", "me")).strip()

        if user_param.lower() == "all":
            status, resp_text = supabase_client_request("view_user_balances?select=*&order=current_balance_eur.asc", method="GET")
            if status == 200:
                rows = json.loads(resp_text)
                if not rows:
                    msg = "ℹ️ Noch keine Kontobewegungen vorhanden."
                else:
                    header = "💳 **Übersicht aller Benutzer-Kontostände**\n"
                    table = "```asciidoc\n"
                    table += f"{'Spieler':<14} | {'Bezahlt':<8} | {'Kosten':<8} | {'Saldo'}\n"
                    table += "-" * 42 + "\n"
                    for r in rows:
                        name = str(r.get("discord_username") or "Unknown")[:13]
                        paid = f"{float(r.get('total_paid_eur', 0)):.2f}€"
                        cost = f"{float(r.get('total_cost_gross_eur', 0)):.2f}€"
                        bal = float(r.get("current_balance_eur", 0))
                        icon = "+" if bal >= 0 else ""
                        table += f"{name:<14} | {paid:<8} | {cost:<8} | {icon}{bal:.2f}€\n"
                    table += "```"
                    msg = header + table
            else:
                msg = f"⚠️ Fehler beim Abrufen der Kontostände ({status}): {resp_text}"
        else:
            target_uid, display_name = resolve_discord_user_id(user_param, caller_id)
            if not target_uid:
                msg = f"❌ Nutzer `{user_param}` konnte nicht gefunden werden."
            else:
                status, resp_text = supabase_client_request(f"view_user_balances?discord_user_id=eq.{target_uid}", method="GET")
                if status == 200:
                    rows = json.loads(resp_text)
                    if not rows:
                        msg = f"ℹ️ Für <@{target_uid}> wurden bisher keine Daten oder Spielzeiten erfasst."
                    else:
                        r = rows[0]
                        uname = r.get("discord_username") or display_name
                        paid_eur = float(r.get("total_paid_eur", 0))
                        paid_chf = float(r.get("total_paid_chf", 0))
                        hours = float(r.get("total_hours_played", 0))
                        cost_gross = float(r.get("total_cost_gross_eur", 0))
                        balance = float(r.get("current_balance_eur", 0))

                        status_emoji = "🟢" if balance >= 0 else "🔴"
                        status_label = "Guthaben" if balance >= 0 else "Offener Betrag (Schulden)"
                        chf_note = f" (davon {paid_chf:.2f} CHF)" if paid_chf > 0 else ""

                        msg = (
                            f"💳 **Kontostand für `{uname}`**\n\n"
                            f"• Eingezahlt: `{paid_eur:.2f} €`{chf_note}\n"
                            f"• Verursachte Serverkosten: `{cost_gross:.2f} €` *({hours:.1f}h Spielzeit inkl. 8.1% MWST)*\n"
                            f"• **{status_label}: {balance:+.2f} €** {status_emoji}"
                        )
                else:
                    msg = f"⚠️ Fehler beim Abrufen des Kontos ({status}): {resp_text}"

    elif command == "cash":
        # 1. Admin-Prüfung über Spalte 'role' in dim_users
        status_role, resp_role = supabase_client_request(f"dim_users?discord_user_id=eq.{caller_id}&select=role", method="GET")
        is_admin = False
        if status_role == 200:
            user_records = json.loads(resp_role)
            if user_records and user_records[0].get("role") == "admin":
                is_admin = True

        if not is_admin:
            msg = "⛔ **Zugriff verweigert:** Nur Administratoren dürfen diesen Befehl ausführen."
        else:
            suboptions = data.get("options", [])
            add_opts = suboptions[0].get("options", []) if suboptions and suboptions[0].get("name") == "add" else suboptions
            opts_map = {o["name"]: o.get("value") for o in add_opts}

            target_user_raw = str(opts_map.get("user", "")).strip()
            amount_raw = opts_map.get("amount")
            currency = str(opts_map.get("currency", "CHF")).strip().upper()
            note = str(opts_map.get("note", "Einzahlung"))

            target_uid, display_name = resolve_discord_user_id(target_user_raw, caller_id)

            if not target_uid:
                msg = f"❌ Empfänger `{target_user_raw}` konnte nicht in der Datenbank gefunden werden."
            elif not amount_raw or float(amount_raw) <= 0:
                msg = "❌ Bitte gib einen gültigen Betrag größer als 0 an."
            elif currency not in ["CHF", "EUR"]:
                msg = "❌ Bitte als Währung entweder `CHF` oder `EUR` angeben."
            else:
                amount_orig = float(amount_raw)
                fx_rate = FX_CHF_TO_EUR if currency == "CHF" else 1.0000
                amount_eur = round(amount_orig * fx_rate, 2)

                payment_data = {
                    "discord_user_id": target_uid,
                    "amount_original": amount_orig,
                    "currency": currency,
                    "exchange_rate": fx_rate,
                    "amount_eur": amount_eur,
                    "note": note,
                    "created_by": caller_name
                }

                status_p, resp_p = supabase_client_request("fact_user_payments", method="POST", data=payment_data)
                if status_p in [200, 201]:
                    fx_text = f" *(Wechselkurs 1 CHF = {fx_rate:.4f} EUR)*" if currency == "CHF" else ""
                    msg = (
                        f"✅ **Zahlung erfolgreich verbucht!**\n"
                        f"• Nutzer: <@{target_uid}>\n"
                        f"• Erhaltener Betrag: `{amount_orig:.2f} {currency}`\n"
                        f"• Gutgeschrieben in EUR: **`+{amount_eur:.2f} €`**{fx_text}\n"
                        f"• Notiz: *{note}* (gebucht von `{caller_name}`)"
                    )
                else:
                    msg = f"⚠ Fehler beim Speichern der Zahlung ({status_p}): {resp_p}"

    elif command == "addgameaccount":
        discord_user_id = caller_id
        discord_username = str(caller_data.get("username", "Unknown"))

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