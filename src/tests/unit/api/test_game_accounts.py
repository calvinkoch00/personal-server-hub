from unittest.mock import patch

from fastapi.testclient import TestClient

from personal_server_hub.api.main import app

client = TestClient(app)


@patch("personal_server_hub.api.routers.game_accounts.add_game_account")
def test_create_game_account_endpoint_calls_application_operation(mock_add_game_account):
    mock_add_game_account.return_value = (
        200,
        {"status": "created", "game": "minecraft", "username": "Notch"},
    )

    response = client.post(
        "/game-accounts",
        json={
            "discord_user_id": "123456",
            "discord_username": "calvin",
            "game": "MINECRAFT",
            "username": "Notch",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "created",
        "game": "minecraft",
        "username": "Notch",
    }
    mock_add_game_account.assert_called_once_with(
        {
            "discord_user_id": "123456",
            "discord_username": "calvin",
            "game": "minecraft",
            "username": "Notch",
        }
    )


def test_create_game_account_endpoint_validates_required_fields():
    response = client.post(
        "/game-accounts",
        json={"discord_user_id": "123456", "discord_username": "calvin"},
    )

    assert response.status_code == 422
