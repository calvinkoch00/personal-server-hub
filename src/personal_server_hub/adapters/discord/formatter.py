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
        return TEMPLATES["server_list_empty"]
    
    header = TEMPLATES["server_list_header"]
    item_template = TEMPLATES["server_item"]
    
    lines = [header]
    for s in servers:
        name = s.get("display_name", s.get("name"))
        st = s.get("status", TEMPLATES["server_status_unknown"])
        ip = s.get("ip") or TEMPLATES["server_ip_offline"]
        lines.append(item_template.format(name=name, status=st, ip=ip))
    return "\n".join(lines)


def format_message(key: str, **kwargs: Any) -> str:
    return MESSAGES[key].format(**kwargs)


def format_response_for_status(status_code: int, message: str) -> str:
    prefix = STATUS_CODES.get(status_code, STATUS_CODES["default"])
    if status_code >= 400:
        return f"{prefix}: {message}"
    return message
