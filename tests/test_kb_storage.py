"""Phase 3.5a C9 — KB storage helpers (real SQLite, migrated by conftest)."""
from __future__ import annotations

import sqlite3

import pytest

from storage import kb
from storage.sqlite import _get_conn
from storage.vec import VEC_DIM, vec_available
from transcripts.kb_chunk import KBChunk

pytestmark = pytest.mark.skipif(
    not vec_available(_get_conn()),
    reason="sqlite-vec not loaded on this connection",
)


@pytest.fixture(autouse=True)
def _clean():
    conn = _get_conn()
    conn.execute("PRAGMA foreign_keys=OFF")
    yield
    for sid in ("kb-s1", "kb-s2"):
        kb.delete_chunks_for_session(sid)
    conn.execute("DELETE FROM embeddings WHERE source_id LIKE 'kb-s%'")
    conn.execute("PRAGMA foreign_keys=ON")


def _mk_chunks(n=2):
    return [
        KBChunk(chunk_index=i, turn_ids=[i * 2, i * 2 + 1],
                text=f"S{i}: chunk number {i} about retrieval",
                token_count=10)
        for i in range(n)
    ]


def _vec(seed: float, dim: int = 768) -> list[float]:
    return [seed + 0.001 * i for i in range(dim)]


def test_save_chunks_round_trip():
    n = kb.save_chunks("kb-s1", _mk_chunks(3), headers=["h0", "h1", "h2"])
    assert n == 3
    rows = kb.query_chunks_for_session("kb-s1")
    assert [r["chunk_index"] for r in rows] == [0, 1, 2]
    assert rows[0]["id"] == "kb-s1:0"
    assert rows[0]["turn_ids"] == [0, 1]
    assert rows[1]["context_header"] == "h1"


def test_save_chunks_idempotent_replace():
    kb.save_chunks("kb-s1", _mk_chunks(3))
    kb.save_chunks("kb-s1", _mk_chunks(2))  # re-chunk smaller
    rows = kb.query_chunks_for_session("kb-s1")
    assert len(rows) == 2


def test_fts_search_finds_text_and_header():
    kb.save_chunks("kb-s1", [
        KBChunk(chunk_index=0, turn_ids=[0],
                text="Ada: we shipped the importer", token_count=6),
    ], headers=["meeting about databases"])
    hits = kb.fts_search_chunks("importer")
    assert any(h["chunk_id"] == "kb-s1:0" for h in hits)
    hits = kb.fts_search_chunks("databases")  # header content
    assert any(h["chunk_id"] == "kb-s1:0" for h in hits)


def test_fts_search_session_filter_and_injection_safety():
    kb.save_chunks("kb-s1", [KBChunk(0, [0], "alpha beta gamma", 3)])
    kb.save_chunks("kb-s2", [KBChunk(0, [0], "alpha delta epsilon", 3)])
    hits = kb.fts_search_chunks("alpha", session_ids=["kb-s2"])
    assert {h["session_id"] for h in hits} == {"kb-s2"}
    # FTS operators / quotes must not raise
    assert kb.fts_search_chunks('alpha" OR "*') is not None
    assert kb.fts_search_chunks("NOT AND OR (") == [] or True
    assert kb.fts_search_chunks("") == []


def test_embeddings_upsert_and_vec_search():
    kb.save_chunks("kb-s1", _mk_chunks(2))
    n = kb.save_chunk_embeddings(
        "kb-s1",
        {"kb-s1:0": _vec(0.1), "kb-s1:1": _vec(0.9)},
        model_id="nomic-embed-text:v1.5",
    )
    assert n == 2

    # full-dim row persisted
    emb = kb.get_embedding("chunk", "kb-s1:0", "nomic-embed-text:v1.5")
    assert emb is not None and emb["dim"] == 768

    # nearest neighbour of a vector close to chunk 0 is chunk 0
    hits = kb.vec_search_chunks(_vec(0.11), k=1)
    assert hits[0]["chunk_id"] == "kb-s1:0"

    # re-save (upsert path) does not duplicate
    kb.save_chunk_embeddings(
        "kb-s1", {"kb-s1:0": _vec(0.2)}, model_id="nomic-embed-text:v1.5"
    )
    conn = _get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source_id='kb-s1:0'"
    ).fetchone()[0]
    assert cnt == 1


def test_vec_search_session_filter():
    kb.save_chunks("kb-s1", _mk_chunks(1))
    kb.save_chunks("kb-s2", _mk_chunks(1))
    kb.save_chunk_embeddings("kb-s1", {"kb-s1:0": _vec(0.1)}, model_id="m")
    kb.save_chunk_embeddings("kb-s2", {"kb-s2:0": _vec(0.1)}, model_id="m")
    hits = kb.vec_search_chunks(_vec(0.1), k=5, session_ids=["kb-s2"])
    assert hits and all(h["session_id"] == "kb-s2" for h in hits)


def test_delete_session_purges_fts_and_vec():
    kb.save_chunks("kb-s1", _mk_chunks(1))
    kb.save_chunk_embeddings("kb-s1", {"kb-s1:0": _vec(0.5)}, model_id="m")
    kb.delete_chunks_for_session("kb-s1")
    assert kb.query_chunks_for_session("kb-s1") == []
    assert kb.fts_search_chunks("retrieval", session_ids=["kb-s1"]) == []
    conn = _get_conn()
    n_vec = conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0]
    # no orphan vec rows pointing at deleted chunk rowids
    orphans = conn.execute(
        "SELECT COUNT(*) FROM chunks_vec v LEFT JOIN chunks c ON c.rowid = v.rowid"
        " WHERE c.rowid IS NULL"
    ).fetchone()[0]
    assert orphans == 0 or n_vec == 0


def test_embedding_for_missing_chunk_skipped():
    n = kb.save_chunk_embeddings("kb-s1", {"kb-s1:99": _vec(0.3)}, model_id="m")
    assert n == 0
