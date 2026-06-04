"""Phase 3.5f C38 — ingest-metrics viewer endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storage import kb_graph
from storage.sqlite import _get_conn
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    conn = _get_conn()
    conn.execute("DELETE FROM ingest_metrics WHERE session_id LIKE 'kb-im-%'")
    conn.execute("DELETE FROM transcript_sessions WHERE session_id LIKE 'kb-im-%'")
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


def _seed(client, email):
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "0"})
    assert r.status_code == 200
    ws = client.get("/api/workspaces").json()["workspaces"][0]
    sid = "kb-im-1"
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text="x", start=0.0, end=1.0)],
        metadata=SessionMetadata(date="2026-06-04", source="t", tags=[]),
        derived=Derived(),
    ))
    user_row = _get_conn().execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    store.set_workspace(sid, workspace_id=ws["id"],
                        owner_user_id=user_row["id"], visibility="owner-only")
    kb_graph.record_metric(sid, "extract", llm_calls=4, ms=1200, items_in=4, items_out=12)
    kb_graph.record_metric(sid, "upsert", llm_calls=12, ms=8000, items_in=12, items_out=10)
    return ws["id"], sid


def test_metrics_aggregate(client):
    wsid, sid = _seed(client, "m1@example.com")
    r = client.get(f"/api/workspaces/{wsid}/ingest-metrics")
    assert r.status_code == 200
    stages = {s["stage"]: s for s in r.json()["stages"]}
    assert stages["extract"]["mean_llm_calls"] == 4
    assert stages["upsert"]["runs"] == 1


def test_metrics_per_session_and_visibility(client):
    wsid, sid = _seed(client, "m2@example.com")
    r = client.get(f"/api/workspaces/{wsid}/ingest-metrics",
                   params={"session_id": sid})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert [row["stage"] for row in rows] == ["extract", "upsert"]

    # someone else's workspace can't read it
    client.cookies.clear()
    r2 = client.post("/auth/v1/verify-otp",
                     json={"email": "m3@example.com", "token": "0"})
    assert r2.status_code == 200
    other_ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    assert client.get(
        f"/api/workspaces/{other_ws}/ingest-metrics",
        params={"session_id": sid},
    ).status_code == 404


def test_metrics_auth(client):
    assert client.get("/api/workspaces/w/ingest-metrics").status_code == 401
