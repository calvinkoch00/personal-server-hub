import os
import pytest

# 1. Dummy-Umgebungsvariablen für die gesamte Test-Laufzeit setzen
os.environ["AUTH_SECRET"] = "test-auth-secret"
os.environ["HETZNER_API_TOKEN"] = "test-hetzner-token"
os.environ["DISCORD_STATUS_WEBHOOK_URL"] = "https://discord.com/api/webhooks/test"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = "test-sb-key"
os.environ["GITHUB_REPO_RAW"] = "https://raw.githubusercontent.com/calvinkoch00/personal-server-hub/main"
os.environ["VOLUME_ID"] = "107045799"
os.environ["LOCATION"] = "nbg1"


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Stellt sicher, dass Umgebungsvariablen für jeden Test sauber isoliert bleiben."""
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("HETZNER_API_TOKEN", "test-hetzner-token")
    monkeypatch.setenv("DISCORD_STATUS_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-sb-key")
    monkeypatch.setenv("GITHUB_REPO_RAW", "https://raw.githubusercontent.com/calvinkoch00/personal-server-hub/main")
    monkeypatch.setenv("VOLUME_ID", "107045799")
    monkeypatch.setenv("LOCATION", "nbg1")


@pytest.fixture
def auth_headers():
    """Gültige Authentifizierungs-Header für API-Gateway-Endpunkte."""
    return {"x-auth-token": "test-auth-secret"}