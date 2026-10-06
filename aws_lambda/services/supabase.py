import os
import re
import json
import urllib.request
import urllib.error

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


def is_user_admin(discord_user_id: str) -> bool:
    status, resp = supabase_client_request(f"dim_users?discord_user_id=eq.{discord_user_id}&select=role", method="GET")
    if status == 200:
        records = json.loads(resp)
        if records and records[0].get("role") == "admin":
            return True
    return False