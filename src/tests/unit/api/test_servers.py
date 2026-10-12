from unittest.mock import patch
from fastapi.testclient import TestClient
from personal_server_hub.api.main import app

client = TestClient(app)


@patch("personal_server_hub.api.routers.servers.handle_start")
def test_server_start_endpoint(mock_start):
    mock_start.return_value = (200, {"message": "Server gestartet"})
    response = client.post("/server/start", json={"server": "default"})
    assert response.status_code == 200
    assert response.json() == {"message": "Server gestartet"}


@patch("personal_server_hub.api.routers.servers.handle_stop")
def test_server_stop_endpoint(mock_stop):
    mock_stop.return_value = (200, {"message": "Shutdown eingeleitet"})
    response = client.post("/server/stop", json={})
    assert response.status_code == 200
    assert response.json() == {"message": "Shutdown eingeleitet"}


@patch("personal_server_hub.api.routers.servers.handle_server_create")
def test_server_create_endpoint(mock_create):
    mock_create.return_value = (201, {"message": "Server erstellt"})
    response = client.post("/server/create", json={"server": "skyblock"})
    assert response.status_code == 201
    assert response.json() == {"message": "Server erstellt"}


@patch("personal_server_hub.api.routers.servers.handle_server_delete")
def test_server_delete_endpoint(mock_delete):
    mock_delete.return_value = (200, {"message": "Server gelöscht"})
    response = client.post("/server/delete", json={"server": "skyblock"})
    assert response.status_code == 200
    assert response.json() == {"message": "Server gelöscht"}


@patch("personal_server_hub.api.routers.servers.handle_servers")
def test_servers_list_endpoint(mock_list):
    mock_list.return_value = (200, {"servers": []})
    response = client.get("/servers")
    assert response.status_code == 200
    assert response.json() == {"servers": []}


def test_server_create_validation_invalid_slug():
    response = client.post("/server/create", json={"server": "INVALID SLUG!"})
    assert response.status_code == 422


@patch("personal_server_hub.api.routers.servers.handle_log")
def test_server_log_endpoint(mock_log):
    mock_log.return_value = (200, {"mode": "game"})
    response = client.post("/log", json={"mode": "game", "server": "default"})
    assert response.status_code == 200
    assert response.json() == {"mode": "game"}


@patch("personal_server_hub.api.routers.servers.handle_server_reload_files")
def test_server_reload_files_endpoint(mock_reload):
    mock_reload.return_value = (200, {"message": "Files reloaded"})
    response = client.post("/server/reload-files", json={"server": "default"})
    assert response.status_code == 200
    assert response.json() == {"message": "Files reloaded"}

