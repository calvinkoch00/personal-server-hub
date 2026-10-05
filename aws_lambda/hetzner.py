import json
import urllib.request
import urllib.error
from config import (
    HETZNER_API_TOKEN,
    VOLUME_ID,
    LOCATION,
    parse_duration_to_seconds,
    get_cloud_init_script
)

BASE_URL = "https://api.hetzner.cloud/v1"

def _request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    url = f"{BASE_URL}{endpoint}"
    encoded_data = json.dumps(data).encode("utf-8") if data else None

    headers = {
        "Authorization": f"Bearer {HETZNER_API_TOKEN}",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        content = resp.read().decode("utf-8")
        return json.loads(content) if content else {}

def create_server(game: str = "minecraft", seconds: int = 300, readable: str = "5 Minuten", server_type: str = "cpx32") -> dict:
    server_name = f"{game}-ondemand"

    payload = {
        "name": server_name,
        "server_type": server_type,
        "image": "ubuntu-24.04",
        "location": LOCATION,
        "start_after_create": True,
        "volumes": [int(VOLUME_ID)],
        "ssh_keys": ["calvin-macbook"],
        "user_data": get_cloud_init_script(max_seconds=seconds, game=game)
    }

    res = _request("/servers", method="POST", data=payload)
    server = res.get("server", {})
    return {
        "server_id": server.get("id"),
        "name": server.get("name"),
        "status": server.get("status"),
        "ip": server.get("public_net", {}).get("ipv4", {}).get("ip"),
        "game": game,
        "server_type": server_type,
        "lifetime_seconds": seconds,
        "lifetime_readable": readable
    }

def get_server_status(server_id: str) -> dict:
    res = _request(f"/servers/{server_id}", method="GET")
    server = res.get("server", {})
    return {
        "server_id": server.get("id"),
        "status": server.get("status"),
        "ip": server.get("public_net", {}).get("ipv4", {}).get("ip")
    }

def list_servers() -> list:
    res = _request("/servers", method="GET")
    servers = res.get("servers", [])
    result = []
    for s in servers:
        result.append({
            "server_id": s.get("id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "ip": s.get("public_net", {}).get("ipv4", {}).get("ip"),
            "server_type": s.get("server_type", {}).get("name"),
            "created": s.get("created")
        })
    return result

def delete_server(server_id: str) -> dict:
    res = _request(f"/servers/{server_id}", method="DELETE")
    return {"message": "Server wird gelöscht", "action": res.get("action")}