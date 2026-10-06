import os
import json
import urllib.request
from config import AUTH_SECRET

AGENT_PORT = 8080


def _call_agent(server_ip: str, endpoint: str, timeout: float = 4.0) -> dict:
    url = f"http://{server_ip}:{AGENT_PORT}{endpoint}"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "x-auth-token": AUTH_SECRET or ""
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read().decode("utf-8")
        return json.loads(content) if content else {}


def call_agent_remote(target_ip: str, endpoint: str, data: dict = None) -> dict:
    """Sendet einen HTTP-Request an die Control-API des Agenten auf Port 8080."""
    auth_secret = os.environ.get("AUTH_SECRET", "")
    url = f"http://{target_ip}:8080/{endpoint.lstrip('/')}"
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-auth-token": auth_secret
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        content = resp.read().decode("utf-8")
        return json.loads(content) if content else {}


def toggle_remote_logging(server_ip: str) -> dict:
    """Schaltet das Discord Live-Logging auf der VM um."""
    return _call_agent(server_ip, "/toggle-log")


def stop_remote_server(server_ip: str) -> dict:
    """Weist den Agenten auf der VM an, Container und Server sauber herunterzufahren."""
    return _call_agent(server_ip, "/stop", timeout=2.0)