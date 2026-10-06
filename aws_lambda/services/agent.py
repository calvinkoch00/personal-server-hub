import json
import urllib.request
from config import AUTH_SECRET

AGENT_PORT = 8080

def call_agent_remote(target_ip: str, endpoint: str, data: dict | None = None, timeout: float = 3.0) -> dict:
    url = f"http://{target_ip}:{AGENT_PORT}/{endpoint.lstrip('/')}"
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-auth-token": AUTH_SECRET or ""
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read().decode("utf-8")
        return json.loads(content) if content else {}

def toggle_remote_logging(server_ip: str, mode: str = "game") -> dict:
    return call_agent_remote(server_ip, "toggle-log", data={"mode": mode}, timeout=5.0)

def stop_remote_server(server_ip: str) -> dict:
    return call_agent_remote(server_ip, "stop", timeout=2.0)