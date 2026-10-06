import os
import sys
import json
import pytest
from unittest.mock import patch

# aws_lambda in den Python-Pfad aufnehmen
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "aws_lambda")))

import config
from lambda_function import lambda_handler


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    """Setzt alle Dummy-Variablen isoliert für den Test-Runner."""
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("HETZNER_API_TOKEN", "mock-token")
    monkeypatch.setenv("VOLUME_ID", "107045799")
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", "mock-discord-key")
    monkeypatch.setenv("DISCORD_STATUS_WEBHOOK_URL", "https://discord.com/api/webhooks/mock")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-sb-key")
    monkeypatch.setenv("GITHUB_REPO_RAW", "https://raw.githubusercontent.com/calvinkoch/personal-server-hub/main")
    monkeypatch.setenv("GITHUB_TOKEN", "test-gh-token")


# ================= 1. Authentifizierung & Basis-Routen =================

def test_unauthorized_request():
    event = {
        "headers": {"x-auth-token": "falscher-token"},
        "rawPath": "/start"
    }
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 401


# ================= 2. Server-Endpoints (Start / List / Stop) =================

@patch("lambda_function.hetzner.create_server")
def test_start_endpoint_success(mock_create):
    mock_create.return_value = {
        "server_id": 999,
        "name": "minecraft-ondemand",
        "status": "running",
        "ip": "1.2.3.4",
        "domain": "mc.calvinkoch.ch",
        "game": "minecraft",
        "server_type": "cpx32",
        "lifetime_seconds": 300,
        "lifetime_readable": "5 Minute(n)"
    }

    event = {
        "headers": {"x-auth-token": "test-secret"},
        "rawPath": "/start",
        "body": json.dumps({"server_type": "cpx32", "game": "minecraft"})
    }

    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["data"]["server_id"] == 999
    assert "MINECRAFT gestartet!" in body["discord_summary"]


@patch("lambda_function.hetzner.list_servers")
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


@patch("lambda_function.hetzner.delete_server")
@patch("lambda_function.hetzner.get_server_status")
@patch("lambda_function.hetzner.trigger_server_graceful_stop")
def test_stop_server_endpoint(mock_stop, mock_status, mock_delete):
    mock_status.return_value = {
        "server_id": "12345",
        "status": "running",
        "ip": "1.2.3.4"
    }
    mock_stop.return_value = {"status": "graceful_triggered"}
    mock_delete.return_value = {"message": "Server wird gelöscht", "action": {}}

    event = {
        "headers": {"x-auth-token": "test-secret"},
        "rawPath": "/stop",
        "body": json.dumps({"server_id": "12345", "server_ip": "1.2.3.4"})
    }

    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200, f"Fehler in Lambda: {resp.get('body')}"
    body = json.loads(resp["body"])
    assert "status" in body["data"] or "message" in body["data"]

# ================= 3. Bootloader & Konfigurations-Tests =================

def test_stage1_bootloader_generation():
    script = config.get_stage1_bootloader(
        volume_id=107045799,
        game_port=25565,
        max_seconds=600
    )
    assert "#!/bin/bash" in script
    assert 'VOLUME_ID="107045799"' in script
    assert 'GAME_PORT="25565"' in script
    assert 'MAX_SECONDS="600"' in script
    assert 'SUPABASE_URL="https://test.supabase.co"' in script
    assert 'SUPABASE_KEY="test-sb-key"' in script
    assert "hetzner/bootstrap.sh" in script
    assert "$MOUNT_DIR/secrets.env" in script

def test_parse_start_args():
    """Prüft die Umrechnung von Zeiten (5m, 2h, 1d) und Defaults."""
    game, seconds, readable = config.parse_start_args(None)
    assert game == "minecraft"
    assert seconds == 300
    assert readable == "5 Minute(n)"

    game, seconds, readable = config.parse_start_args("2h")
    assert game == "minecraft"
    assert seconds == 7200
    assert readable == "2 Stunde(n)"

    game, seconds, readable = config.parse_start_args("minecraft 45m")
    assert game == "minecraft"
    assert seconds == 2700
    assert readable == "45 Minute(n)"