"""Tests for /api/meetings/invite-bot + /bot-status + /shares.

Recato is monkeypatched — `launch_bot` returns a fake bot id without
touching the network. The auth flow uses /auth/v1/verify-otp with the
same Supabase monkeypatch as test_workspaces_routes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import bot_invitations
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM bot_invitations")
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

    import api.bot_routes as br
    monkeypatch.setattr(
        br,
        "launch_bot",
        lambda **kw: {"id": 42, "status": "joining", "native_meeting_id": kw["native_meeting_id"]},
    )

    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


def test_unauthenticated_invite_bot_returns_401(client: TestClient):
    r = client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "abc-defg-hij", "workspace_id": "ws_anything"},
    )
    assert r.status_code == 401


def test_invite_bot_creates_invitation(client: TestClient):
    me = _login(client, "host@example.com")
    ws_id = me["workspace"]["id"]

    r = client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "abc-defg-hij", "workspace_id": ws_id},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["meeting_session_id"] == "abc-defg-hij"
    assert body["status"] == "joining"
    inv = bot_invitations.get_invitation(body["invitation_id"])
    assert inv["status"] == "joining"
    assert inv["recato_bot_id"] == 42


def test_invite_bot_parses_meet_url(client: TestClient):
    me = _login(client, "url@example.com")
    ws_id = me["workspace"]["id"]
    r = client.post(
        "/api/meetings/invite-bot",
        json={
            "meet_url_or_code": "https://meet.google.com/xyz-abcd-pqr",
            "workspace_id": ws_id,
        },
    )
    assert r.status_code == 201
    assert r.json()["meeting_session_id"] == "xyz-abcd-pqr"


def test_invite_bot_rejects_garbage(client: TestClient):
    me = _login(client, "garbage@example.com")
    ws_id = me["workspace"]["id"]
    r = client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "not-a-meet-link", "workspace_id": ws_id},
    )
    assert r.status_code == 422


def test_invite_bot_rejects_non_member_workspace(client: TestClient):
    a = _login(client, "alice@example.com")
    ws_a = a["workspace"]["id"]
    client.cookies.clear()
    _login(client, "bob@example.com")
    r = client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "abc-defg-hij", "workspace_id": ws_a},
    )
    assert r.status_code == 404


def test_invite_bot_writes_attendee_shares(client: TestClient):
    me = _login(client, "host2@example.com")
    ws_id = me["workspace"]["id"]
    r = client.post(
        "/api/meetings/invite-bot",
        json={
            "meet_url_or_code": "abc-defg-hij",
            "workspace_id": ws_id,
            "attendee_emails": ["bob@example.com", "carol@example.com"],
        },
    )
    assert r.status_code == 201
    from infra.workspaces import list_meeting_shares
    shares = {s["user_email"] for s in list_meeting_shares("abc-defg-hij")}
    assert shares == {"bob@example.com", "carol@example.com"}


def test_invite_bot_recato_failure_marks_invitation_failed(client: TestClient, monkeypatch):
    from connectors.recato.launch import RecatoLaunchError
    import api.bot_routes as br
    monkeypatch.setattr(
        br,
        "launch_bot",
        lambda **kw: (_ for _ in ()).throw(RecatoLaunchError("Recato down")),
    )

    me = _login(client, "fail@example.com")
    ws_id = me["workspace"]["id"]
    r = client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "abc-defg-hij", "workspace_id": ws_id},
    )
    assert r.status_code == 502
    # Invitation row exists and is marked failed (audit trail).
    inv = bot_invitations.find_by_meeting("google_meet", "abc-defg-hij")
    assert inv["status"] == "failed"


def test_bot_status(client: TestClient):
    me = _login(client, "stat@example.com")
    ws_id = me["workspace"]["id"]
    invite = client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "abc-defg-hij", "workspace_id": ws_id},
    ).json()
    r = client.get(f"/api/meetings/{invite['meeting_session_id']}/bot-status")
    assert r.status_code == 200
    assert r.json()["status"] == "joining"
    assert r.json()["recato_bot_id"] == 42


def test_bot_status_unknown_meeting(client: TestClient):
    _login(client, "unknown@example.com")
    r = client.get("/api/meetings/abc-defg-hij/bot-status")
    assert r.status_code == 404


def test_add_share_post_facto(client: TestClient):
    me = _login(client, "shareadd@example.com")
    ws_id = me["workspace"]["id"]
    client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "abc-defg-hij", "workspace_id": ws_id},
    )
    r = client.post(
        "/api/meetings/abc-defg-hij/shares",
        json={"email": "late@example.com"},
    )
    assert r.status_code == 201
    from infra.workspaces import has_meeting_share
    assert has_meeting_share("abc-defg-hij", "late@example.com")


def test_add_share_only_owner_can(client: TestClient):
    a = _login(client, "owner@example.com")
    ws_a = a["workspace"]["id"]
    client.post(
        "/api/meetings/invite-bot",
        json={"meet_url_or_code": "abc-defg-hij", "workspace_id": ws_a},
    )
    client.cookies.clear()
    _login(client, "stranger@example.com")
    r = client.post(
        "/api/meetings/abc-defg-hij/shares",
        json={"email": "x@example.com"},
    )
    assert r.status_code == 404


# --- Meet input parsing ----------------------------------------------------


def test_parse_meet_input_variants():
    from connectors.recato.launch import parse_meet_input

    assert parse_meet_input("abc-defg-hij") == "abc-defg-hij"
    assert parse_meet_input("ABC-DEFG-HIJ") == "abc-defg-hij"
    assert parse_meet_input("https://meet.google.com/abc-defg-hij") == "abc-defg-hij"
    assert parse_meet_input("https://meet.google.com/abc-defg-hij/") == "abc-defg-hij"
    assert (
        parse_meet_input("https://meet.google.com/abc-defg-hij?foo=bar")
        == "abc-defg-hij"
    )

    import pytest

    with pytest.raises(ValueError):
        parse_meet_input("")
    with pytest.raises(ValueError):
        parse_meet_input("not-a-code")
    with pytest.raises(ValueError):
        parse_meet_input("https://zoom.us/j/123")
