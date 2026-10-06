import os
import json
import urllib.request
import urllib.error
from config import (
    HETZNER_API_TOKEN,
    LOCATION,
    AUTH_SECRET,
    get_game_config,
    get_stage1_bootloader,
    DEFAULT_GAME
)

BASE_URL = "https://api.hetzner.cloud/v1"
GODADDY_API_KEY = os.environ.get("GODADDY_API_KEY")
GODADDY_API_SECRET = os.environ.get("GODADDY_API_SECRET")
GODADDY_DOMAIN = os.environ.get("GODADDY_DOMAIN", "calvinkoch.ch")
GODADDY_SUBDOMAIN = os.environ.get("GODADDY_SUBDOMAIN", "mc")


def _request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    encoded_data = json.dumps(data).encode("utf-8") if data else None
    headers = {
        "Authorization": f"Bearer {HETZNER_API_TOKEN}",
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Hetzner API {e.code}: {err_body}")


def update_godaddy_dns(ip: str):
    """Aktualisiert den A-Record bei GoDaddy."""
    if not GODADDY_API_KEY or not GODADDY_API_SECRET:
        return

    url = f"https://api.godaddy.com/v1/domains/{GODADDY_DOMAIN}/records/A/{GODADDY_SUBDOMAIN}"
    headers = {
        "Authorization": f"sso-key {GODADDY_API_KEY}:{GODADDY_API_SECRET}",
        "Content-Type": "application/json"
    }
    payload = [{"data": ip, "ttl": 600}]
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            print(f"GoDaddy DNS aktualisiert: {resp.status}")
    except Exception as e:
        print(f"GoDaddy DNS Fehler/Timeout: {e}")


def create_server(game: str = DEFAULT_GAME, seconds: int = 300, readable: str = "5 Minute(n)", server_type: str = "cpx32") -> dict:
    config_info = get_game_config(game)
    if not config_info:
        raise ValueError(f"Für das Spiel '{game}' ist kein Volume/Port konfiguriert.")

    volume_id, game_port, clean_game = config_info
    server_name = f"{clean_game}-ondemand"

    payload = {
        "name": server_name,
        "server_type": server_type,
        "image": "ubuntu-24.04",
        "location": LOCATION,
        "start_after_create": True,
        "volumes": [int(volume_id)],
        "ssh_keys": [],
        "user_data": get_stage1_bootloader(volume_id=volume_id, game_port=game_port, max_seconds=seconds)
    }

    res = _request("servers", method="POST", data=payload)
    server = res.get("server", {})
    public_ip = server.get("public_net", {}).get("ipv4", {}).get("ip")

    if public_ip and clean_game == "minecraft":
        update_godaddy_dns(public_ip)

    return {
        "server_id": server.get("id"),
        "name": server.get("name"),
        "status": server.get("status"),
        "ip": public_ip,
        "domain": f"{GODADDY_SUBDOMAIN}.{GODADDY_DOMAIN}",
        "game": clean_game,
        "server_type": server_type,
        "lifetime_seconds": seconds,
        "lifetime_readable": readable
    }


def list_servers() -> list:
    res = _request("servers", method="GET")
    servers = res.get("servers", [])
    results = []
    for s in servers:
        results.append({
            "server_id": s.get("id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "ip": s.get("public_net", {}).get("ipv4", {}).get("ip"),
            "server_type": s.get("server_type", {}).get("name"),
            "created": s.get("created")
        })
    return results


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


def trigger_server_graceful_stop(server_ip: str, server_id: str) -> dict:
    """Sendet den Shutdown-Befehl an den Agenten auf der VM (Port 8080)."""
    url = f"http://{server_ip}:8080/stop"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json", "x-auth-token": AUTH_SECRET or ""},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return {"status": "graceful_triggered"}
    except Exception as e:
        print(f"Agent auf VM nicht erreichbar ({e}), lösche direkt via Hetzner API...")
        return delete_server(server_id)