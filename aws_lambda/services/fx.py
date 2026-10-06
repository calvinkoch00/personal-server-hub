import os
import json
import datetime
import urllib.request
from services.supabase import supabase_client_request

def get_current_chf_to_eur_rate() -> tuple[float, str]:
    """
    Ermittelt den Kurs CHF -> EUR:
    1. Prüft, ob heute bereits ein Kurs in dim_exchange_rates gecacht ist.
    2. Falls nicht: Ruft EZB-Kurs via API ab und speichert ihn in Supabase.
    3. Fallback: Nimmt den neuesten historischen Kurs aus Supabase.
    """
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    status, resp = supabase_client_request(
        f"dim_exchange_rates?rate_date=eq.{today_str}&base_currency=eq.CHF&target_currency=eq.EUR&select=rate",
        method="GET"
    )
    if status == 200:
        rows = json.loads(resp)
        if rows:
            return float(rows[0]["rate"]), f"Supabase Cache ({today_str})"

    try:
        req = urllib.request.Request("https://api.frankfurter.app/latest?from=CHF&to=EUR", headers={"User-Agent": "GameServer-Bot/1.0"})
        with urllib.request.urlopen(req, timeout=3) as api_resp:
            if api_resp.status == 200:
                data = json.loads(api_resp.read().decode("utf-8"))
                rate = float(data.get("rates", {}).get("EUR", 0.0))
                if rate > 0:
                    api_date = data.get("date", today_str)
                    supabase_client_request(
                        "dim_exchange_rates",
                        method="POST",
                        data={
                            "rate_date": api_date,
                            "base_currency": "CHF",
                            "target_currency": "EUR",
                            "rate": rate,
                            "source": "api.frankfurter.app (EZB)"
                        },
                        headers_extra={"Prefer": "resolution=merge-duplicates"}
                    )
                    return rate, f"live ({api_date})"
    except Exception as e:
        print(f"[FX API WARNING] Live-Abruf fehlgeschlagen: {e}", flush=True)

    status_fb, resp_fb = supabase_client_request(
        "dim_exchange_rates?base_currency=eq.CHF&target_currency=eq.EUR&order=rate_date.desc&limit=1&select=rate,rate_date",
        method="GET"
    )
    if status_fb == 200:
        fb_rows = json.loads(resp_fb)
        if fb_rows:
            return float(fb_rows[0]["rate"]), f"letzter bekannter Kurs ({fb_rows[0]['rate_date']})"

    return float(os.environ.get("FX_CHF_TO_EUR", "1.05")), "Notfall-Fallback"