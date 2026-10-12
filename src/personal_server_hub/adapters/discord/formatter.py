import os
import yaml
from typing import Any

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "discord_responses.yaml")

_config = {}
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f) or {}

TEMPLATES = _config.get("status_templates", {})
STATUS_CODES = _config.get("status_codes", {})
MESSAGES = _config.get("command_messages", {})


def format_server_list(resp: dict) -> str:
    servers = resp.get("servers", resp.get("data", []))
    if not servers:
        return TEMPLATES.get("server_list_empty", "⚪ Keine registrierten Server vorhanden.")
    
    header = TEMPLATES.get("server_list_header", "🟢 **Registrierte Server:**")
    item_template = TEMPLATES.get("server_item", "• **{name}** (`{status}`) — IP: `{ip}`")
    
    lines = [header]
    for s in servers:
        name = s.get("display_name", s.get("name"))
        st = s.get("status", "unknown")
        ip = s.get("ip") or "offline"
        lines.append(item_template.format(name=name, status=st, ip=ip))
    return "\n".join(lines)


def format_message(key: str, default: str, **kwargs: Any) -> str:
    msg_template = MESSAGES.get(key, default)
    try:
        return msg_template.format(**kwargs)
    except Exception:
        return msg_template


def format_response_for_status(status_code: int, message: str) -> str:
    prefix = STATUS_CODES.get(status_code, "ℹ️")
    if status_code >= 400:
        return f"{prefix}: {message}"
    return message
