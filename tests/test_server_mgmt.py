import json
from unittest.mock import patch, MagicMock
from services import hetzner
import rest_api

@patch("services.hetzner.supabase_client_request")
@patch("urllib.request.urlopen")
@patch("services.hetzner.update_godaddy_dns")
def test_create_server_dynamic_resolution(mock_dns, mock_urlopen, mock_sb):
    server_meta = [{
        "server_id": "srv-1234",
        "hetzner_volume_id": 99999999,
        "hetzner_server_type": "cpx32",
        "game_port": 25565,
        "full_name": "server-minecraft-default"
    }]
    dns_meta = [{"subdomain": "mc"}]
    mock_sb.side_effect = [
        (200, json.dumps(server_meta)),  # Select dim_servers
        (200, json.dumps(dns_meta)),     # Select dim_dns_records
        (200, '{"status": "ok"}')        # PATCH status online
    ]

    hetzner_resp = MagicMock()
    hetzner_resp.status = 201
    hetzner_resp.read.return_value = json.dumps({
        "server": {
            "id": 101,
            "name": "server-minecraft-default",
            "status": "initializing",
            "public_net": {"ipv4": {"ip": "1.2.3.4"}}
        }
    }).encode("utf-8")
    hetzner_resp.__enter__.return_value = hetzner_resp
    mock_urlopen.return_value = hetzner_resp

    with patch("services.hetzner.log_server_start_to_supabase") as mock_log:
        res = hetzner.create_server(game="minecraft", server_name="default", seconds=300)

        assert res["server_id"] == 101
        assert res["db_server_id"] == "srv-1234"
        assert res["ip"] == "1.2.3.4"
        assert "mc.calvinkoch.ch" in res["domain"]
        assert mock_dns.called
        assert mock_log.called

@patch("services.hetzner.create_volume")
@patch("services.supabase.supabase_client_request")
def test_handle_server_create(mock_sb, mock_vol):
    mock_vol.return_value = {"id": 12345678}
    mock_sb.side_effect = [
        (200, "[]"),  # Name Check (frei)
        (201, json.dumps([{
            "server_id": "new-srv-id",
            "server_slug": "skyblock",
            "display_name": "minecraft-skyblock"
        }]))
    ]

    status, body = rest_api.handle_server_create({
        "game": "minecraft",
        "server_name": "skyblock",
        "discord_user_id": "432141301111324672"
    })

    assert status == 201
    assert body["server"]["server_slug"] == "skyblock"
    assert mock_vol.called

@patch("services.supabase.supabase_client_request")
def test_handle_server_create_invalid_name(mock_sb):
    status, body = rest_api.handle_server_create({
        "game": "minecraft",
        "server_name": "Invalid Name with Spaces!!",
        "discord_user_id": "432141301111324672"
    })
    assert status == 400
    assert "nur Kleinbuchstaben" in body["error"]

@patch("services.dns.update_godaddy_dns")
@patch("services.supabase.supabase_client_request")
@patch("services.agent.stop_remote_server")
@patch("services.hetzner.list_servers")
def test_handle_stop_with_dns_reset(mock_list, mock_agent, mock_sb, mock_dns):
    mock_list.return_value = [{
        "server_id": 999,
        "name": "server-minecraft-skyblock",
        "ip": "2.28.203.66"
    }]
    mock_agent.return_value = {"status": "stopping"}
    mock_sb.side_effect = [
        (200, json.dumps([{"server_id": "srv-sky", "server_slug": "skyblock"}])), # Select dim_servers
        (200, '{"status": "ok"}'), # Patch dim_servers offline
        (200, json.dumps([{"subdomain": "sky"}])) # Select dim_dns_records
    ]

    status, body = rest_api.handle_stop({"name": "skyblock"})
    assert status == 200
    assert body["mode"] == "graceful"
    mock_dns.assert_called_with("0.0.0.0", subdomain="sky", server_id="srv-sky")