from unittest.mock import patch
from fastapi.testclient import TestClient
from personal_server_hub.api.main import app
from personal_server_hub.api.dependencies import Principal, get_principal

client = TestClient(app)


@patch("personal_server_hub.api.routers.billing.get_exchange_rate")
def test_exchange_rate_endpoint(mock_get_exchange_rate):
    mock_get_exchange_rate.return_value = (200, {"base_currency": "CHF", "target_currency": "EUR", "rate": 1.05})
    response = client.post("/exchange-rate", json={"base": "CHF", "target": "EUR"})
    assert response.status_code == 200
    assert response.json() == {"base_currency": "CHF", "target_currency": "EUR", "rate": 1.05}
    mock_get_exchange_rate.assert_called_once_with({"base": "CHF", "from": None, "target": "EUR", "to": None})


@patch("personal_server_hub.api.routers.billing.get_costs_summary")
def test_costs_endpoint(mock_get_costs):
    mock_get_costs.return_value = (200, {"rows": []})
    response = client.post("/costs", json={"timeframe": "current_month"})
    assert response.status_code == 200
    assert response.json() == {"rows": []}


@patch("personal_server_hub.api.routers.billing.get_account_balance")
def test_account_endpoint(mock_get_account):
    mock_get_account.return_value = (200, {"mode": "single", "user": {"discord_user_id": "123"}})
    response = client.post("/account", json={"user": "me"})
    assert response.status_code == 200
    assert response.json() == {"mode": "single", "user": {"discord_user_id": "123"}}


@patch("personal_server_hub.api.routers.billing.add_cash_payment")
@patch("personal_server_hub.api.dependencies.get_user_role", return_value=(200, "superadmin"))
def test_cash_endpoint_success(mock_role, mock_add_cash):
    mock_add_cash.return_value = (200, {"payment": {"amount": 10}})
    app.dependency_overrides[get_principal] = lambda: Principal(kind="discord", discord_user_id="123")
    try:
        response = client.post("/cash", json={"target_uid": "456", "amount": 10.0})
        assert response.status_code == 200
        assert response.json() == {"payment": {"amount": 10}}
    finally:
        app.dependency_overrides.pop(get_principal, None)


def test_cash_endpoint_forbidden_for_service():
    # Service principal is not allowed on admin routes (require_admin requires discord principal)
    response = client.post("/cash", json={"target_uid": "456", "amount": 10.0})
    assert response.status_code == 403
