from unittest.mock import patch

from fastapi.testclient import TestClient

from personal_server_hub.api.main import app

client = TestClient(app)


@patch(
    "personal_server_hub.api.routers.users.get_user",
    return_value=(
        200,
        {"discord_user_id": "123456", "discord_username": "Calvin"},
    ),
)
def test_get_user_endpoint_calls_application_operation(mock_get_user):
    response = client.get("/users/123456")

    assert response.status_code == 200
    assert response.json() == {
        "discord_user_id": "123456",
        "discord_username": "Calvin",
    }
    mock_get_user.assert_called_once_with("123456")


@patch(
    "personal_server_hub.api.routers.users.get_user",
    return_value=(404, {"error": "not found"}),
)
def test_get_user_endpoint_preserves_not_found_status(mock_get_user):
    response = client.get("/users/123456")

    assert response.status_code == 404
    assert response.json() == {"error": "not found"}


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
