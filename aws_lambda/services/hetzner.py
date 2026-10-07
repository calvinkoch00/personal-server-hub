import os
import json
import urllib.request
import urllib.error
from config import HETZNER_API_TOKEN, get_stage1_bootloader, get_game_config
from services.dns import update_godaddy_dns
from services.supabase import log_server_start_to_supabase, supabase_client_request

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

def create_volume(name: str, size_gb: int = 20, location: str = "nbg1") -> dict:
    """Erstellt ein neues Block Storage Volume bei Hetzner."""
    payload = {"name": name, "size": size_gb, "location": location, "format": "ext4"}
    res = _request("volumes", method="POST", data=payload)
    return res.get("volume", {})

def delete_volume(volume_id: int) -> bool:
    """Löscht ein Hetzner Block Volume."""
    try:
        _request(f"volumes/{volume_id}", method="DELETE")
        return True
    except Exception as e:
        print(f"[HETZNER ERROR] Volume {volume_id} konnte nicht gelöscht werden: {e}")
        return False

def create_server(
    game: str = "minecraft",
    server_name: str = "default",
    seconds: int = 300,
    readable: str = "5 Minute(n)",
    server_type: str | None = None,
    enable_logging: str = "none"
) -> dict:
    clean_game = game.strip().lower()
    clean_name = server_name.strip().lower().replace(" ", "_")

    # 1. Server-Metadaten aus dim_servers abfragen
    status_sb, resp_sb = supabase_client_request(
        f"dim_servers?game=eq.{clean_game}&server_name=eq.{clean_name}&status=neq.deleted&select=*",
        method="GET"
    )
    db_server = json.loads(resp_sb)[0] if status_sb == 200 and json.loads(resp_sb) else None

    # Fallback auf bestehende Konfiguration falls nicht in DB
    game_cfg = get_game_config(clean_game)
    volume_id = int(db_server["hetzner_volume_id"]) if db_server else game_cfg.get("volume_id", 107045799)
    game_port = int(db_server["game_port"]) if db_server else game_cfg.get("port", 25565)
    resolved_type = server_type or (db_server.get("hetzner_server_type") if db_server else None) or game_cfg.get("default_type", "cpx32")
    subdomain = db_server.get("subdomain") if db_server else os.environ.get("GODADDY_SUBDOMAIN", "mc")
    db_server_id = db_server.get("server_id") if db_server else None

    user_data = get_stage1_bootloader(
        volume_id=volume_id,
        game_port=game_port,
        max_seconds=seconds,
        enable_logging=enable_logging
    )

    vm_name = db_server.get("full_name") if db_server else f"{clean_game}-ondemand"
    payload = {
        "name": vm_name,
        "server_type": resolved_type,
        "image": "ubuntu-24.04",
        "location": os.environ.get("HETZNER_LOCATION", "nbg1"),
        "user_data": user_data,
        "volumes": [volume_id],
        "labels": {"game": clean_game, "server_name": clean_name}
    }

    resp = _request("/servers", method="POST", data=payload)
    server_data = resp["server"]
    server_ip = server_data["public_net"]["ipv4"]["ip"]

    # DNS aktualisieren mit Subdomain
    update_godaddy_dns(ip=server_ip, subdomain=subdomain, server_id=db_server_id)

    # In Supabase protokollieren & Status auf online setzen
    log_server_start_to_supabase(server_data["id"], clean_game, resolved_type, server_id=db_server_id)
    if db_server_id:
        supabase_client_request(f"dim_servers?server_id=eq.{db_server_id}", method="PATCH", data={"status": "online"})

    domain = os.environ.get("GODADDY_DOMAIN", "calvinkoch.ch")

    return {
        "server_id": server_data["id"],
        "db_server_id": db_server_id,
        "name": server_data["name"],
        "game": clean_game,
        "server_name": clean_name,
        "ip": server_ip,
        "domain": f"{subdomain}.{domain}",
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