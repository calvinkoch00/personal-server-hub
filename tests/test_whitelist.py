import json
from unittest.mock import patch
import rest_api


@patch("services.hetzner.list_servers")
@patch("services.supabase.supabase_client_request")
def test_handle_whitelist_add_with_hetzner_live_sync(mock_sb, mock_hetzner_list):
    # Hetzner bestätigt: VM läuft tatsächlich
    mock_hetzner_list.return_value = [
        {"name": "server-minecraft-default", "ip": "1.2.3.4", "status": "running"}
    ]

    mock_sb.side_effect = [
        # 1. dim_servers Lookup
        (200, json.dumps([{
            "server_id": "srv-100",
            "server_name": "default",
            "display_name": "minecraft-default",
            "full_name": "server-minecraft-default",
            "created_by": "admin-id",
            "whitelist_policy": "admin_only",
            "status": "offline"
        }])),
        # 2. caller role
        (200, json.dumps([{"role": "superadmin"}])),
        # 3. dim_game_accounts
        (200, json.dumps([{
            "id": "acc-100",
            "discord_user_id": "player-id",
            "ingame_username": "Steve"
        }])),
        # 4. map_server_whitelist POST
        (201, json.dumps([{"status": "ok"}])),
        # 5. Status-Korrektur in dim_servers auf 'online'
        (200, '{"status": "updated"}')
    ]

    with patch("services.agent.add_remote_whitelist") as mock_agent_add:
        mock_agent_add.return_value = {"status": "ok"}

        status, body = rest_api.handle_whitelist_add({
            "server_name": "default",
            "username": "Steve",
            "discord_user_id": "admin-id",
            "role": "player"
        })

        assert status == 200
        assert body["status"] == "added"
        assert body["live_synced"] is True
        assert mock_hetzner_list.called
        assert mock_agent_add.called


@patch("services.hetzner.list_servers")
@patch("services.supabase.supabase_client_request")
def test_handle_whitelist_add_forbidden_other_user(mock_sb, mock_hetzner_list):
    mock_hetzner_list.return_value = []
    mock_sb.side_effect = [
        # dim_servers: policy all, aber anderer User als Caller
        (200, json.dumps([{
            "server_id": "srv-100",
            "server_name": "skyblock",
            "display_name": "minecraft-skyblock",
            "full_name": "server-minecraft-skyblock",
            "created_by": "owner-id",
            "whitelist_policy": "all",
            "status": "offline"
        }])),
        # Caller ist einfacher User
        (200, json.dumps([{"role": "user"}])),
        # Target Account gehört jemand anderem
        (200, json.dumps([{
            "id": "acc-200",
            "discord_user_id": "different-user-id",
            "ingame_username": "Alex"
        }]))
    ]

    status, body = rest_api.handle_whitelist_add({
        "server_name": "skyblock",
        "username": "Alex",
        "discord_user_id": "stranger-id",
        "role": "player"
    })

    assert status == 403
    assert "nur selbst hinzufügen" in body["error"]