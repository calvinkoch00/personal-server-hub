import json
import urllib.request
from unittest.mock import patch, MagicMock

from scripts.sync_discord_commands import (
    extract_command_names_from_yaml,
    load_credentials,
    main,
)

def test_load_credentials_prefers_environment_and_fills_from_env_file(monkeypatch, tmp_path):
    # Mock BASE_DIR
    monkeypatch.setattr("scripts.sync_discord_commands.BASE_DIR", tmp_path / "base")
    (tmp_path / "base").mkdir(parents=True, exist_ok=True)

    # Erstelle eine temporäre .env-Datei im Parent-Verzeichnis
    env_path = tmp_path / ".env"
    env_path.write_text(
        'DISCORD_APPLICATION_ID="123456"\nDISCORD_BOT_TOKEN=local-token\n',
        encoding="utf-8",
    )

    # Setze eine Variable im System-Environment (sollte Vorrang haben)
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "789012")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    assert load_credentials() == ("789012", "local-token")


def test_extract_command_names_from_yaml():
    commands = [
        {
            "name": "server",
            "options": [
                {"type": 1, "name": "start"},
                {"type": 1, "name": "stop"},
            ],
        },
        {
            "name": "status"
        },
    ]

    names = extract_command_names_from_yaml(commands)
    assert names == {"server start", "server stop", "status"}


@patch("scripts.sync_discord_commands.urllib.request.urlopen")
def test_main_syncs_commands_to_discord_and_checks_registry(mock_urlopen, monkeypatch, tmp_path, capsys):
    # Mock die YAML-Datei
    yaml_path = tmp_path / "discord_responses.yaml"
    yaml_path.write_text("""
discord_commands:
  - name: "help"
    description: "Show help"
""", encoding="utf-8")
    monkeypatch.setattr("scripts.sync_discord_commands.YAML_PATH", yaml_path)

    # Mock Credentials
    monkeypatch.setattr("scripts.sync_discord_commands.load_credentials", lambda: ("123456", "test-token"))
    
    # Mock die FastAPI Registry (sollte mit dem YAML übereinstimmen)
    monkeypatch.setattr("scripts.sync_discord_commands.DISCORD_COMMANDS_REGISTRY", {"help"})

    # Simuliere eine erfolgreiche Discord-API-Antwort
    response_mock = MagicMock()
    response_mock.__enter__.return_value = response_mock
    response_mock.read.return_value = b'[]'
    mock_urlopen.return_value = response_mock

    # Main ausführen
    main()

    # Request prüfen
    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args.args[0]
    
    assert req.full_url.endswith("/applications/123456/commands")
    assert req.get_header("Authorization") == "Bot test-token"
    
    # Prüfe den gesendeten JSON-Payload
    payload = json.loads(req.data)
    assert len(payload) == 1
    assert payload[0]["name"] == "help"
    assert payload[0]["description"] == "Show help"
    
    # Terminalausgabe prüfen
    out, _ = capsys.readouterr()
    assert "1 Commands aus YAML erfolgreich bei Discord registriert!" in out


@patch("scripts.sync_discord_commands.urllib.request.urlopen")
def test_main_warns_on_registry_mismatch(mock_urlopen, monkeypatch, tmp_path, capsys):
    # Mock die YAML-Datei
    yaml_path = tmp_path / "discord_responses.yaml"
    yaml_path.write_text("""
discord_commands:
  - name: "server"
    options:
      - type: 1
        name: "start"
""", encoding="utf-8")
    monkeypatch.setattr("scripts.sync_discord_commands.YAML_PATH", yaml_path)
    monkeypatch.setattr("scripts.sync_discord_commands.load_credentials", lambda: ("123456", "test-token"))
    
    # Absichtlicher Mismatch: "server stop" ist im Code, "server start" im YAML
    monkeypatch.setattr("scripts.sync_discord_commands.DISCORD_COMMANDS_REGISTRY", {"server stop"})

    response_mock = MagicMock()
    response_mock.__enter__.return_value = response_mock
    response_mock.read.return_value = b'[]'
    mock_urlopen.return_value = response_mock

    main()

    out, _ = capsys.readouterr()
    assert "Im YAML definiert, aber kein @discord_command in FastAPI: {'server start'}" in out
    assert "In FastAPI dekoriert, aber fehlt im YAML: {'server stop'}" in out