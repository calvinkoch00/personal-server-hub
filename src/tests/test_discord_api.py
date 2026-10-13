import json
from unittest.mock import MagicMock
from unittest.mock import patch
from personal_server_hub.application.help import get_help_message
from personal_server_hub.adapters.discord.slash_commands import slash_command_response
import personal_server_hub.discord_api as discord_api


def test_slash_command_adapter_wraps_discord_message_data():
    data = {"content": "Done", "components": [{"type": 1, "components": []}]}

    assert slash_command_response(data) == {
        "statusCode": 200,
        "body": {"type": 4, "data": data},
    }


def test_discord_help_command_uses_application_help():
    response = discord_api.handle_interaction(
        {"type": 2, "data": {"name": "help"}}
    )

    assert response["statusCode"] == 200
    assert response["body"]["data"]["content"] == get_help_message()


def test_handle_interaction_ping():
    res = discord_api.handle_interaction({"type": 1})
    assert res["statusCode"] == 200
    assert res["body"]["type"] == 1


def test_handle_interaction_unsupported():
    res = discord_api.handle_interaction({"type": 99})
    assert res["statusCode"] == 400
    assert "Unsupported" in res["body"]["error"]


@patch("personal_server_hub.api.routers.servers.handle_start")
@patch("personal_server_hub.api.dependencies.get_user_role", return_value=(200, "user"))
def test_handle_interaction_server_subcommand_start(mock_get_role, mock_start):
    mock_start.return_value = (200, {"message": "Server wird gestartet..."})

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
    call_payload = mock_start.call_args[0][0]
    assert call_payload.get("name") == "skyblock"
    assert call_payload.get("duration") == "2h"


@patch("personal_server_hub.api.routers.servers.handle_servers")
@patch("personal_server_hub.api.dependencies.get_user_role", return_value=(200, "user"))
def test_handle_interaction_server_subcommand_status(mock_get_role, mock_handle_servers):
    mock_handle_servers.return_value = (200, {"servers": [{"display_name": "minecraft-test-2", "status": "online", "ip": "1.2.3.4"}]})

    payload = {
        "type": 2,
        "data": {
            "name": "server",
            "options": [
                {
                    "type": 1,
                    "name": "status"
                }
            ]
        },
        "member": {
            "user": {"id": "12345678", "username": "Calvin"}
        }
    }

    res = discord_api.handle_interaction(payload)
    assert res["statusCode"] == 200
    assert "minecraft-test-2" in res["body"]["data"]["content"]
    assert "online" in res["body"]["data"]["content"]
    assert "1.2.3.4" in res["body"]["data"]["content"]


@patch("personal_server_hub.api.routers.whitelist.add_whitelist")
@patch("personal_server_hub.api.dependencies.get_user_role", return_value=(200, "user"))
def test_handle_interaction_whitelist_subcommand(mock_get_role, mock_wl):
    mock_wl.return_value = (200, {"status": "Whitelist aktualisiert"})

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
    assert "Whitelist aktualisiert" in res["body"]["data"]["content"]
    mock_wl.assert_called_once_with(
        {
            "game": "minecraft",
            "server": None,
            "server_name": None,
            "server_slug": None,
            "username": "Notch",
            "discord_user_id": "12345678",
            "role": "server-admin"
        }
    )


@patch("personal_server_hub.api.routers.game_accounts.add_game_account")
@patch("personal_server_hub.api.dependencies.get_user_role", return_value=(200, "user"))
def test_addgameaccount_command_uses_shared_application_operation(mock_get_role, mock_add_game_account):
    mock_add_game_account.return_value = (
        200,
        {
            "status": "created",
            "game": "minecraft",
            "username": "Notch",
            "mojang_uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        },
    )
    payload = {
        "type": 2,
        "data": {
            "name": "addgameaccount",
            "options": [
                {"name": "game", "value": "minecraft"},
                {"name": "username", "value": "Notch"},
            ],
        },
        "member": {
            "user": {"id": "123456", "username": "Calvin"}
        },
    }

    response = discord_api.handle_interaction(payload)

    assert "created" in response["body"]["data"]["content"]
    mock_add_game_account.assert_called_once_with(
        {
            "discord_user_id": "123456",
            "discord_username": "Calvin",
            "game": "minecraft",
            "username": "Notch",
        }
    )


@patch("personal_server_hub.discord_api.urllib.request.urlopen")
@patch("personal_server_hub.discord_api.handle_interaction")
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
    assert progress_request.get_header("User-agent") == (
        "DiscordBot (https://github.com/calvinkoch00/personal-server-hub, 1.0)"
    )
    assert json.loads(progress_request.data) == {
        "content": "✅ Befehl empfangen – ich versuche ihn auszuführen…"
    }
    assert final_request.full_url == progress_request.full_url
    assert final_request.get_method() == "PATCH"
    assert final_request.get_header("User-agent") == progress_request.get_header("User-agent")
    assert json.loads(final_request.data) == {"content": "Server gestartet"}


@patch("personal_server_hub.discord_api.urllib.request.urlopen")
def test_execute_help_splits_content_within_discord_limit(mock_urlopen):
    response = MagicMock()
    response.__enter__.return_value = response
    mock_urlopen.return_value = response

    command_payload = {"type": 2, "data": {"name": "help"}}
    expected_content = discord_api.handle_interaction(command_payload)["body"]["data"]["content"]

    discord_api.execute_async_command(
        command_payload,
        token="interaction-token",
        app_id="123456789"
    )

    assert len(expected_content) > discord_api.DISCORD_MESSAGE_CONTENT_LIMIT
    assert mock_urlopen.call_count == 3
    progress_request = mock_urlopen.call_args_list[0].args[0]
    first_result_request = mock_urlopen.call_args_list[1].args[0]
    second_result_request = mock_urlopen.call_args_list[2].args[0]

    assert json.loads(progress_request.data)["content"].startswith("✅ Befehl empfangen")
    assert first_result_request.get_method() == "PATCH"
    assert second_result_request.get_method() == "POST"
    result_chunks = [
        json.loads(first_result_request.data)["content"],
        json.loads(second_result_request.data)["content"]
    ]
    assert all(len(chunk) <= discord_api.DISCORD_MESSAGE_CONTENT_LIMIT for chunk in result_chunks)
    assert "".join(result_chunks) == expected_content


def test_split_discord_content_prefers_paragraph_break():
    limit = discord_api.DISCORD_MESSAGE_CONTENT_LIMIT
    content = "a" * 1780 + "\n\n" + "b" * 180 + "\n" + "c" * 100

    chunks = discord_api.split_discord_content(content)

    assert chunks[0] == "a" * 1780 + "\n\n"
    assert "".join(chunks) == content
    assert all(len(chunk) <= limit for chunk in chunks)


def test_split_discord_content_prefers_line_break_over_whitespace():
    limit = discord_api.DISCORD_MESSAGE_CONTENT_LIMIT
    content = "a" * 1000 + "\n" + "b" * 500 + " " + "c" * 600

    chunks = discord_api.split_discord_content(content)

    assert chunks[0] == "a" * 1000 + "\n"
    assert "".join(chunks) == content
    assert all(len(chunk) <= limit for chunk in chunks)


def test_split_discord_content_falls_back_to_whitespace_then_hard_limit():
    limit = discord_api.DISCORD_MESSAGE_CONTENT_LIMIT
    content = "a" * 1000 + "\t" + "b" * 1500

    chunks = discord_api.split_discord_content(content)

    assert chunks[0] == "a" * 1000 + "\t"
    assert "".join(chunks) == content
    assert all(len(chunk) <= limit for chunk in chunks)

    unbroken_content = "x" * (limit + 10)
    unbroken_chunks = discord_api.split_discord_content(unbroken_content)
    assert unbroken_chunks == ["x" * limit, "x" * 10]


@patch("personal_server_hub.discord_api.urllib.request.urlopen")
@patch("personal_server_hub.discord_api.handle_interaction")
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