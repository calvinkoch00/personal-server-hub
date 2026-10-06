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


def toggle_remote_logging(server_ip: str) -> dict:
    """Schaltet das Discord Live-Logging auf der VM um."""
    return _call_agent(server_ip, "/toggle-log")


def stop_remote_server(server_ip: str) -> dict:
    """Weist den Agenten auf der VM an, Container und Server sauber herunterzufahren."""
    return _call_agent(server_ip, "/stop", timeout=2.0)