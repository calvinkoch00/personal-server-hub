import json
from unittest.mock import MagicMock
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


@patch("discord_api.urllib.request.urlopen")
@patch("discord_api.handle_interaction")
def test_execute_async_command_posts_followup(mock_interaction, mock_urlopen):
    mock_interaction.return_value = {
        "statusCode": 200,
        "body": {"type": 4, "data": {"content": "Server gestartet"}}
    }
    response = MagicMock()
    response.__enter__.return_value = response
    mock_urlopen.return_value = response

    discord_api.execute_async_command(
        {"type": 2, "data": {"name": "status"}},
        token="interaction-token",
        app_id="123456789"
    )

    assert mock_urlopen.call_count == 2
    progress_request = mock_urlopen.call_args_list[0].args[0]
    final_request = mock_urlopen.call_args_list[1].args[0]
    assert progress_request.full_url == (
        "https://discord.com/api/v10/webhooks/123456789/"
        "interaction-token/messages/@original"
    )
    assert progress_request.get_method() == "PATCH"
    assert json.loads(progress_request.data) == {
        "content": "✅ Befehl empfangen – ich versuche ihn auszuführen…"
    }
    assert final_request.full_url == progress_request.full_url
    assert final_request.get_method() == "PATCH"
    assert json.loads(final_request.data) == {"content": "Server gestartet"}


@patch("discord_api.urllib.request.urlopen")
@patch("discord_api.handle_interaction")
def test_execute_async_component_updates_original_message(mock_interaction, mock_urlopen):
    mock_interaction.return_value = {
        "statusCode": 200,
        "body": {"type": 7, "data": {"content": "Löschung abgebrochen", "components": []}}
    }
    response = MagicMock()
    response.__enter__.return_value = response
    mock_urlopen.return_value = response

    discord_api.execute_async_command(
        {"type": 3, "data": {"custom_id": "cancel_del:123"}},
        token="interaction-token",
        app_id="123456789"
    )

    request = mock_urlopen.call_args.args[0]
    assert request.full_url.endswith("/messages/@original")
    assert request.get_method() == "PATCH"