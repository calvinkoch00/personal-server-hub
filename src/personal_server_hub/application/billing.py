import json

from personal_server_hub.integrations import fx, supabase


def get_exchange_rate(payload: dict) -> tuple[int, dict]:
    base = payload.get("base") or payload.get("from") or "CHF"
    target = payload.get("target") or payload.get("to") or "EUR"
    rate, source, rate_id = fx.get_exchange_rate(base_currency=base, target_currency=target)
    return 200, {
        "base_currency": base.upper(),
        "target_currency": target.upper(),
        "rate": rate,
        "source": source,
        "rate_id": rate_id,
    }


def get_costs_summary(payload: dict) -> tuple[int, dict]:
    status, resp_text = supabase.supabase_client_request("rpc/get_costs_summary", method="POST", data=payload)
    if status not in [200, 201]:
        return status, {"error": f"Fehler beim Abrufen der Abrechnung ({status}): {resp_text}"}
    return 200, {"rows": json.loads(resp_text)}


def get_account_balance(payload: dict) -> tuple[int, dict]:
    user_param = payload.get("user", "me")
    if str(user_param).lower() == "all":
        status, resp_text = supabase.supabase_client_request("view_user_balances?select=*&order=current_balance.asc", method="GET")
        if status == 200:
            return 200, {"mode": "all", "rows": json.loads(resp_text)}
        return status, {"error": f"Fehler beim Abrufen der Kontostände ({status}): {resp_text}"}

    target_uid = payload.get("target_uid")
    status, resp_text = supabase.supabase_client_request(f"view_user_balances?discord_user_id=eq.{target_uid}", method="GET")
    if status == 200:
        rows = json.loads(resp_text)
        return 200, {"mode": "single", "user": rows[0] if rows else None}
    return status, {"error": f"Fehler beim Abrufen des Kontos ({status}): {resp_text}"}


def add_cash_payment(payload: dict) -> tuple[int, dict]:
    target_uid = payload.get("target_uid")
    amount_orig = float(payload.get("amount", 0.0))
    currency = payload.get("currency", "CHF").upper()
    target_currency = payload.get("target_currency", "EUR").upper()
    note = payload.get("note", "Einzahlung")
    caller_name = payload.get("created_by", "Admin")

    fx_rate, fx_source, rate_id = fx.get_exchange_rate(
        base_currency=currency,
        target_currency=target_currency,
    )

    if currency != target_currency:
        fx_text = f" *(Wechselkurs 1 {currency} = {fx_rate:.4f} {target_currency} [{fx_source}])* "
    else:
        fx_text = ""

    amount_target = round(amount_orig * fx_rate, 2)
    payment_data = {
        "discord_user_id": target_uid,
        "amount": amount_target,
        "currency": target_currency,
        "payment_amount": amount_orig,
        "payment_currency": currency,
        "exchange_rate": fx_rate,
        "exchange_rate_id": rate_id,
        "note": note,
        "created_by": caller_name,
    }

    status_p, resp_p = supabase.supabase_client_request("fact_user_payments", method="POST", data=payment_data)
    if status_p in [200, 201]:
        return 200, {
            "payment": payment_data,
            "fx_text": fx_text,
        }
    return status_p, {"error": f"Fehler beim Speichern der Zahlung ({status_p}): {resp_p}"}
