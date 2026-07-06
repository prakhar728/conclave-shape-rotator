"""Task #9 — boot seeder (main._seed_workspace_from_env).

The seeder gives strict link-only auth a first membership to attach to: it
creates CONCLAVE_SEED_WORKSPACE + a standing owner invite for
CONCLAVE_SEED_OWNER_EMAIL, idempotently, at startup.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    yield


def _seed_admin():
    from infra import identity
    return identity.upsert_user_by_supabase("seed-admin", "seed-admin@conclave.local")


def test_seed_creates_workspace_and_owner_invite(monkeypatch):
    monkeypatch.setenv("CONCLAVE_SEED_OWNER_EMAIL", "boss@example.com")
    monkeypatch.setenv("CONCLAVE_SEED_WORKSPACE", "demo-ws")
    import main
    main._seed_workspace_from_env()

    from infra import workspaces
    wss = [w for w in workspaces.list_user_workspaces(_seed_admin()["id"]) if w["name"] == "demo-ws"]
    assert wss, "workspace seeded"
    pend = workspaces.list_pending_invites(wss[0]["id"])
    assert any(i["email"] == "boss@example.com" and i["role"] == "owner" for i in pend)


def test_seed_is_idempotent(monkeypatch):
    monkeypatch.setenv("CONCLAVE_SEED_OWNER_EMAIL", "boss@example.com")
    monkeypatch.setenv("CONCLAVE_SEED_WORKSPACE", "demo-ws")
    import main
    main._seed_workspace_from_env()
    main._seed_workspace_from_env()  # second boot must not create a 2nd workspace

    from infra import workspaces
    wss = [w for w in workspaces.list_user_workspaces(_seed_admin()["id"]) if w["name"] == "demo-ws"]
    assert len(wss) == 1


def test_seed_noop_without_env(monkeypatch):
    monkeypatch.delenv("CONCLAVE_SEED_OWNER_EMAIL", raising=False)
    import main
    main._seed_workspace_from_env()  # no-op, must not raise


def test_seeded_invite_lets_that_email_connect(monkeypatch):
    """End-to-end: seed → the seeded email passes link-only exchange-token."""
    monkeypatch.setenv("CONCLAVE_SEED_OWNER_EMAIL", "boss@example.com")
    monkeypatch.setenv("CONCLAVE_SEED_WORKSPACE", "demo-ws")
    import main
    main._seed_workspace_from_env()

    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_validate", lambda tok: {"sub": "sb-boss", "email": "boss@example.com"})
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    r = client.post("/auth/v1/exchange-token", json={"access_token": "ok"})
    assert r.status_code == 200, r.text
    assert r.json()["workspace"]["name"] == "demo-ws"
