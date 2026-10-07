import os
import json
import datetime
import urllib.request
from services.supabase import supabase_client_request

def get_exchange_rate(
    base_currency: str = "CHF",
    target_currency: str = "EUR"
) -> tuple[float, str, str | None]:
    """
    Ermittelt den Wechselkurs für ein beliebiges Währungspaar:
    1. Identische Währungen -> 1.0 (direkt)
    2. Prüft dim_exchange_rates für das heutige Datum
    3. Live-Abruf über Frankfurter API (EZB) & persistiert in dim_exchange_rates
    4. Fallback: Neuester historischer Kurs aus dim_exchange_rates
    5. Notfall-Fallback
    """
    base = (base_currency or "CHF").strip().upper()
    target = (target_currency or "EUR").strip().upper()

    if base == target:
        return 1.0, "direct", None

    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    status, resp = supabase_client_request(
        f"dim_exchange_rates?rate_date=eq.{today_str}&base_currency=eq.{base}&target_currency=eq.{target}&select=rate_id,rate",
        method="GET"
    )
    if status == 200:
        rows = json.loads(resp)
        if rows:
            return float(rows[0]["rate"]), f"Supabase Cache ({today_str})", str(rows[0].get("rate_id"))

    try:
        req = urllib.request.Request(
            f"https://api.frankfurter.app/latest?from={base}&to={target}",
            headers={"User-Agent": "GameServer-Bot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3) as api_resp:
            if api_resp.status == 200:
                data = json.loads(api_resp.read().decode("utf-8"))
                rate = float(data.get("rates", {}).get(target, 0.0))
                if rate > 0:
                    api_date = data.get("date", today_str)
                    status_ins, resp_ins = supabase_client_request(
                        "dim_exchange_rates",
                        method="POST",
                        data={
                            "rate_date": api_date,
                            "base_currency": base,
                            "target_currency": target,
                            "rate": rate,
                            "source": "api.frankfurter.app (EZB)"
                        },
                        headers_extra={"Prefer": "resolution=merge-duplicates,return=representation"}
                    )
                    rate_id = None
                    if status_ins in [200, 201]:
                        ins_rows = json.loads(resp_ins)
                        if ins_rows:
                            rate_id = str(ins_rows[0].get("rate_id"))
                    return rate, f"live ({api_date})", rate_id
    except Exception as e:
        print(f"[FX API WARNING] Live-Abruf fehlgeschlagen: {e}", flush=True)

    status_fb, resp_fb = supabase_client_request(
        f"dim_exchange_rates?base_currency=eq.{base}&target_currency=eq.{target}&order=rate_date.desc&limit=1&select=rate_id,rate,rate_date",
        method="GET"
    )
    if status_fb == 200:
        fb_rows = json.loads(resp_fb)
        if fb_rows:
            return float(fb_rows[0]["rate"]), f"letzter bekannter Kurs ({fb_rows[0]['rate_date']})", str(fb_rows[0].get("rate_id"))

    env_fallback = float(os.environ.get(f"FX_{base}_TO_{target}", os.environ.get("FX_CHF_TO_EUR", "1.05")))
    return env_fallback, "Notfall-Fallback", None