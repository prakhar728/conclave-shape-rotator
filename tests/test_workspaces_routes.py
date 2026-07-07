"""HTTP tests for /api/workspaces/*.

Auth is exercised via the real /auth/v1/verify-otp flow (Supabase monkeypatched).
That mirrors how the frontend will use these endpoints.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


def test_unauthenticated_returns_401(client: TestClient):
    assert client.get("/api/workspaces").status_code == 401
    assert client.post("/api/workspaces", json={"name": "X"}).status_code == 401


def test_list_returns_personal_workspace_after_login(client: TestClient):
    _login(client, "alice@example.com")
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    body = r.json()
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["name"] == "Personal"
    assert body["workspaces"][0]["role"] == "owner"


def test_create_workspace(client: TestClient):
    _login(client, "creator@example.com")
    r = client.post("/api/workspaces", json={"name": "Side Project"})
    assert r.status_code == 201
    ws = r.json()["workspace"]
    assert ws["name"] == "Side Project"
    # Listing shows both Personal + new one.
    listed = client.get("/api/workspaces").json()["workspaces"]
    names = sorted(w["name"] for w in listed)
    assert names == ["Personal", "Side Project"]


def test_create_workspace_rejects_blank_name(client: TestClient):
    _login(client, "blank@example.com")
    r = client.post("/api/workspaces", json={"name": ""})
    assert r.status_code == 422


def test_get_workspace_details(client: TestClient):
    _login(client, "detail@example.com")
    ws_id = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    r = client.get(f"/api/workspaces/{ws_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["workspace"]["id"] == ws_id
    assert body["role"] == "owner"


def test_non_member_cannot_see_workspace(client: TestClient):
    _login(client, "a@example.com")
    ws_id = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    # Different user logs in, gets their own session.
    client.cookies.clear()
    _login(client, "b@example.com")
    r = client.get(f"/api/workspaces/{ws_id}")
    assert r.status_code == 404


def test_meetings_endpoint_empty_for_new_workspace(client: TestClient):
    """New workspace has no meetings until 1.6's set_workspace binds one."""
    _login(client, "meet@example.com")
    ws_id = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    r = client.get(f"/api/workspaces/{ws_id}/meetings")
    assert r.status_code == 200
    assert r.json()["meetings"] == []


def test_owner_can_invite_member(client: TestClient):
    """Task #32: the once-501 endpoint now creates a pending invite (owner-only). #25: invites target a
    TEAM workspace — the default Personal workspace is non-invitable, so we create a team one first."""
    _login(client, "members@example.com")
    ws_id = client.post("/api/workspaces", json={"name": "Team WS"}).json()["workspace"]["id"]
    r = client.post(f"/api/workspaces/{ws_id}/members", json={"email": "invitee@example.com"})
    assert r.status_code == 201, r.text
    assert r.json()["invite"]["email"] == "invitee@example.com"


def test_personal_workspace_rejects_invites(client: TestClient):
    """#25: the auto-provisioned Personal workspace is solo — inviting into it is 403 (non-invitable)."""
    _login(client, "solo@example.com")
    ws_id = client.get("/api/workspaces").json()["workspaces"][0]["id"]  # the Personal workspace
    r = client.post(f"/api/workspaces/{ws_id}/members", json={"email": "someone@example.com"})
    assert r.status_code == 403, r.text
