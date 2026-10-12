import json

from personal_server_hub.integrations import supabase


def register_user(payload: dict) -> tuple[int, dict]:
    discord_user_id = str(payload.get("discord_user_id") or "").strip()
    discord_username = str(payload.get("discord_username") or "Unknown").strip()

    if not discord_user_id:
        return 400, {"error": "Feld 'discord_user_id' ist erforderlich"}

    if not discord_username:
        return 400, {"error": "Feld 'discord_username' darf nicht leer sein"}

    status, response = supabase.supabase_client_request(
        "dim_users",
        method="POST",
        data={
            "discord_user_id": discord_user_id,
            "discord_username": discord_username,
        },
        headers_extra={"Prefer": "resolution=merge-duplicates"},
    )
    if status not in [200, 201, 204]:
        return status, {
            "error": f"Fehler beim Registrieren des Discord-Nutzers ({status}): {response}"
        }

    return 200, {
        "status": "registered",
        "discord_user_id": discord_user_id,
        "discord_username": discord_username,
    }

def get_user_role(discord_user_id: str) -> tuple[int, str | None]:
    """Return (status, role). Role is None if the user is not registered."""
    discord_user_id = str(discord_user_id or "").strip()
    if not discord_user_id:
        return 200, None

    status, response = supabase.supabase_client_request(
        f"dim_users?discord_user_id=eq.{discord_user_id}&select=role",
        method="GET",
    )
    if status != 200:
        return status, None

    try:
        users = json.loads(response)
    except json.JSONDecodeError:
        return 502, None
    if not isinstance(users, list) or (users and not isinstance(users[0], dict)):
        return 502, None
    if not users:
        return 200, None

    return 200, users[0].get("role") or "user"


def get_user(discord_user_id: str) -> tuple[int, dict]:
    discord_user_id = str(discord_user_id or "").strip()
    if not discord_user_id:
        return 400, {"error": "Feld 'discord_user_id' ist erforderlich"}

    status, response = supabase.supabase_client_request(
        f"dim_users?discord_user_id=eq.{discord_user_id}",
        method="GET",
    )
    if status != 200:
        return status, {
            "error": f"Fehler beim Abrufen des Discord-Nutzers ({status}): {response}"
        }

    try:
        users = json.loads(response)
    except json.JSONDecodeError:
        return 502, {"error": "Ungültige Antwort beim Abrufen des Discord-Nutzers"}

    if not isinstance(users, list):
        return 502, {"error": "Ungültige Antwort beim Abrufen des Discord-Nutzers"}
    if not users:
        return 404, {"error": f"Discord-Nutzer mit ID '{discord_user_id}' nicht gefunden"}

    user = users[0]
    if not isinstance(user, dict):
        return 502, {"error": "Ungültige Antwort beim Abrufen des Discord-Nutzers"}

    return 200, {
        "discord_user_id": user.get("discord_user_id"),
        "discord_username": user.get("discord_username"),
    }
