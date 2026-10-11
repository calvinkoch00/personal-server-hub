import json
import os
from unittest.mock import patch

import pytest

from personal_server_hub.runtime_secrets import (
    REQUIRED_RUNTIME_SECRETS,
    load_runtime_secrets,
)


def _runtime_secret_values() -> dict[str, str]:
    return {name: f"test-{name.lower()}" for name in REQUIRED_RUNTIME_SECRETS}


def test_load_runtime_secrets_populates_environment(monkeypatch):
    values = _runtime_secret_values()
    monkeypatch.setenv("APP_SECRETS_ARN", "test-secret-arn")

    with patch("boto3.client") as client:
        client.return_value.get_secret_value.return_value = {
            "SecretString": json.dumps(values)
        }

        load_runtime_secrets()

    for name, value in values.items():
        assert os.environ[name] == value
    client.assert_called_once_with("secretsmanager", region_name="eu-central-1")
    client.return_value.get_secret_value.assert_called_once_with(
        SecretId="test-secret-arn"
    )


def test_load_runtime_secrets_requires_all_application_settings(monkeypatch):
    monkeypatch.setenv("APP_SECRETS_ARN", "test-secret-arn")
    with patch("boto3.client") as client:
        client.return_value.get_secret_value.return_value = {
            "SecretString": json.dumps({"AUTH_SECRET": "test-auth"})
        }

        with pytest.raises(RuntimeError, match="missing required settings"):
            load_runtime_secrets()


def test_load_runtime_secrets_skips_local_environment(monkeypatch):
    monkeypatch.delenv("APP_SECRETS_ARN", raising=False)

    with patch("boto3.client") as client:
        load_runtime_secrets()

    client.assert_not_called()
