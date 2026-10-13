# src/personal_server_hub/api/discord_registry.py
from typing import Callable

# Für das YAML-Sync Skript (zum Abgleich)
DISCORD_COMMANDS_REGISTRY = set()
# Für das dynamische Routing im Discord-Adapter
DISCORD_ROUTE_MAP = {}

def discord_command(name: str, api_path: str, method: str = "POST"):
    """
    Mappt einen Discord Command dynamisch auf eine FastAPI Route.
    :param name: Der Name bei Discord (z. B. "server start")
    :param api_path: Der Pfad in FastAPI (z. B. "/server/start")
    :param method: GET oder POST
    """
    def decorator(func: Callable):
        DISCORD_COMMANDS_REGISTRY.add(name)
        DISCORD_ROUTE_MAP[name] = {
            "path": api_path,
            "method": method.upper()
        }
        return func
    return decorator