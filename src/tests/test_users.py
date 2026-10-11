from unittest.mock import patch

from personal_server_hub.application.users import get_user, register_user


@patch("personal_server_hub.application.users.supabase.supabase_client_request")
def test_register_user_upserts_discord_user(mock_request):
    mock_request.return_value = (201, '[{"discord_user_id":"123456"}]')

    status, response = register_user({
        "discord_user_id": "123456",
        "discord_username": "Calvin",
    })

    assert status == 200
    assert response == {
        "status": "registered",
        "discord_user_id": "123456",
        "discord_username": "Calvin",
    }
    mock_request.assert_called_once_with(
        "dim_users",
        method="POST",
        data={"discord_user_id": "123456", "discord_username": "Calvin"},
        headers_extra={"Prefer": "resolution=merge-duplicates"},
    )


@patch("personal_server_hub.application.users.supabase.supabase_client_request")
def test_register_user_surfaces_database_error(mock_request):
    mock_request.return_value = (401, "Invalid key")

    status, response = register_user({
        "discord_user_id": "123456",
        "discord_username": "Calvin",
    })

    assert status == 401
    assert "Invalid key" in response["error"]


def test_register_user_requires_discord_user_id():
    status, response = register_user({"discord_username": "Calvin"})

    assert status == 400
    assert "discord_user_id" in response["error"]


@patch("personal_server_hub.application.users.supabase.supabase_client_request")
def test_get_user_returns_user_from_supabase(mock_request):
    mock_request.return_value = (
        200,
        '[{"discord_user_id":"123456","discord_username":"Calvin"}]',
    )

    status, response = get_user("123456")

    assert status == 200
    assert response == {
        "discord_user_id": "123456",
        "discord_username": "Calvin",
    }
    mock_request.assert_called_once_with(
        "dim_users?discord_user_id=eq.123456",
        method="GET",
    )


@patch("personal_server_hub.application.users.supabase.supabase_client_request")
def test_get_user_returns_not_found_for_empty_result(mock_request):
    mock_request.return_value = (200, "[]")

    status, response = get_user("123456")

    assert status == 404
    assert "123456" in response["error"]


@patch("personal_server_hub.application.users.supabase.supabase_client_request")
def test_get_user_surfaces_supabase_error(mock_request):
    mock_request.return_value = (503, "Unavailable")

    status, response = get_user("123456")

    assert status == 503
    assert "Unavailable" in response["error"]
