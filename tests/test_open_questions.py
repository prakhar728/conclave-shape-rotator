"""Tests for /api/workspaces/{id}/open-questions (Phase 3.2)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import identity, workspaces
from storage import sqlite as _sqlite
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
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
    assert r.status_code == 200
    return r.json()


def _seed_session(
    *,
    session_id: str,
    workspace_id: str,
    owner_user_id: str,
    date: str,
    questions: list[tuple[str, list[str]]],
    visibility: str = "owner-only",
    summary: str = "demo summary",
) -> None:
    signals = [
        {
            "kind": "open_question",
            "text": text,
            "said_by": said_by,
            "about_person": [],
            "source_quote": None,
        }
        for text, said_by in questions
    ]
    _sqlite.save_transcript_session(
        session_id=session_id,
        source="test",
        session_date=date,
        raw_diarization=[],
        metadata={"date": date, "source": "test"},
        derived={"summary": summary, "signals": signals, "entities": []},
    )
    _sqlite.set_transcript_workspace(
        session_id=session_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        visibility=visibility,
    )


def test_unauthenticated_returns_401(client: TestClient):
    r = client.get("/api/workspaces/ws_anything/open-questions")
    assert r.status_code == 401


def test_non_member_returns_404(client: TestClient):
    a = _login(client, "a@example.com")
    ws_id = a["workspace"]["id"]
    client.cookies.clear()
    _login(client, "b@example.com")
    r = client.get(f"/api/workspaces/{ws_id}/open-questions")
    assert r.status_code == 404


def test_empty_workspace_returns_empty_list(client: TestClient):
    me = _login(client, "empty@example.com")
    r = client.get(f"/api/workspaces/{me['workspace']['id']}/open-questions")
    assert r.status_code == 200
    assert r.json() == {"questions": []}


def test_aggregates_across_two_meetings_newest_first(client: TestClient):
    me = _login(client, "host@example.com")
    ws = me["workspace"]["id"]
    _seed_session(
        session_id="sess-old",
        workspace_id=ws,
        owner_user_id=me["user"]["id"],
        date="2026-05-01",
        questions=[("Old q1", ["Alice"]), ("Old q2", ["Bob"])],
    )
    _seed_session(
        session_id="sess-new",
        workspace_id=ws,
        owner_user_id=me["user"]["id"],
        date="2026-06-01",
        questions=[("New q1", ["Alice"])],
    )

    r = client.get(f"/api/workspaces/{ws}/open-questions")
    assert r.status_code == 200
    qs = r.json()["questions"]
    assert [q["text"] for q in qs] == ["New q1", "Old q1", "Old q2"]
    assert qs[0]["meeting"]["session_id"] == "sess-new"
    assert qs[0]["said_by"] == ["Alice"]
    assert qs[1]["meeting"]["date"] == "2026-05-01"


def test_ignores_non_question_signals(client: TestClient):
    me = _login(client, "filt@example.com")
    ws = me["workspace"]["id"]
    _sqlite.save_transcript_session(
        session_id="sess-mixed",
        source="test",
        session_date="2026-06-01",
        raw_diarization=[],
        metadata={"date": "2026-06-01", "source": "test"},
        derived={
            "summary": "mixed",
            "signals": [
                {"kind": "open_question", "text": "Q1", "said_by": ["A"], "about_person": [], "source_quote": None},
                {"kind": "action_item", "text": "A1", "said_by": ["B"], "about_person": [], "source_quote": None},
                {"kind": "insight", "text": "I1", "said_by": ["C"], "about_person": [], "source_quote": None},
            ],
            "entities": [],
        },
    )
    _sqlite.set_transcript_workspace(
        session_id="sess-mixed",
        workspace_id=ws,
        owner_user_id=me["user"]["id"],
        visibility="owner-only",
    )
    r = client.get(f"/api/workspaces/{ws}/open-questions")
    assert [q["text"] for q in r.json()["questions"]] == ["Q1"]


def test_owner_only_session_not_visible_to_non_owner_member(client: TestClient):
    """Multi-member sim: workspace member who isn't the meeting's owner
    shouldn't see owner-only questions."""
    a = identity.upsert_user_by_supabase("sb-a@example.com", "a@example.com")
    b = identity.upsert_user_by_supabase("sb-b@example.com", "b@example.com")
    ws = workspaces.create_workspace("Shared WS", a["id"])
    # Manually add b as a workspace member (v1.5 surface; helper not exposed in v1).
    from storage.sqlite import _now
    _get_conn().execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, 'member', ?, ?)",
        (ws["id"], b["id"], _now(), a["id"]),
    )

    _seed_session(
        session_id="sess-priv",
        workspace_id=ws["id"],
        owner_user_id=a["id"],
        date="2026-06-01",
        questions=[("Only A sees this", ["A"])],
        visibility="owner-only",
    )

    # B logs in and queries → empty.
    _login(client, "b@example.com")
    r = client.get(f"/api/workspaces/{ws['id']}/open-questions")
    assert r.status_code == 200
    assert r.json()["questions"] == []


def test_shared_session_visible_to_workspace_member_via_share(client: TestClient):
    a = identity.upsert_user_by_supabase("sb-a@example.com", "a@example.com")
    b = identity.upsert_user_by_supabase("sb-b@example.com", "b@example.com")
    ws = workspaces.create_workspace("Shared WS 2", a["id"])
    from storage.sqlite import _now
    _get_conn().execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, 'member', ?, ?)",
        (ws["id"], b["id"], _now(), a["id"]),
    )

    _seed_session(
        session_id="sess-shared",
        workspace_id=ws["id"],
        owner_user_id=a["id"],
        date="2026-06-01",
        questions=[("Shared Q", ["A"])],
        visibility="shared",
    )
    workspaces.add_meeting_share("sess-shared", "b@example.com", a["id"])

    _login(client, "b@example.com")
    r = client.get(f"/api/workspaces/{ws['id']}/open-questions")
    assert r.json()["questions"][0]["text"] == "Shared Q"
