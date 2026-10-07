import json
import rest_api
from commands.finance import resolve_discord_user_id
from services.supabase import supabase_client_request

def handle_account(data: dict, caller_id: str) -> str:
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    user_param = str(options.get("user", "me")).strip()

    if user_param.lower() == "all":
        status, resp = rest_api.handle_account({"user": "all"})
        if status != 200:
            return resp.get("error", "Fehler")

        rows = resp.get("rows", [])
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
    else:
        target_uid, display_name = resolve_discord_user_id(user_param, caller_id)
        if not target_uid:
            return f"❌ Nutzer `{user_param}` konnte nicht gefunden werden."

        status, resp = rest_api.handle_account({"user": "single", "target_uid": target_uid})
        if status != 200:
            return resp.get("error", "Fehler")

        r = resp.get("user")
        if not r:
            return f"ℹ️ Für <@{target_uid}> wurden bisher keine Daten oder Spielzeiten erfasst."

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

def handle_cash(data: dict, caller_id: str, caller_name: str) -> str:
    status_role, resp_role = supabase_client_request(f"dim_users?discord_user_id=eq.{caller_id}&select=role", method="GET")
    is_admin = False
    if status_role == 200:
        user_records = json.loads(resp_role)
        if user_records and user_records[0].get("role") == "admin":
            is_admin = True

    if not is_admin:
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

    status, resp = rest_api.handle_cash({
        "target_uid": target_uid,
        "amount": amount_raw,
        "currency": currency,
        "target_currency": "EUR",
        "note": note,
        "created_by": caller_name
    })

    if status != 200:
        return f"⚠ {resp.get('error')}"

    payment = resp["payment"]
    fx_text = resp["fx_text"]

    return (
        f"✅ **Zahlung erfolgreich verbucht!**\n"
        f"• Nutzer: <@{target_uid}>\n"
        f"• Erhaltener Betrag: `{payment['amount_original']:.2f} {payment['currency']}`\n"
        f"• Gutgeschrieben in EUR: **`+{payment['amount_eur']:.2f} €`**{fx_text}\n"
        f"• Notiz: *{payment['note']}* (gebucht von `{caller_name}`)"
    )

def handle_addgameaccount(data: dict, caller_id: str, caller_data: dict) -> str:
    discord_user_id = caller_id
    discord_username = str(caller_data.get("username", "Unknown"))

    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    game = str(options.get("game", "")).strip().lower()
    username = str(options.get("username", "")).strip()

    if not game or not username:
        return "❌ Bitte gib Spiel und Ingame-Namen an: `/addgameaccount <game> <username>`"

    try:
        status, resp = rest_api.handle_addgameaccount({
            "discord_user_id": discord_user_id,
            "discord_username": discord_username,
            "game": game,
            "username": username
        })

        if status == 200:
            if resp.get("status") == "already_linked_self":
                return f"ℹ Der Ingame-Account `{username}` ({game.upper()}) ist bereits mit deinem Profil verknüpft."
            return f"✅ Ingame-Account `{username}` ({game.upper()}) wurde erfolgreich mit deinem Discord-Profil verknüpft!"
        elif status == 403:
            return f"⛔ **Zugriff verweigert:** Der Ingame-Account `{username}` ({game.upper()}) ist bereits mit einem anderen Discord-Account verknüpft!"
        else:
            return f"⚠ {resp.get('error')}"
    except Exception as e:
        return f"❌ Datenbankfehler: {e}"