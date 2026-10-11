from unittest.mock import patch

from fastapi.testclient import TestClient

from personal_server_hub.api.main import app

client = TestClient(app)


@patch(
    "personal_server_hub.api.routers.users.register_user",
    return_value=(
        200,
        {
            "status": "registered",
            "discord_user_id": "123456",
            "discord_username": "Calvin",
        },
    ),
)
def test_register_user_endpoint_calls_application_operation(mock_register_user):
    response = client.post(
        "/users/register",
        json={"discord_user_id": "123456", "discord_username": "Calvin"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "registered",
        "discord_user_id": "123456",
        "discord_username": "Calvin",
    }
    mock_register_user.assert_called_once_with(
        {"discord_user_id": "123456", "discord_username": "Calvin"}
    )


def test_register_user_endpoint_requires_discord_user_id():
    response = client.post("/users/register", json={"discord_username": "Calvin"})

    assert response.status_code == 422
