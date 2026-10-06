import json
from services.supabase import supabase_client_request, resolve_discord_user_id, is_user_admin


def handle_addgameaccount(body: dict, data: dict) -> str:
    caller_data = body.get("member", {}).get("user") or body.get("user", {})
    discord_user_id = str(caller_data.get("id"))
    discord_username = str(caller_data.get("username", "Unknown"))

    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])}
    game = str(options.get("game", "")).strip().lower()
    username = str(options.get("username", "")).strip()

    if not game or not username:
        return "❌ Bitte gib Spiel und Ingame-Namen an: `/addgameaccount <game> <username>`"

    try:
        # 1. Sicherstellen, dass User in dim_users existiert
        supabase_client_request(
            "dim_users",
            method="POST",
            data={"discord_user_id": discord_user_id, "discord_username": discord_username},
            headers_extra={"Prefer": "resolution=merge-duplicates"}
        )

        # 2. Prüfen, ob der Ingame-Account bereits verknüpft ist
        endpoint_check = f"dim_game_accounts?game=eq.{game}&ingame_username=ilike.{username}&select=discord_user_id"
        status_check, resp_check = supabase_client_request(endpoint_check, method="GET")
        existing_accounts = json.loads(resp_check) if status_check == 200 else []

        if existing_accounts:
            owner_id = str(existing_accounts[0].get("discord_user_id"))
            if owner_id == discord_user_id:
                return f"ℹ️ Der Ingame-Account `{username}` ({game.upper()}) ist bereits mit deinem Profil verknüpft."
            return f"⛔ **Zugriff verweigert:** Der Ingame-Account `{username}` ({game.upper()}) ist bereits mit einem anderen Discord-Account verknüpft!"

        # 3. Neu anlegen
        status_a, resp_a = supabase_client_request(
            "dim_game_accounts",
            method="POST",
            data={
                "discord_user_id": discord_user_id,
                "game": game,
                "ingame_username": username
            },
            headers_extra={"Prefer": "return=representation"}
        )
        if status_a in [200, 201]:
            return f"✅ Ingame-Account `{username}` ({game.upper()}) wurde erfolgreich mit deinem Discord-Profil verknüpft!"
        return f"⚠ Fehler beim Verknüpfen ({status_a}): {resp_a}"
    except Exception as e:
        return f"❌ Datenbankfehler: {e}"