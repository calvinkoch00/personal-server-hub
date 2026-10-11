import json

from scripts.register_discord_commands import (
    build_command_cache,
    load_credentials,
    main,
    register_commands,
)


def test_load_credentials_prefers_environment_and_fills_from_env_file(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        'DISCORD_APPLICATION_ID="123456"\nDISCORD_BOT_TOKEN=local-token\n',
        encoding="utf-8",
    )

    assert load_credentials(
        {"DISCORD_APPLICATION_ID": "789012"},
        env_path,
    ) == ("789012", "local-token")


def test_build_command_cache_includes_nested_subcommand_arguments():
    commands = [
        {
            "name": "server",
            "description": "Manage servers",
            "options": [
                {
                    "type": 1,
                    "name": "start",
                    "description": "Start a server",
                    "options": [
                        {"type": 3, "name": "name", "required": True},
                        {"type": 3, "name": "duration", "required": False},
                    ],
                }
            ],
        }
    ]

    assert build_command_cache(commands) == (
        "📖 **Verfügbare Server-Befehle:**\n\n"
        "• `/server start <name> [duration]` — Start a server\n"
    )


def test_register_commands_sends_bot_auth_and_returns_response():
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'[{"name":"help","description":"Help"}]'

    def fake_opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    registered = register_commands(
        "123456",
        "never-log-this-token",
        [{"name": "help"}],
        fake_opener,
    )

    assert registered == [{"name": "help", "description": "Help"}]
    assert captured["request"].full_url.endswith("/applications/123456/commands")
    assert captured["request"].get_header("Authorization") == "Bot never-log-this-token"
    assert captured["timeout"] == 30
    assert json.loads(captured["request"].data) == [{"name": "help"}]


def test_main_registers_commands_and_writes_cache(tmp_path):
    command_path = tmp_path / "commands.json"
    command_path.write_text(
        json.dumps([{"name": "help", "description": "Show help"}]),
        encoding="utf-8",
    )
    cache_path = tmp_path / "commands_cache.txt"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'[{"name":"help","description":"Show help"}]'

    assert main(
        environment={
            "DISCORD_APPLICATION_ID": "123456",
            "DISCORD_BOT_TOKEN": "test-token",
        },
        commands_path=command_path,
        cache_path=cache_path,
        opener=lambda _request, timeout: FakeResponse(),
    ) == 0
    assert "`/help` — Show help" in cache_path.read_text(encoding="utf-8")
