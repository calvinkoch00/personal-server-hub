import json

from personal_server_hub.application.users import get_user, register_user
from personal_server_hub.integrations import mojang, supabase


def add_game_account(payload: dict) -> tuple[int, dict]:
    discord_user_id = str(payload.get("discord_user_id") or "").strip()
    discord_username = str(payload.get("discord_username") or "Unknown").strip()
    game = str(payload.get("game") or "").strip().lower()
    raw_username = str(payload.get("username") or "").strip()

    if not discord_user_id or not game or not raw_username:
        return 400, {"error": "Felder 'discord_user_id', 'game' und 'username' sind erforderlich"}

    mojang_uuid = None
    username = raw_username

    if game == "minecraft":
        mojang_uuid, official_name = mojang.get_mojang_profile(raw_username)
        if not mojang_uuid:
            return 404, {"error": f"Minecraft-Account `{raw_username}` existiert nicht bei Mojang."}
        username = official_name

    status_user, response_user = get_user(discord_user_id)
    if status_user == 404:
        status_user, response_user = register_user(
            {
                "discord_user_id": discord_user_id,
                "discord_username": discord_username,
            }
        )
    if status_user != 200:
        return status_user, response_user

    endpoint_check = (
        f"dim_game_accounts?game=eq.{game}"
        f"&ingame_username=ilike.{username}&select=discord_user_id,mojang_uuid"
    )
    status_check, response_check = supabase.supabase_client_request(
        endpoint_check,
        method="GET",
    )
    if status_check != 200:
        return status_check, {
            "error": f"Fehler beim Prüfen des Ingame-Accounts ({status_check}): {response_check}"
        }

    existing_accounts = json.loads(response_check)
    if existing_accounts:
        owner_id = str(existing_accounts[0].get("discord_user_id"))
        if owner_id == discord_user_id:
            if mojang_uuid and not existing_accounts[0].get("mojang_uuid"):
                status_patch, response_patch = supabase.supabase_client_request(
                    (
                        f"dim_game_accounts?discord_user_id=eq.{discord_user_id}"
                        f"&game=eq.{game}&ingame_username=ilike.{username}"
                    ),
                    method="PATCH",
                    data={"mojang_uuid": mojang_uuid},
                )
                if status_patch not in [200, 204]:
                    return status_patch, {
                        "error": f"Fehler beim Aktualisieren des Ingame-Accounts ({status_patch}): {response_patch}"
                    }
            return 200, {
                "status": "already_linked_self",
                "game": game,
                "username": username,
                "mojang_uuid": mojang_uuid,
            }
        return 403, {"status": "forbidden", "game": game, "username": username}

    account_payload = {
        "discord_user_id": discord_user_id,
        "game": game,
        "ingame_username": username,
        "mojang_uuid": mojang_uuid,
    }
    status_account, response_account = supabase.supabase_client_request(
        "dim_game_accounts",
        method="POST",
        data=account_payload,
        headers_extra={"Prefer": "return=representation"},
    )
    if status_account in [200, 201]:
        return 200, {
            "status": "created",
            "game": game,
            "username": username,
            "mojang_uuid": mojang_uuid,
        }
    return status_account, {
        "error": f"Fehler beim Verknüpfen ({status_account}): {response_account}"
    }
