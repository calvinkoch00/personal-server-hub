import pytest

from personal_server_hub.api.dependencies import Principal, get_principal
from personal_server_hub.api.main import app


@pytest.fixture(autouse=True)
def authenticated_service_principal():
    """Router unit tests focus on routing/schemas; auth is covered in tests/unit/test_auth.py."""
    app.dependency_overrides[get_principal] = lambda: Principal(kind="service")
    yield
    app.dependency_overrides.pop(get_principal, None)
