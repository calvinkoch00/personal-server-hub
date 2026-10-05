import json
import pytest
from unittest.mock import patch
import sys
import os


from aws_lambda.lambda_function import lambda_handler

@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("HETZNER_API_TOKEN", "mock-token")
    monkeypatch.setenv("VOLUME_ID", "123456")

def test_unauthorized_request():
    event = {"headers": {"x-auth-token": "falscher-token"}, "rawPath": "/start"}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 401

@patch("hetzner.create_server")
def test_start_endpoint_success(mock_create):
    mock_create.return_value = {
        "server_id": 999,
        "status": "running",
        "ip": "1.2.3.4",
        "server_type": "cpx32",
        "auto_kill_after_seconds": 20
    }

    event = {
        "headers": {"x-auth-token": "test-secret"},
        "rawPath": "/start",
        "body": json.dumps({"server_type": "cpx32"})
    }

    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["data"]["server_id"] == 999
    assert "discord_summary" in body