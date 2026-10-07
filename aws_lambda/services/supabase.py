import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def supabase_client_request(endpoint: str, method: str = "POST", data: dict | list | None = None, headers_extra: dict | None = None) -> tuple[int, str]:
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
    except Exception as e:
        return 500, str(e)

def log_server_start_to_supabase(hetzner_id: int, game: str, server_type: str, server_id: str | None = None):
    """Protokolliert den neu gestarteten Serverlauf in fact_server_runs."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "hetzner_server_id": hetzner_id,
        "server_id": server_id,
        "game": game,
        "server_type": server_type,
        "started_at": now_iso,
        "fallback_end_at": now_iso,
        "currency": "EUR"
    }

    try:
        supabase_client_request(
            "fact_server_runs",
            method="POST",
            data=payload,
            headers_extra={"Prefer": "resolution=merge-duplicates"}
        )
    except Exception as e:
        print(f"[SUPABASE ERROR] Serverlauf konnte nicht protokolliert werden: {e}")