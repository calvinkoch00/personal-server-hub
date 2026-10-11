from personal_server_hub.services import supabase


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
