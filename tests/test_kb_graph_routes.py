"""Phase 3.5d C28/C29 — graph endpoint + speaker aggregation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra.speakers import aggregate_speakers
from storage import kb_graph
from storage.sqlite import _get_conn
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


# ---------------------------------------------------------------------------
# C29 — speaker aggregation (pure)
# ---------------------------------------------------------------------------

def _sess(sid, speakers, date="2026-06-01"):
    return Session(
        session_id=sid,
        raw_diarization=[
            RawSegment(speaker=sp, text="hi", start=float(i), end=float(i + 1))
            for i, sp in enumerate(speakers)
        ],
        metadata=SessionMetadata(date=date, source="t", tags=[]),
        derived=Derived(),
    )


def test_speakers_case_insensitive_merge():
    out = aggregate_speakers([
        _sess("s1", ["Andrew Miller", "andrew miller", "Ada"]),
        _sess("s2", ["ANDREW MILLER"]),
    ])
    am = out["andrew miller"]
    assert am["name"] == "Andrew Miller"          # first-seen casing kept
    assert set(am["session_ids"]) == {"s1", "s2"}
    assert am["turn_count"] == 3
    assert out["ada"]["session_ids"] == ["s1"]


def test_speakers_anonymous_excluded():
    out = aggregate_speakers([_sess("s1", ["Speaker 1", "speaker_2", "Real Person"])])
    assert set(out) == {"real person"}


# ---------------------------------------------------------------------------
# C28 — graph endpoint
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    conn = _get_conn()
    conn.execute("DELETE FROM entity_mentions WHERE session_id LIKE 'kb-g-%'")
    conn.execute("DELETE FROM entities WHERE canonical_name LIKE 'Graph%'")
    for sid in ("kb-g-1", "kb-g-2"):
        conn.execute("DELETE FROM transcript_sessions WHERE session_id = ?", (sid,))
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


def _login(client, email):
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "0"})
    assert r.status_code == 200


def _seed(client, email):
    _login(client, email)
    ws = client.get("/api/workspaces").json()["workspaces"][0]
    user_row = _get_conn().execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    for sid, date, speakers in (
        ("kb-g-1", "2026-06-01", ["Ada", "Bob"]),
        ("kb-g-2", "2026-06-03", ["Ada"]),
    ):
        store.save_session(_sess(sid, speakers, date))
        store.set_workspace(sid, workspace_id=ws["id"],
                            owner_user_id=user_row["id"], visibility="owner-only")
    eid = kb_graph.insert_entity("project", "GraphProj", ["GraphProj"])
    kb_graph.add_mentions(eid, "kb-g-1", [0, 1], "GraphProj")
    kb_graph.add_mentions(eid, "kb-g-2", [0], "GraphProj")
    return ws["id"], eid


def test_graph_nodes_edges_weights(client):
    wsid, eid = _seed(client, "g1@example.com")
    r = client.get(f"/api/workspaces/{wsid}/graph")
    assert r.status_code == 200
    body = r.json()
    kinds = {n["kind"] for n in body["nodes"]}
    assert kinds == {"meeting", "entity", "speaker"}

    ent = next(n for n in body["nodes"] if n["kind"] == "entity")
    assert ent["label"] == "GraphProj" and ent["weight"] == 3

    e1 = next(e for e in body["edges"]
              if e["source"] == f"entity:{eid}" and e["target"] == "meeting:kb-g-1")
    assert e1["weight"] == 2

    ada = next(n for n in body["nodes"] if n["kind"] == "speaker" and n["label"] == "Ada")
    ada_edges = [e for e in body["edges"] if e["source"] == ada["id"]]
    assert len(ada_edges) == 2  # Ada spoke in both meetings


def test_graph_as_of_filter(client):
    wsid, eid = _seed(client, "g2@example.com")
    r = client.get(f"/api/workspaces/{wsid}/graph", params={"as_of": "2026-06-02"})
    body = r.json()
    meeting_ids = {n["id"] for n in body["nodes"] if n["kind"] == "meeting"}
    # kb-g-2 (dated 2026-06-03) drops out; kb-g-1 stays. Demo sessions
    # (0009-seeded, May dates, any-authed-user) may legitimately appear,
    # so assert membership rather than set equality.
    assert "meeting:kb-g-1" in meeting_ids
    assert "meeting:kb-g-2" not in meeting_ids
    # edges into the dropped meeting are gone too
    assert all(e["target"] != "meeting:kb-g-2" for e in body["edges"])


def test_graph_type_and_min_mentions_filters(client):
    wsid, eid = _seed(client, "g3@example.com")
    body = client.get(
        f"/api/workspaces/{wsid}/graph", params={"types": "person"}
    ).json()
    assert all(n["kind"] != "entity" for n in body["nodes"])
    body = client.get(
        f"/api/workspaces/{wsid}/graph", params={"min_mentions": 5}
    ).json()
    assert all(n["kind"] != "entity" for n in body["nodes"])


def test_graph_auth(client):
    assert client.get("/api/workspaces/w/graph").status_code == 401
    _login(client, "g4@example.com")
    assert client.get("/api/workspaces/nope/graph").status_code == 404
