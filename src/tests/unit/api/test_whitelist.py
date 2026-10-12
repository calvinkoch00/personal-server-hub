from unittest.mock import patch
from fastapi.testclient import TestClient
from personal_server_hub.api.main import app

client = TestClient(app)


@patch("personal_server_hub.api.routers.whitelist.add_whitelist")
def test_whitelist_add_endpoint(mock_add):
    mock_add.return_value = (200, {"status": "added", "username": "Steve"})
    response = client.post("/whitelist/add", json={"username": "Steve", "server": "default"})
    assert response.status_code == 200
    assert response.json() == {"status": "added", "username": "Steve"}


@patch("personal_server_hub.api.routers.whitelist.remove_whitelist")
def test_whitelist_remove_endpoint(mock_remove):
    mock_remove.return_value = (200, {"status": "removed", "username": "Steve"})
    response = client.post("/whitelist/remove", json={"username": "Steve", "server": "default"})
    assert response.status_code == 200
    assert response.json() == {"status": "removed", "username": "Steve"}


@patch("personal_server_hub.api.routers.whitelist.list_whitelist")
def test_whitelist_list_endpoint(mock_list):
    mock_list.return_value = (200, {"server": "minecraft-default", "entries": []})
    response = client.post("/whitelist/list", json={"server": "default"})
    assert response.status_code == 200
    assert response.json() == {"server": "minecraft-default", "entries": []}
