# to run this test from root directory, use the following command:
# pytest -s src/tests/unit/api/test_health.py -v

import httpx2 as httpx
from fastapi.testclient import TestClient

from personal_server_hub.api.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")

    assert response.status_code == httpx.codes.OK
    assert response.json() == {"status": "ok"}
    

