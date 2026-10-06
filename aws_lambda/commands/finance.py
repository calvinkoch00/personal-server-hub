import re
import datetime
import rest_api
from services.supabase import supabase_client_request

def resolve_discord_user_id(user_param: str, caller_id: str) -> tuple[str | None, str]:
    import json
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

def handle_costs(data: dict, caller_id: str) -> str:
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

    status, resp = rest_api.handle_costs(payload)
    if status != 200:
        return resp.get("error", "Fehler")

    try:
        rows = resp.get("rows", [])
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