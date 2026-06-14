"""P4 demo enabler — env-gated Conclave dev-login (mirrors FPM's, for the browser demo)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_tables():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client() -> TestClient:
    from main import app
    return TestClient(app)


def test_dev_login_disabled_by_default(client):
    assert client.get("/auth/v1/dev-login", params={"email": "a@x.com"}).status_code == 404


def test_dev_login_sets_session_when_enabled(client, monkeypatch):
    monkeypatch.setenv("CONCLAVE_DEV_LOGIN", "1")
    r = client.get("/auth/v1/dev-login", params={"email": "Alice@X.com"})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "alice@x.com"   # lowercased
    # the session cookie now authenticates /auth/v1/me
    me = client.get("/auth/v1/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "alice@x.com"
