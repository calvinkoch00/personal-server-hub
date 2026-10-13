import re
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from personal_server_hub.api import dependencies
from personal_server_hub.api.dependencies import (
    Principal,
    internal_headers,
    require_admin,
    require_registered,
)
from personal_server_hub.api.main import app

SECRET = {"x-auth-token": "test-auth-secret"}


def _all_routes():
    # OpenAPI lists every API route, including those of nested routers.
    for path, operations in app.openapi()["paths"].items():
        for method in sorted(operations):
            yield method.upper(), re.sub(r"{[^}]+}", "x", path)


ROUTES = list(_all_routes())
client = TestClient(app)


def test_route_inventory_is_not_empty():
    assert ("POST", "/dns/sync") in ROUTES


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_rejects_unauthenticated_calls(method, path):
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_rejects_wrong_secret(method, path):
    response = client.request(method, path, headers={"x-auth-token": "wrong"})
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ROUTES)
def test_discord_headers_without_internal_token_are_ignored(method, path):
    headers = {"x-discord-user-id": "123", "x-internal-token": "guessed"}
    assert client.request(method, path, headers=headers).status_code == 401


def test_auth_runs_before_body_validation():
    assert client.post("/users/register", json={}).status_code == 401


# --- require_registered / require_admin on a throwaway app -------------------

probe = FastAPI()


@probe.get("/registered")
def registered(principal: Principal = Depends(require_registered)):
    return {"kind": principal.kind}


@probe.get("/admin")
def admin(principal: Principal = Depends(require_admin)):
    return {"kind": principal.kind}


probe_client = TestClient(probe)


def _role(status, role):
    return patch.object(dependencies, "get_user_role", return_value=(status, role))


def test_registered_allows_service_without_lookup():
    with _role(500, None) as lookup:
        response = probe_client.get("/registered", headers=SECRET)
    assert response.status_code == 200
    lookup.assert_not_called()


def test_registered_allows_known_discord_user():
    with _role(200, "user") as lookup:
        response = probe_client.get("/registered", headers=internal_headers("123"))
    assert response.status_code == 200
    lookup.assert_called_once_with("123")


def test_registered_rejects_unknown_discord_user():
    with _role(200, None):
        response = probe_client.get("/registered", headers=internal_headers("123"))
    assert response.status_code == 403


def test_registered_reports_lookup_failure_as_502():
    with _role(500, None):
        response = probe_client.get("/registered", headers=internal_headers("123"))
    assert response.status_code == 502


def test_admin_rejects_service_secret():
    with _role(200, "superadmin") as lookup:
        response = probe_client.get("/admin", headers=SECRET)
    assert response.status_code == 403
    lookup.assert_not_called()


def test_admin_rejects_regular_discord_user():
    with _role(200, "user"):
        response = probe_client.get("/admin", headers=internal_headers("123"))
    assert response.status_code == 403


def test_admin_allows_superadmin_discord_user():
    with _role(200, "superadmin"):
        response = probe_client.get("/admin", headers=internal_headers("123"))
    assert response.status_code == 200
    assert response.json() == {"kind": "discord"}


def test_admin_without_credentials_is_401():
    assert probe_client.get("/admin").status_code == 401
