import json
import datetime
from services.supabase import supabase_client_request, resolve_discord_user_id, is_user_admin
from services.fx import get_current_chf_to_eur_rate

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


def handle_costs(body: dict, data: dict) -> str:
    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id"))

    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    user_param = str(options.get("user", "all")).strip()
    timeframe_param = str(options.get("timeframe", "this month")).strip()

    target_uid, _ = resolve_discord_user_id(user_param, caller_id)
    filter_user = target_uid if target_uid else user_param.lstrip("@")

    start_dt, end_dt, label_tf = parse_timeframe(timeframe_param)

    payload = {
        "filter_user": filter_user,
        "from_date": start_dt.isoformat() if start_dt else None,
        "to_date": end_dt.isoformat() if end_dt else None
    }

    status, resp_text = supabase_client_request("rpc/get_costs_summary", method="POST", data=payload)
    if status not in [200, 201]:
        return f"⚠️️ Fehler beim Abrufen der Abrechnung ({status}): {resp_text}"

    try:
        rows = json.loads(resp_text)
        if not rows:
            return f"ℹ️ Keine Kosten oder Spielzeiten für **{label_tf}** gefunden."

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
        return header + table
    except Exception as e:
        return f"❌ Fehler beim Formatieren der Abrechnung: {e}"


def handle_account(body: dict, data: dict) -> str:
    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id"))

    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    user_param = str(options.get("user", "me")).strip()

    if user_param.lower() == "all":
        status, resp_text = supabase_client_request("view_user_balances?select=*&order=current_balance_eur.asc", method="GET")
        if status == 200:
            rows = json.loads(resp_text)
            if not rows:
                return "ℹ️ Noch keine Kontobewegungen vorhanden."
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
            return header + table
        return f"⚠️ Fehler beim Abrufen der Kontostände ({status}): {resp_text}"

    target_uid, display_name = resolve_discord_user_id(user_param, caller_id)
    if not target_uid:
        return f"❌ Nutzer `{user_param}` konnte nicht gefunden werden."

    status, resp_text = supabase_client_request(f"view_user_balances?discord_user_id=eq.{target_uid}", method="GET")
    if status == 200:
        rows = json.loads(resp_text)
        if not rows:
            return f"ℹ️ Für <@{target_uid}> wurden bisher keine Daten oder Spielzeiten erfasst."

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

        return (
            f"💳 **Kontostand für `{uname}`**\n\n"
            f"• Eingezahlt: `{paid_eur:.2f} €`{chf_note}\n"
            f"• Verursachte Serverkosten: `{cost_gross:.2f} €` *({hours:.1f}h Spielzeit inkl. 8.1% MWST)*\n"
            f"• **{status_label}: {balance:+.2f} €** {status_emoji}"
        )
    return f"⚠️ Fehler beim Abrufen des Kontos ({status}): {resp_text}"


def handle_cash(body: dict, data: dict) -> str:
    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    caller_id = str(caller_data.get("id"))
    caller_name = str(caller_data.get("username", "Admin"))

    if not is_user_admin(caller_id):
        return "⛔ **Zugriff verweigert:** Nur Administratoren dürfen diesen Befehl ausführen."

    suboptions = data.get("options", [])
    add_opts = suboptions[0].get("options", []) if suboptions and suboptions[0].get("name") == "add" else suboptions
    opts_map = {o["name"]: o.get("value") for o in add_opts}

    target_user_raw = str(opts_map.get("user", "")).strip()
    amount_raw = opts_map.get("amount")
    currency = str(opts_map.get("currency", "CHF")).strip().upper()
    note = str(opts_map.get("note", "Einzahlung"))

    target_uid, _ = resolve_discord_user_id(target_user_raw, caller_id)

    if not target_uid:
        return f"❌ Empfänger `{target_user_raw}` konnte nicht in der Datenbank gefunden werden."
    if not amount_raw or float(amount_raw) <= 0:
        return "❌ Bitte gib einen gültigen Betrag größer als 0 an."
    if currency not in ["CHF", "EUR"]:
        return "❌ Bitte als Währung entweder `CHF` oder `EUR` angeben."

    amount_orig = float(amount_raw)
    if currency == "CHF":
        fx_rate, fx_source = get_current_chf_to_eur_rate()
        fx_text = f" *(Wechselkurs 1 CHF = {fx_rate:.4f} EUR [{fx_source}])* "
    else:
        fx_rate = 1.0000
        fx_text = ""

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
        return (
            f"✅ **Zahlung erfolgreich verbucht!**\n"
            f"• Nutzer: <@{target_uid}>\n"
            f"• Erhaltener Betrag: `{amount_orig:.2f} {currency}`\n"
            f"• Gutgeschrieben in EUR: **`+{amount_eur:.2f} €`**{fx_text}\n"
            f"• Notiz: *{note}* (gebucht von `{caller_name}`)"
        )
    return f"⚠ Fehler beim Speichern der Zahlung ({status_p}): {resp_p}"