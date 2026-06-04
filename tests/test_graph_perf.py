"""Phase 3.5d C34 — graph endpoint perf budget on a synthetic workspace.

50 meetings × 8 speakers/turns × 60 entities with cross-meeting
mentions. Budget: < 1s per request (roadmap 3.5f.5 / 3.5d C34).
Generous against CI noise but catches accidental O(n²) regressions.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from storage import kb_graph
from storage.sqlite import _get_conn
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata

N_MEETINGS = 50
N_ENTITIES = 60

GRAPH_BUDGET_S = 1.0


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


@pytest.fixture
def big_workspace(client):
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    conn = _get_conn()
    conn.execute("DELETE FROM entity_mentions WHERE session_id LIKE 'perf-%'")
    conn.execute("DELETE FROM entities WHERE canonical_name LIKE 'PerfEnt%'")
    conn.execute("DELETE FROM transcript_sessions WHERE session_id LIKE 'perf-%'")

    r = client.post("/auth/v1/verify-otp",
                    json={"email": "perf@example.com", "token": "0"})
    assert r.status_code == 200
    ws = client.get("/api/workspaces").json()["workspaces"][0]
    user_row = conn.execute(
        "SELECT id FROM users WHERE email = 'perf@example.com'"
    ).fetchone()

    eids = [
        kb_graph.insert_entity(
            ["project", "topic", "tool", "company", "person"][i % 5],
            f"PerfEnt{i}", [f"PerfEnt{i}"],
        )
        for i in range(N_ENTITIES)
    ]
    for m in range(N_MEETINGS):
        sid = f"perf-{m}"
        store.save_session(Session(
            session_id=sid,
            raw_diarization=[
                RawSegment(speaker=f"Speaker Person {p}", text="words " * 30,
                           start=float(p), end=float(p + 1))
                for p in range(8)
            ],
            metadata=SessionMetadata(date=f"2026-05-{(m % 28) + 1:02d}",
                                     source="perf", tags=[]),
            derived=Derived(),
        ))
        store.set_workspace(sid, workspace_id=ws["id"],
                            owner_user_id=user_row["id"],
                            visibility="owner-only")
        # each meeting mentions ~12 entities, several turns each
        for i in range(12):
            eid = eids[(m * 7 + i) % N_ENTITIES]
            kb_graph.add_mentions(eid, sid, [0, 1, 2], f"PerfEnt{i}")

    yield ws["id"]

    conn.execute("DELETE FROM entity_mentions WHERE session_id LIKE 'perf-%'")
    conn.execute("DELETE FROM entities WHERE canonical_name LIKE 'PerfEnt%'")
    conn.execute("DELETE FROM transcript_sessions WHERE session_id LIKE 'perf-%'")


def test_graph_under_budget(client, big_workspace):
    # warm (first request pays session loads etc.)
    r = client.get(f"/api/workspaces/{big_workspace}/graph")
    assert r.status_code == 200

    t0 = time.time()
    r = client.get(f"/api/workspaces/{big_workspace}/graph")
    dt = time.time() - t0
    assert r.status_code == 200
    body = r.json()

    meetings = [n for n in body["nodes"] if n["kind"] == "meeting"]
    entities = [n for n in body["nodes"] if n["kind"] == "entity"]
    assert len(meetings) == N_MEETINGS
    assert len(entities) == N_ENTITIES  # 60 < cap of 100
    assert body["edges"]

    assert dt < GRAPH_BUDGET_S, (
        f"graph took {dt:.2f}s for {N_MEETINGS} meetings "
        f"(budget {GRAPH_BUDGET_S}s)"
    )
