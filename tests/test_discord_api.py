import json
from unittest.mock import patch
import discord_api


def test_handle_interaction_ping():
    res = discord_api.handle_interaction({"type": 1})
    assert res["statusCode"] == 200
    assert res["body"]["type"] == 1


def test_handle_interaction_unsupported():
    res = discord_api.handle_interaction({"type": 99})
    assert res["statusCode"] == 400
    assert "Unsupported" in res["body"]["error"]


@patch("commands.server.handle_start")
def test_handle_interaction_server_subcommand_start(mock_start):
    mock_start.return_value = "Server wird gestartet..."

    payload = {
        "type": 2,
        "data": {
            "name": "server",
            "options": [
                {
                    "type": 1,
                    "name": "start",
                    "options": [
                        {"name": "name", "value": "skyblock"},
                        {"name": "duration", "value": "2h"}
                    ]
                }
            ]
        },
        "member": {
            "user": {"id": "12345678", "username": "Calvin"}
        }
    }

    res = discord_api.handle_interaction(payload)
    assert res["statusCode"] == 200
    assert res["body"]["data"]["content"] == "Server wird gestartet..."
    assert mock_start.called
    call_options = mock_start.call_args[0][0]["options"]
    assert any(o["name"] == "name" and o["value"] == "skyblock" for o in call_options)


@patch("commands.accounts.handle_whitelist")
def test_handle_interaction_whitelist_subcommand(mock_wl):
    mock_wl.return_value = "Whitelist aktualisiert"

    payload = {
        "type": 2,
        "data": {
            "name": "whitelist",
            "options": [
                {
                    "type": 1,
                    "name": "add",
                    "options": [
                        {"name": "username", "value": "Notch"},
                        {"name": "role", "value": "server-admin"}
                    ]
                }
            ]
        },
        "member": {
            "user": {"id": "12345678", "username": "Calvin"}
        }
    }

    res = discord_api.handle_interaction(payload)
    assert res["statusCode"] == 200
    assert res["body"]["data"]["content"] == "Whitelist aktualisiert"
    mock_wl.assert_called_once_with(
        "add",
        {"username": "Notch", "role": "server-admin"},
        "12345678"
    )