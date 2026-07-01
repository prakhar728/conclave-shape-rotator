"""Task #18 — blocking first-login Terms & Conditions gate.

  - a fresh user needs acceptance (`tnc_needs_acceptance` on /me, GET /me/tnc).
  - accepting records users.tnc_accepted_at + tnc_version, clears the flag.
  - a stale/unknown version is rejected (422) so the gate can't be bypassed.
  - a version bump re-fires the gate for a previously-accepted user.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str = "alice@x.com") -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


class TestGate:
    def test_fresh_user_needs_acceptance(self, client):
        me = _login(client)
        # /me flags the block for the client-side gate.
        assert me["user"]["tnc_needs_acceptance"] is True
        assert me["user"]["tnc_accepted_at"] is None
        assert me["user"]["tnc_current_version"] == "tnc-v0"

        r = client.get("/api/users/me/tnc")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == "tnc-v0"
        assert body["needs_acceptance"] is True
        assert "pre-production" in body["text"]  # the verbatim placeholder copy

    def test_accept_records_and_clears(self, client):
        _login(client)
        r = client.post("/api/users/me/tnc/accept", json={"version": "tnc-v0"})
        assert r.status_code == 200, r.text
        assert r.json()["needs_acceptance"] is False

        # Persisted on the user row.
        from auth.session import COOKIE_NAME  # noqa: F401 — cookie already on client
        me = client.get("/auth/v1/me").json()
        assert me["user"]["tnc_needs_acceptance"] is False
        assert me["user"]["tnc_version"] == "tnc-v0"
        assert me["user"]["tnc_accepted_at"] is not None

        status = client.get("/api/users/me/tnc").json()
        assert status["needs_acceptance"] is False
        assert status["accepted_version"] == "tnc-v0"

    def test_unknown_version_rejected(self, client):
        _login(client)
        r = client.post("/api/users/me/tnc/accept", json={"version": "tnc-v99"})
        assert r.status_code == 422
        # still not accepted
        assert client.get("/api/users/me/tnc").json()["needs_acceptance"] is True

    def test_version_bump_refires_gate(self, client, monkeypatch):
        _login(client)
        client.post("/api/users/me/tnc/accept", json={"version": "tnc-v0"})
        assert client.get("/auth/v1/me").json()["user"]["tnc_needs_acceptance"] is False

        # Terms bump → the previously-accepted user must accept again.
        import infra.tnc as tnc
        monkeypatch.setattr(tnc, "TNC_VERSION", "tnc-v1")
        me = client.get("/auth/v1/me").json()
        assert me["user"]["tnc_needs_acceptance"] is True
        assert me["user"]["tnc_current_version"] == "tnc-v1"

    def test_accept_requires_auth(self, client):
        assert client.post(
            "/api/users/me/tnc/accept", json={"version": "tnc-v0"}
        ).status_code == 401
        assert client.get("/api/users/me/tnc").status_code == 401
