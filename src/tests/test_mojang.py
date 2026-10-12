import json
from unittest.mock import patch, MagicMock
from personal_server_hub.services import mojang
from personal_server_hub.application.game_accounts import add_game_account

def test_format_uuid():
    raw = "069a79f444e94726a5befca90e38aaf5"
    expected = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
    assert mojang.format_uuid(raw) == expected

@patch("urllib.request.urlopen")
def test_get_mojang_profile_success(mock_urlopen):
    profile_data = json.dumps({
        "id": "069a79f444e94726a5befca90e38aaf5",
        "name": "Notch"
    }).encode("utf-8")

    resp_mock = MagicMock()
    resp_mock.status = 200
    resp_mock.read.return_value = profile_data
    resp_mock.__enter__.return_value = resp_mock
    mock_urlopen.return_value = resp_mock

    uuid, name = mojang.get_mojang_profile("notch")
    assert uuid == "069a79f4-44e9-4726-a5be-fca90e38aaf5"
    assert name == "Notch"

@patch("personal_server_hub.services.mojang.get_mojang_profile")
@patch("personal_server_hub.services.supabase.supabase_client_request")
def test_handle_addgameaccount_minecraft_success(mock_sb, mock_mojang):
    mock_mojang.return_value = ("069a79f4-44e9-4726-a5be-fca90e38aaf5", "Notch")
    mock_sb.side_effect = [
        (200, "[]"),                # dim_users lookup
        (201, '{"status": "ok"}'), # dim_users registration
        (200, "[]"),                # existing check
        (201, json.dumps([{"id": "uuid-123"}])) # insert dim_game_accounts
    ]

    status, body = add_game_account({
        "discord_user_id": "123456",
        "discord_username": "calvin",
        "game": "minecraft",
        "username": "notch"
    })

    assert status == 200
    assert body["status"] == "created"
    assert body["username"] == "Notch"
    assert body["mojang_uuid"] == "069a79f4-44e9-4726-a5be-fca90e38aaf5"

@patch("personal_server_hub.services.mojang.get_mojang_profile")
def test_handle_addgameaccount_minecraft_not_found(mock_mojang):
    mock_mojang.return_value = (None, None)

    status, body = add_game_account({
        "discord_user_id": "123456",
        "discord_username": "calvin",
        "game": "minecraft",
        "username": "invalid_user_999999"
    })

    assert status == 404
    assert "existiert nicht bei Mojang" in body["error"]


@patch("personal_server_hub.services.mojang.get_mojang_profile")
@patch("personal_server_hub.services.supabase.supabase_client_request")
def test_handle_addgameaccount_stops_when_user_registration_fails(mock_sb, mock_mojang):
    mock_mojang.return_value = ("069a79f4-44e9-4726-a5be-fca90e38aaf5", "Notch")
    mock_sb.side_effect = [
        (200, "[]"),
        (401, "Invalid Supabase key"),
    ]

    status, body = add_game_account({
        "discord_user_id": "123456",
        "discord_username": "calvin",
        "game": "minecraft",
        "username": "notch",
    })

    assert status == 401
    assert "Registrieren des Discord-Nutzers" in body["error"]
    assert mock_sb.call_count == 2