import json
from unittest.mock import MagicMock, patch

import config
import hetzner
from lambda_function import lambda_handler
from config import parse_start_args


# 1. Security Gatekeeper Test
def test_unauthorized_request():
    event = {
        "rawPath": "/start",
        "headers": {"x-auth-token": "invalid-token"},
        "body": json.dumps({"game": "minecraft"})
    }
    response = lambda_handler(event, None)
    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert "error" in body or "Unauthorized" in str(body)


# 2. Server Start Test
@patch("hetzner.create_server")
def test_start_endpoint_success(mock_create, auth_headers):
    # Mocking: create_server Rückgabewert mit allen Pflichtfeldern
    mock_create.return_value = {
        "server_id": 123456,
        "name": "minecraft-ondemand",
        "game": "minecraft",
        "ip": "1.2.3.4",
        "lifetime_readable": "2 Stunde(n)",
        "server_type": "cpx32",
        "status": "initializing"
    }

    event = {
        "rawPath": "/start",
        "headers": auth_headers,
        "body": json.dumps({"game": "minecraft", "duration": "2h"})
    }
    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body.get("message") == "Server gestartet"
    assert "MINECRAFT" in body.get("discord_summary", "")
    assert body["data"]["ip"] == "1.2.3.4"


# 3. Server List Test
@patch("hetzner.list_servers")
def test_list_servers_endpoint(mock_list, auth_headers):
    mock_list.return_value = [
        {
            "server_id": 98765,
            "name": "minecraft-ondemand",
            "status": "running",
            "ip": "5.6.7.8"
        }
    ]

    event = {
        "rawPath": "/servers",
        "headers": auth_headers,
        "body": None
    }
    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert isinstance(body.get("data"), list)
    assert len(body["data"]) == 1
    assert body["data"][0]["ip"] == "5.6.7.8"


# 4. Stop Server Test (über delete_server)
@patch("hetzner.delete_server")
@patch("hetzner.list_servers")
def test_stop_server_endpoint(mock_list, mock_delete, auth_headers):
    mock_list.return_value = [
        {
            "server_id": 98765,
            "name": "minecraft-ondemand",
            "ip": "5.6.7.8"
        }
    ]
    mock_delete.return_value = {"status": "deleted"}

    event = {
        "rawPath": "/stop",
        "headers": auth_headers,
        "body": json.dumps({"game": "minecraft"})
    }
    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["data"]["status"] == "deleted"
    mock_delete.assert_called_once_with("98765")


# 5. Stage-1 Bootloader Generation Test
def test_stage1_bootloader_generation():
    script = config.get_stage1_bootloader(
        volume_id=107045799,
        game_port=25565,
        max_seconds=600
    )

    assert script.startswith("#!/bin/bash")
    assert "set -euo pipefail" in script
    assert 'VOLUME_ID="107045799"' in script
    assert 'GAME_PORT="25565"' in script
    assert 'MAX_SECONDS="600"' in script
    assert 'SUPABASE_URL="https://test.supabase.co"' in script
    assert 'SUPABASE_KEY="test-sb-key"' in script
    assert "$MOUNT_DIR/secrets.env" in script
    assert "raw.githubusercontent.com/calvinkoch00/personal-server-hub/main" in script
    assert "hetzner/bootstrap.sh" in script
    assert "exec /opt/bootstrap/bootstrap.sh" in script


# 6. Flexible Zeiteingaben Test
def test_parse_start_args():
    _, secs_none, _ = parse_start_args(None)
    assert secs_none == 300

    _, secs_2h, label_2h = parse_start_args("2h")
    assert secs_2h == 7200
    assert "2" in label_2h

    _, secs_comb, label_comb = parse_start_args("minecraft 45m")
    assert secs_comb == 2700
    assert "45" in label_comb