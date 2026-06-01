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
    conn = _get_conn()
    for table in ("sessions", "meeting_shares", "workspace_members", "workspaces", "users"):
        conn.execute(f"DELETE FROM {table}")
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


def test_meetings_endpoint_stub(client: TestClient):
    _login(client, "meet@example.com")
    ws_id = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    r = client.get(f"/api/workspaces/{ws_id}/meetings")
    assert r.status_code == 200
    body = r.json()
    assert body["meetings"] == []
    assert "Phase 1.6" in body["note"]


def test_add_member_returns_501(client: TestClient):
    _login(client, "members@example.com")
    ws_id = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    r = client.post(f"/api/workspaces/{ws_id}/members", json={})
    assert r.status_code == 501
