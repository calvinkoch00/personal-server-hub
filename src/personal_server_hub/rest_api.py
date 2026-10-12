import re
import json
from datetime import datetime, timezone
from personal_server_hub.services import supabase
from personal_server_hub.services import agent, dns, fx, hetzner, mojang
from personal_server_hub.application.dns import list_dns_records, sync_dns_records
from personal_server_hub.application.game_accounts import add_game_account
from personal_server_hub.application.billing import (
    add_cash_payment,
    get_account_balance,
    get_costs_summary,
    get_exchange_rate,
)
from personal_server_hub.application.whitelist import (
    add_whitelist,
    list_whitelist,
    remove_whitelist,
)
from personal_server_hub.application.servers import (
    handle_log as app_handle_log,
    handle_server_create as app_handle_server_create,
    handle_server_delete as app_handle_server_delete,
    handle_server_reload_files as app_handle_reload_files,
    handle_servers as app_handle_servers,
    handle_start as app_handle_start,
    handle_stop as app_handle_stop,
)

def resolve_server_slug(raw_name: str | None, game: str = "minecraft") -> str:
    cleaned = str(raw_name or "").strip().lower().replace(" ", "_")
    if not cleaned or cleaned in ["default", f"{game}-default"]:
        return f"{game}-default"
    return cleaned

def handle_start(payload: dict) -> tuple[int, dict]:
    return app_handle_start(payload)

def handle_servers() -> tuple[int, dict]:
    return app_handle_servers()

def handle_stop(payload: dict) -> tuple[int, dict]:
    return app_handle_stop(payload)

def handle_server_create(payload: dict) -> tuple[int, dict]:
    return app_handle_server_create(payload)

def handle_server_delete(payload: dict) -> tuple[int, dict]:
    return app_handle_server_delete(payload)

def handle_log(payload: dict) -> tuple[int, dict]:
    return app_handle_log(payload)

def handle_costs(payload: dict) -> tuple[int, dict]:
    return get_costs_summary(payload)

def handle_account(payload: dict) -> tuple[int, dict]:
    return get_account_balance(payload)

def handle_exchange_rate(payload: dict) -> tuple[int, dict]:
    return get_exchange_rate(payload)

def handle_cash(payload: dict) -> tuple[int, dict]:
    return add_cash_payment(payload)

def handle_addgameaccount(payload: dict) -> tuple[int, dict]:
    return add_game_account(payload)

def handle_dns_sync(payload: dict) -> tuple[int, dict]:
    return sync_dns_records()

def handle_dns_records(payload: dict) -> tuple[int, dict]:
    return list_dns_records()

def handle_whitelist_add(payload: dict) -> tuple[int, dict]:
    return add_whitelist(payload)

def handle_whitelist_remove(payload: dict) -> tuple[int, dict]:
    return remove_whitelist(payload)

def handle_whitelist_list(payload: dict) -> tuple[int, dict]:
    return list_whitelist(payload)

def handle_server_reload_files(payload: dict) -> tuple[int, dict]:
    return app_handle_reload_files(payload)

def route_request(path: str, body: dict) -> tuple[int, dict]:
    raw_path = path or "/"
    action = body.get("action")

    if raw_path.endswith("/server/start") or raw_path.endswith("/start") or action == "start":
        return handle_start(body)
    if raw_path.endswith("/server/stop") or raw_path.endswith("/stop") or action == "stop":
        return handle_stop(body)
    if raw_path.endswith("/server/create") or action == "server_create":
        return handle_server_create(body)
    if raw_path.endswith("/server/delete") or action == "server_delete":
        return handle_server_delete(body)
    if raw_path.endswith("/servers") or action == "list":
        return handle_servers()

    if raw_path.endswith("/log") or action == "log":
        return handle_log(body)
    if raw_path.endswith("/costs"):
        return handle_costs(body)
    if raw_path.endswith("/account"):
        return handle_account(body)
    if raw_path.endswith("/cash"):
        return handle_cash(body)
    if raw_path.endswith("/exchange-rate") or action == "exchange_rate":
        return handle_exchange_rate(body)

    if raw_path.endswith("/addgameaccount") or action == "addgameaccount":
        return handle_addgameaccount(body)

    if raw_path.endswith("/dns/sync") or action == "dns_sync":
        return handle_dns_sync(body)
    if raw_path.endswith("/dns/records") or action == "dns_records":
        return handle_dns_records(body)

    if raw_path.endswith("/whitelist/add") or action == "whitelist_add":
        return handle_whitelist_add(body)
    if raw_path.endswith("/whitelist/remove") or action == "whitelist_remove":
        return handle_whitelist_remove(body)
    if raw_path.endswith("/whitelist/list") or action == "whitelist_list":
        return handle_whitelist_list(body)
    if raw_path.endswith("/server/reload-files") or action == "server_reload_files":
        return handle_server_reload_files(body)

    return 404, {"error": f"Endpoint '{raw_path}' nicht gefunden"}