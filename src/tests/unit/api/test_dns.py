import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from personal_server_hub.api.main import app

client = TestClient(app)


@patch(
    "personal_server_hub.api.routers.dns.list_dns_records",
    return_value=(200, {"records": [{"subdomain": "mc"}]}),
)
def test_read_dns_records_endpoint_calls_application_operation(mock_list):
    response = client.get("/dns/records")

    assert response.status_code == 200
    assert response.json() == {"records": [{"subdomain": "mc"}]}
    mock_list.assert_called_once_with()


@patch(
    "personal_server_hub.api.routers.dns.sync_dns_records",
    return_value=(500, {"error": "GoDaddy API Keys fehlen"}),
)
def test_sync_dns_endpoint_preserves_error_status(mock_sync):
    response = client.post("/dns/sync")

    assert response.status_code == 500
    assert response.json() == {"error": "GoDaddy API Keys fehlen"}
    mock_sync.assert_called_once_with()


def test_dns_endpoints_enforce_http_methods():
    assert client.post("/dns/records").status_code == 405
    assert client.get("/dns/sync").status_code == 405


@patch("personal_server_hub.application.dns.supabase_client_request")
def test_list_dns_records_returns_supabase_rows(mock_sb):
    from personal_server_hub.application.dns import list_dns_records

    mock_sb.return_value = (200, json.dumps([{"subdomain": "mc"}]))

    assert list_dns_records() == (200, {"records": [{"subdomain": "mc"}]})
    mock_sb.assert_called_once_with("dim_dns_records?order=subdomain.asc", method="GET")


@patch("personal_server_hub.application.dns.supabase_client_request")
def test_list_dns_records_forwards_supabase_error(mock_sb):
    from personal_server_hub.application.dns import list_dns_records

    mock_sb.return_value = (503, "down")

    status, body = list_dns_records()

    assert status == 503
    assert "down" in body["error"]


@patch("personal_server_hub.application.dns.sync_all_dns_from_godaddy")
def test_sync_dns_records_maps_error_to_500(mock_sync):
    from personal_server_hub.application.dns import sync_dns_records

    mock_sync.return_value = {"error": "boom"}
    assert sync_dns_records() == (500, {"error": "boom"})

    mock_sync.return_value = {"synced_count": 1, "records": ["mc (A)"]}
    assert sync_dns_records() == (200, {"synced_count": 1, "records": ["mc (A)"]})
