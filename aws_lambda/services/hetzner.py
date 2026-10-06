import os
import json
import urllib.request
import urllib.error
from config import HETZNER_API_TOKEN, get_stage1_bootloader, get_game_config
from services.dns import update_godaddy_dns
from services.supabase import log_server_start_to_supabase

BASE_URL = "https://api.hetzner.cloud/v1"

def _request(endpoint: str, method: str = "GET", data: dict | None = None) -> dict:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    encoded = json.dumps(data).encode("utf-8") if data else None
    headers = {
        "Authorization": f"Bearer {HETZNER_API_TOKEN}",
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(url, data=encoded, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Hetzner API {e.code}: {err_body}")

def create_server(
    game: str = "minecraft",
    seconds: int = 300,
    readable: str = "5 Minute(n)",
    server_type: str = "cpx32",
    enable_logging: str = "none"
) -> dict:
    game_cfg = get_game_config(game)
    volume_id = game_cfg.get("volume_id", 107045799)
    game_port = game_cfg.get("port", 25565)
    resolved_type = server_type or game_cfg.get("default_type", "cpx32")

    user_data = get_stage1_bootloader(
        volume_id=volume_id,
        game_port=game_port,
        max_seconds=seconds,
        enable_logging=enable_logging
    )

    payload = {
        "name": f"{game}-ondemand",
        "server_type": resolved_type,
        "image": "ubuntu-24.04",
        "location": os.environ.get("HETZNER_LOCATION", "nbg1"),
        "user_data": user_data,
        "volumes": [volume_id],
        "labels": {"game": game}
    }

    resp = _request("/servers", method="POST", data=payload)
    server_data = resp["server"]
    server_ip = server_data["public_net"]["ipv4"]["ip"]

    update_godaddy_dns(server_ip)
    log_server_start_to_supabase(server_data["id"], game, resolved_type)

    subdomain = os.environ.get("GODADDY_SUBDOMAIN", "mc")
    domain = os.environ.get("GODADDY_DOMAIN", "calvinkoch.ch")

    return {
        "server_id": server_data["id"],
        "name": server_data["name"],
        "game": game,
        "ip": server_ip,
        "domain": os.environ.get("DOMAIN_NAME", f"{subdomain}.{domain}"),
        "lifetime_readable": readable,
        "server_type": resolved_type,
        "status": server_data["status"]
    }

def list_servers() -> list[dict]:
    res = _request("servers", method="GET")
    return [
        {
            "server_id": s.get("id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "ip": s.get("public_net", {}).get("ipv4", {}).get("ip"),
            "server_type": s.get("server_type", {}).get("name"),
            "created": s.get("created")
        }
        for s in res.get("servers", [])
    ]

def get_server_status(server_id: str) -> dict:
    res = _request(f"servers/{server_id}", method="GET")
    server = res.get("server", {})
    return {
        "server_id": server.get("id"),
        "status": server.get("status"),
        "ip": server.get("public_net", {}).get("ipv4", {}).get("ip")
    }

def delete_server(server_id: str) -> dict:
    res = _request(f"servers/{server_id}", method="DELETE")
    return {"message": "Server wird gelöscht", "action": res.get("action")}