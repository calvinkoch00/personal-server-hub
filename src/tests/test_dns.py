import json
from unittest.mock import patch, MagicMock
from personal_server_hub.services import dns
import personal_server_hub.rest_api as rest_api

@patch("urllib.request.urlopen")
@patch("personal_server_hub.services.dns.supabase_client_request")
def test_update_godaddy_dns_success(mock_supabase, mock_urlopen, monkeypatch):
    monkeypatch.setattr(dns, "GODADDY_API_KEY", "test-api-key")
    monkeypatch.setattr(dns, "GODADDY_API_SECRET", "test-api-secret")

    # Mock GoDaddy Response (200 OK)
    godaddy_resp = MagicMock()
    godaddy_resp.status = 200
    godaddy_resp.__enter__.return_value = godaddy_resp
    mock_urlopen.return_value = godaddy_resp

    # Mock Supabase Snapshot Upsert
    mock_supabase.return_value = (201, '{"status": "ok"}')

    success = dns.update_godaddy_dns(ip="1.2.3.4", subdomain="mc")

    assert success is True
    assert mock_urlopen.called
    assert mock_supabase.called
    # Prüfen, ob Supabase mit den richtigen Feldern aufgerufen wurde
    called_args = mock_supabase.call_args[1]
    assert called_args["data"]["subdomain"] == "mc"
    assert called_args["data"]["record_value"] == "1.2.3.4"


@patch("urllib.request.urlopen")
@patch("personal_server_hub.services.dns.supabase_client_request")
def test_update_godaddy_dns_applies_staging_prefix(
    mock_supabase, mock_urlopen, monkeypatch
):
    monkeypatch.setattr(dns, "GODADDY_API_KEY", "test-api-key")
    monkeypatch.setattr(dns, "GODADDY_API_SECRET", "test-api-secret")
    monkeypatch.setattr(dns, "DNS_SUBDOMAIN_PREFIX", "staging-")

    godaddy_resp = MagicMock()
    godaddy_resp.status = 200
    godaddy_resp.__enter__.return_value = godaddy_resp
    mock_urlopen.return_value = godaddy_resp

    assert dns.update_godaddy_dns(ip="1.2.3.4", subdomain="minecraft-default")
    assert "records/A/staging-minecraft-default" in mock_urlopen.call_args.args[0].full_url
    assert mock_supabase.call_args.kwargs["data"]["subdomain"] == "staging-minecraft-default"


def test_environment_subdomain_applies_prefix_only_once(monkeypatch):
    monkeypatch.setattr(dns, "DNS_SUBDOMAIN_PREFIX", "staging-")

    assert dns.environment_subdomain("skyblock") == "staging-skyblock"
    assert dns.environment_subdomain("STAGING-skyblock") == "staging-skyblock"
    assert dns.fallback_server_subdomain("minecraft", "default") == "staging-minecraft-default"


@patch("urllib.request.urlopen")
@patch("personal_server_hub.services.dns.supabase_client_request")
def test_sync_all_dns_from_godaddy(mock_supabase, mock_urlopen, monkeypatch):
    monkeypatch.setattr(dns, "GODADDY_API_KEY", "test-api-key")
    monkeypatch.setattr(dns, "GODADDY_API_SECRET", "test-api-secret")

    # Mock GoDaddy Remote Records
    records_json = json.dumps([
        {"name": "@", "type": "A", "data": "1.2.3.4", "ttl": 600},
        {"name": "mc", "type": "A", "data": "5.6.7.8", "ttl": 600}
    ]).encode("utf-8")

    godaddy_resp = MagicMock()
    godaddy_resp.status = 200
    godaddy_resp.read.return_value = records_json
    godaddy_resp.__enter__.return_value = godaddy_resp
    mock_urlopen.return_value = godaddy_resp

    mock_supabase.return_value = (201, '{"status": "ok"}')

    res = dns.sync_all_dns_from_godaddy()

    assert "error" not in res
    assert res["synced_count"] == 2
    assert len(res["records"]) == 2


@patch("urllib.request.urlopen")
@patch("personal_server_hub.services.dns.supabase_client_request")
def test_sync_all_dns_only_imports_prefixed_records(
    mock_supabase, mock_urlopen, monkeypatch
):
    monkeypatch.setattr(dns, "GODADDY_API_KEY", "test-api-key")
    monkeypatch.setattr(dns, "GODADDY_API_SECRET", "test-api-secret")
    monkeypatch.setattr(dns, "DNS_SUBDOMAIN_PREFIX", "staging-")

    godaddy_resp = MagicMock()
    godaddy_resp.read.return_value = json.dumps([
        {"name": "mc", "type": "A", "data": "1.2.3.4", "ttl": 600},
        {"name": "staging-mc", "type": "A", "data": "5.6.7.8", "ttl": 600},
    ]).encode("utf-8")
    godaddy_resp.__enter__.return_value = godaddy_resp
    mock_urlopen.return_value = godaddy_resp
    mock_supabase.return_value = (201, '{"status": "ok"}')

    result = dns.sync_all_dns_from_godaddy()

    assert result["records"] == ["staging-mc (A)"]
    assert mock_supabase.call_count == 1
    assert mock_supabase.call_args.kwargs["data"]["subdomain"] == "staging-mc"


@patch("urllib.request.urlopen")
def test_find_subdomains_by_ip_only_returns_prefixed_records(
    mock_urlopen, monkeypatch
):
    monkeypatch.setattr(dns, "DNS_SUBDOMAIN_PREFIX", "staging-")

    godaddy_resp = MagicMock()
    godaddy_resp.read.return_value = json.dumps([
        {"name": "mc", "data": "1.2.3.4"},
        {"name": "staging-mc", "data": "1.2.3.4"},
    ]).encode("utf-8")
    godaddy_resp.__enter__.return_value = godaddy_resp
    mock_urlopen.return_value = godaddy_resp

    assert dns.find_subdomains_by_ip("1.2.3.4") == ["staging-mc"]


def test_rest_api_dns_sync_endpoint():
    with patch("personal_server_hub.services.dns.sync_all_dns_from_godaddy") as mock_sync:
        mock_sync.return_value = {"synced_count": 2, "records": ["@ (A)", "mc (A)"]}
        status, body = rest_api.route_request("/dns/sync", {})
        assert status == 200
        assert body["synced_count"] == 2

def test_rest_api_dns_records_endpoint():
    with patch("personal_server_hub.services.supabase.supabase_client_request") as mock_sb:
        mock_sb.return_value = (200, json.dumps([{"subdomain": "mc", "record_value": "1.2.3.4"}]))
        status, body = rest_api.route_request("/dns/records", {})
        assert status == 200
        assert len(body["records"]) == 1
        assert body["records"][0]["subdomain"] == "mc"