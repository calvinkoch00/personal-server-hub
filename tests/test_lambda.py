import json
import pytest
from unittest.mock import patch
import sys
import os

# Pfad zu aws_lambda explizit in den Python-Suchpfad aufnehmen
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "aws_lambda")))

# Jetzt kann lambda_function seine Nachbardateien (auth, hetzner, config) direkt finden
from lambda_function import lambda_handler

@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("HETZNER_API_TOKEN", "mock-token")
    monkeypatch.setenv("VOLUME_ID", "123456")

def test_unauthorized_request():
    event = {"headers": {"x-auth-token": "falscher-token"}, "rawPath": "/start"}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 401

@patch("hetzner.create_server")
def test_start_endpoint_success(mock_create):
    mock_create.return_value = {
        "server_id": 999,
        "status": "running",
        "ip": "1.2.3.4",
        "server_type": "cpx32",
        "auto_kill_after_seconds": 20
    }

    event = {
        "headers": {"x-auth-token": "test-secret"},
        "rawPath": "/start",
        "body": json.dumps({"server_type": "cpx32"})
    }

    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["data"]["server_id"] == 999
    assert "discord_summary" in body

@patch("hetzner.list_servers")
def test_list_servers_endpoint(mock_list):
    mock_list.return_value = [
        {
            "server_id": 12345,
            "name": "minecraft-ondemand",
            "status": "running",
            "ip": "1.2.3.4",
            "server_type": "cpx32",
            "created": "2026-10-05T18:00:00Z"
        }
    ]

    event = {
        "headers": {"x-auth-token": "test-secret"},
        "rawPath": "/servers"
    }

    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["data"]) == 1
    assert body["data"][0]["server_id"] == 12345
    assert "🟢 Aktuell laufen 1 Server." in body["discord_summary"]