"""Phase 3.5c C23 — RRF math + hybrid search endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra.rrf import rrf_fuse
from storage import kb
from storage.sqlite import _get_conn
from storage.vec import vec_available
from transcripts import store
from transcripts.kb_chunk import KBChunk
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


# ---------------------------------------------------------------------------
# RRF math (pure)
# ---------------------------------------------------------------------------

def test_rrf_consensus_beats_single_list_head():
    # doc B is #2 in both lists; A and C are #1 in one list each.
    fused = rrf_fuse([["A", "B"], ["C", "B"]])
    assert fused[0][0] == "B"


def test_rrf_k_damping_and_order():
    fused = rrf_fuse([["A", "B", "C"]], k=60)
    scores = dict(fused)
    assert scores["A"] == pytest.approx(1 / 61)
    assert scores["C"] == pytest.approx(1 / 63)
    assert [d for d, _ in fused] == ["A", "B", "C"]


def test_rrf_empty_lists():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


# ---------------------------------------------------------------------------
# Endpoint (auth + fusion + visibility)
# ---------------------------------------------------------------------------

pytestmark_db = pytest.mark.skipif(
    not vec_available(_get_conn()),
    reason="sqlite-vec not loaded",
)


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    for sid in ("kb-se-1", "kb-se-2"):
        kb.delete_chunks_for_session(sid)
        _get_conn().execute(
            "DELETE FROM transcript_sessions WHERE session_id = ?", (sid,)
        )
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
    return r.json()


def _seed(client, email, sid, text):
    _login(client, email)
    ws = client.get("/api/workspaces").json()["workspaces"][0]
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text=text, start=0.0, end=1.0)],
        metadata=SessionMetadata(date="2026-06-04", source="test", tags=[]),
        derived=Derived(),
    ))
    user_row = _get_conn().execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    store.set_workspace(sid, workspace_id=ws["id"],
                        owner_user_id=user_row["id"], visibility="owner-only")
    kb.save_chunks(sid, [KBChunk(0, [0], f"A: {text}", 10)])
    return ws["id"]


@pytestmark_db
def test_search_unauthenticated_401(client):
    assert client.post(
        "/api/workspaces/w/search", json={"query": "x"}
    ).status_code == 401


@pytestmark_db
def test_search_bm25_only_when_embedder_down(client, monkeypatch):
    wsid = _seed(client, "s1@example.com", "kb-se-1",
                 "we discussed attestation verification for enclaves")

    def _broken(texts, **kw):
        raise RuntimeError("embedder down")
    monkeypatch.setattr("transcripts.embed.embed_texts", _broken)

    r = client.post(f"/api/workspaces/{wsid}/search",
                    json={"query": "attestation"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert results and results[0]["chunk_id"] == "kb-se-1:0"
    assert "attestation" in results[0]["snippet"]
    assert results[0]["meeting"]["session_id"] == "kb-se-1"


@pytestmark_db
def test_search_visibility_isolation(client, monkeypatch):
    _seed(client, "owner2@example.com", "kb-se-2",
          "secret roadmap discussion about funding")
    client.cookies.clear()
    # another user, own workspace — must see nothing
    wsid_other = _seed(client, "other@example.com", "kb-se-1",
                       "completely unrelated chatter")
    monkeypatch.setattr(
        "transcripts.embed.embed_texts",
        lambda texts, **kw: (_ for _ in ()).throw(RuntimeError("no vec")),
    )
    r = client.post(f"/api/workspaces/{wsid_other}/search",
                    json={"query": "funding roadmap secret"})
    assert r.status_code == 200
    assert all(
        res["session_id"] != "kb-se-2" for res in r.json()["results"]
    )


@pytestmark_db
def test_search_body_validation(client):
    wsid = _seed(client, "v@example.com", "kb-se-1", "hello world")
    assert client.post(
        f"/api/workspaces/{wsid}/search", json={"query": ""}
    ).status_code == 422
    assert client.post(
        f"/api/workspaces/{wsid}/search", json={"query": "x", "top_k": 9999}
    ).status_code == 422
