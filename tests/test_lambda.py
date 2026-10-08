import json
from unittest.mock import patch

import config
from lambda_function import lambda_handler


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
@patch("services.hetzner.create_server")
def test_start_endpoint_success(mock_create, auth_headers):
    mock_create.return_value = {
        "server_id": 123456,
        "name": "minecraft-default",
        "game": "minecraft",
        "server_name": "default",
        "ip": "1.2.3.4",
        "domain": "mc.calvinkoch.ch",
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
    assert "minecraft-default" in body.get("discord_summary", "")
    assert body["data"]["ip"] == "1.2.3.4"


# 3. Server List Test
@patch("services.supabase.supabase_client_request")
def test_list_servers_endpoint(mock_sb, auth_headers):
    mock_sb.return_value = (
        200,
        json.dumps([
            {
                "server_id": "uuid-1",
                "game": "minecraft",
                "server_name": "default",
                "display_name": "minecraft-default",
                "status": "offline"
            }
        ])
    )

    event = {
        "rawPath": "/servers",
        "headers": auth_headers,
        "body": None
    }
    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "servers" in body
    assert len(body["servers"]) == 1
    assert body["servers"][0]["server_name"] == "default"


# 4. Stop Server Test
@patch("services.supabase.supabase_client_request")
@patch("services.hetzner.delete_server")
@patch("services.hetzner.list_servers")
def test_stop_server_endpoint(mock_list, mock_delete, mock_sb, auth_headers):
    mock_list.return_value = [
        {
            "server_id": 98765,
            "name": "server-minecraft-default",
            "ip": "5.6.7.8"
        }
    ]
    mock_delete.return_value = {"action": "deleted"}
    mock_sb.return_value = (200, "[]")

    event = {
        "rawPath": "/stop",
        "headers": auth_headers,
        "body": json.dumps({"server_id": 98765})
    }
    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "Shutdown" in body["message"] or "gelöscht" in body["message"]
    assert body["target"]["server_id"] == 98765


# 5. Stage-1 Bootloader Generation Test
def test_stage1_bootloader_generation():
    script = config.get_stage1_bootloader(
        volume_id=107045799,
        game_port=25565,
        max_seconds=600,
        enable_logging="none"
    )

    assert script.startswith("#!/bin/bash")
    assert "set -euo pipefail" in script
    assert 'VOLUME_ID="107045799"' in script
    assert 'GAME_PORT="25565"' in script
    assert 'MAX_SECONDS="600"' in script
    assert 'ENABLE_LOGGING="none"' in script
    assert "$MOUNT_DIR/secrets.env" in script
    assert "hetzner/bootstrap.sh" in script
    assert "exec /opt/bootstrap/bootstrap.sh" in script


@patch("lambda_function.verify_discord_signature", return_value=True)
@patch("lambda_function.lambda_client.invoke")
def test_discord_command_is_deferred_and_queued(mock_invoke, _mock_verify, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "hetzner-server-controller")
    mock_invoke.return_value = {"StatusCode": 202}
    event = {
        "headers": {"x-signature-ed25519": "signature"},
        "body": json.dumps({
            "type": 2,
            "application_id": "1234567890",
            "token": "interaction-token",
            "data": {"name": "status"}
        })
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"type": 5}
    invocation = json.loads(mock_invoke.call_args.kwargs["Payload"])
    assert invocation["async_worker"] is True
    assert invocation["command_payload"]["data"]["name"] == "status"
    assert invocation["token"] == "interaction-token"
    assert invocation["app_id"] == "1234567890"


@patch("lambda_function.verify_discord_signature", return_value=True)
@patch("lambda_function.lambda_client.invoke")
def test_discord_button_is_deferred_as_message_update(mock_invoke, _mock_verify, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "hetzner-server-controller")
    mock_invoke.return_value = {"StatusCode": 202}
    event = {
        "headers": {"x-signature-ed25519": "signature"},
        "body": json.dumps({
            "type": 3,
            "application_id": "1234567890",
            "token": "interaction-token",
            "data": {"custom_id": "confirm_del:skyblock:123"}
        })
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"type": 6}


@patch("lambda_function.discord_api.execute_async_command")
def test_async_worker_executes_queued_interaction(mock_execute):
    event = {
        "async_worker": True,
        "command_payload": {"type": 2, "data": {"name": "status"}},
        "token": "interaction-token",
        "app_id": "1234567890"
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    mock_execute.assert_called_once_with(
        command_payload=event["command_payload"],
        token="interaction-token",
        app_id="1234567890"
    )