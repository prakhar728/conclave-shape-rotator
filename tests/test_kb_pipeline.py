"""Phase 3.5a C10 — KB ingest pipeline integration (chunk→header→embed→index).

Real store + real SQLite (conftest-migrated); LLM + embeddings faked by
monkeypatch so no Ollama/RedPill dependency.
"""
from __future__ import annotations

import pytest

from storage import kb
from storage.sqlite import _get_conn
from storage.vec import vec_available
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata
from transcripts.kb_pipeline import index_session

pytestmark = pytest.mark.skipif(
    not vec_available(_get_conn()),
    reason="sqlite-vec not loaded on this connection",
)

SID = "kb-pipe-1"


@pytest.fixture(autouse=True)
def _session():
    s = Session(
        session_id=SID,
        raw_diarization=[
            RawSegment(speaker="Ada", text="We shipped the importer today.", start=0.0, end=5.0),
            RawSegment(speaker="Bob", text="Great, I will write the announcement.", start=5.0, end=9.0),
        ],
        metadata=SessionMetadata(date="2026-06-03", source="test", tags=[]),
        derived=Derived(),
    )
    store.save_session(s)
    yield
    kb.delete_chunks_for_session(SID)
    _get_conn().execute("DELETE FROM embeddings WHERE source_id LIKE ?", (f"{SID}%",))
    _get_conn().execute("DELETE FROM transcript_sessions WHERE session_id = ?", (SID,))


def _fake_embed(texts, *, kind="document", model_id="m", transport=None):
    return [[0.5] * 768 for _ in texts]


def test_index_session_end_to_end(monkeypatch):
    monkeypatch.setattr("transcripts.kb_pipeline.embed_texts", _fake_embed)
    monkeypatch.setattr(
        "transcripts.kb_pipeline.generate_header", lambda text, meta: "a header"
    )
    metrics = index_session(SID)
    assert metrics is not None
    assert metrics["chunks"] >= 1
    assert metrics["headers_nonempty"] == metrics["chunks"]
    assert metrics["embedded"] == metrics["chunks"]

    rows = kb.query_chunks_for_session(SID)
    assert rows and rows[0]["context_header"] == "a header"
    # FTS finds transcript content
    assert kb.fts_search_chunks("importer", session_ids=[SID])
    # vec index populated
    hits = kb.vec_search_chunks([0.5] * 768, k=1, session_ids=[SID])
    assert hits and hits[0]["session_id"] == SID


def test_index_session_header_failure_degrades(monkeypatch):
    monkeypatch.setattr("transcripts.kb_pipeline.embed_texts", _fake_embed)
    monkeypatch.setattr(
        "transcripts.kb_pipeline.generate_header", lambda text, meta: ""
    )
    metrics = index_session(SID)
    assert metrics["headers_nonempty"] == 0
    # chunks still stored + FTS-searchable
    assert kb.fts_search_chunks("announcement", session_ids=[SID])


def test_index_session_embed_failure_keeps_fts(monkeypatch):
    from transcripts.embed import EmbeddingUnavailable

    def _broken(texts, **kw):
        raise EmbeddingUnavailable("ollama down")

    monkeypatch.setattr("transcripts.kb_pipeline.embed_texts", _broken)
    metrics = index_session(SID, with_headers=False)
    assert metrics["embedded"] == 0
    assert kb.fts_search_chunks("importer", session_ids=[SID])
    assert kb.vec_search_chunks([0.5] * 768, k=1, session_ids=[SID]) == []


def test_index_session_idempotent_rerun(monkeypatch):
    monkeypatch.setattr("transcripts.kb_pipeline.embed_texts", _fake_embed)
    index_session(SID, with_headers=False)
    index_session(SID, with_headers=False)  # re-run must not duplicate
    rows = kb.query_chunks_for_session(SID)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    conn = _get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source_id = ?", (f"{SID}:0",)
    ).fetchone()[0]
    assert cnt == 1


def test_index_session_missing_session():
    assert index_session("does-not-exist") is None
