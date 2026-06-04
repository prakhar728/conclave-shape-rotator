"""KB storage helpers — chunks, embeddings, FTS + vec search (3.5a C9).

Build plan nominally appends these to ``storage/sqlite.py``; split into
a module instead (same connection seam, ``storage.sqlite._get_conn``)
to keep that file from growing unbounded. All tables come from Alembic
0006 — nothing here creates schema.

Conventions:
- chunk id = ``{session_id}:{chunk_index}`` (deterministic, re-chunk
  produces the same ids)
- ``save_chunks`` is delete-then-insert per session (idempotent);
  FTS rows ride along via triggers, ``chunks_vec`` rows are purged
  explicitly (no triggers possible — embeddings land later)
- ``embeddings`` stores the full-dim vector model-keyed;
  ``chunks_vec`` stores the 256-dim Matryoshka truncation keyed by
  ``chunks.rowid``
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from storage.sqlite import _get_conn, _now
from storage.vec import VEC_DIM
from transcripts.embed import serialize_f32, truncate_matryoshka


def chunk_id(session_id: str, chunk_index: int) -> str:
    return f"{session_id}:{chunk_index}"


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------

def save_chunks(session_id: str, chunks: list, *, headers: Optional[list[str]] = None) -> int:
    """Replace a session's chunks (delete-then-insert; idempotent).

    ``chunks``: KBChunk instances or dicts with chunk_index/turn_ids/
    text/token_count. ``headers``: optional parallel list of context
    headers (defaults to empty strings).
    """
    conn = _get_conn()
    delete_chunks_for_session(session_id)
    now = _now()
    n = 0
    for i, c in enumerate(chunks):
        d = c if isinstance(c, dict) else c.__dict__
        header = (headers[i] if headers and i < len(headers) else "") or ""
        conn.execute(
            """
            INSERT INTO chunks
                (id, session_id, chunk_index, turn_ids, text,
                 context_header, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id(session_id, d["chunk_index"]),
                session_id,
                d["chunk_index"],
                json.dumps(d["turn_ids"]),
                d["text"],
                header,
                d["token_count"],
                now,
            ),
        )
        n += 1
    return n


def delete_chunks_for_session(session_id: str) -> int:
    """Remove a session's chunks + their vec rows (FTS rides triggers)."""
    conn = _get_conn()
    rowids = [
        r[0] for r in conn.execute(
            "SELECT rowid FROM chunks WHERE session_id = ?", (session_id,)
        ).fetchall()
    ]
    if rowids:
        qs = ",".join("?" * len(rowids))
        try:
            conn.execute(f"DELETE FROM chunks_vec WHERE rowid IN ({qs})", rowids)
        except Exception:  # noqa: BLE001 — vec table absent when ext unloadable
            pass
    cur = conn.execute("DELETE FROM chunks WHERE session_id = ?", (session_id,))
    return cur.rowcount


def query_chunks_for_session(session_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT id, session_id, chunk_index, turn_ids, text, context_header,"
        " token_count, created_at FROM chunks WHERE session_id = ?"
        " ORDER BY chunk_index",
        (session_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "session_id": r["session_id"],
            "chunk_index": r["chunk_index"],
            "turn_ids": json.loads(r["turn_ids"]),
            "text": r["text"],
            "context_header": r["context_header"],
            "token_count": r["token_count"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def save_chunk_embeddings(
    session_id: str,
    vectors: dict[str, list[float]],
    *,
    model_id: str,
) -> int:
    """Persist full-dim vectors + refresh the ANN index for a session.

    ``vectors``: chunk_id → full-dim embedding. Upserts ``embeddings``
    on (source_kind, source_id, model_id); rewrites the matching
    ``chunks_vec`` rows (delete+insert keyed by chunks.rowid).
    """
    conn = _get_conn()
    now = _now()
    n = 0
    for cid, vec in vectors.items():
        row = conn.execute(
            "SELECT rowid FROM chunks WHERE id = ?", (cid,)
        ).fetchone()
        if row is None:
            continue  # chunk vanished (re-chunk raced) — skip quietly
        rowid = row[0]
        conn.execute(
            """
            INSERT INTO embeddings
                (id, source_kind, source_id, model_id, dim, vec, created_at)
            VALUES (?, 'chunk', ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, source_id, model_id) DO UPDATE SET
                dim = excluded.dim, vec = excluded.vec,
                created_at = excluded.created_at
            """,
            (
                f"emb:chunk:{cid}:{model_id}",
                cid,
                model_id,
                len(vec),
                serialize_f32(vec),
                now,
            ),
        )
        truncated = truncate_matryoshka(vec, VEC_DIM)
        conn.execute("DELETE FROM chunks_vec WHERE rowid = ?", (rowid,))
        conn.execute(
            "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
            (rowid, serialize_f32(truncated)),
        )
        n += 1
    return n


def get_embedding(source_kind: str, source_id: str, model_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, source_kind, source_id, model_id, dim, vec, created_at"
        " FROM embeddings WHERE source_kind = ? AND source_id = ? AND model_id = ?",
        (source_kind, source_id, model_id),
    ).fetchone()
    if row is None:
        return None
    from transcripts.embed import deserialize_f32
    return {
        "id": row["id"],
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "model_id": row["model_id"],
        "dim": row["dim"],
        "vec": deserialize_f32(row["vec"]),
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _fts_sanitize(query: str) -> str:
    """User text → safe FTS5 MATCH expression: quoted terms, OR-joined.

    Strips FTS operators/punctuation outright — search-box input should
    never be able to throw a MATCH syntax error.

    OR (not implicit AND) because natural-language queries carry
    stopwords that rarely co-occur in one chunk; BM25's rank already
    rewards multi-term matches, so OR recall + rank ordering is the
    right BM25 idiom. (Found by C24: the FTS leg scored NDCG 0.000 on
    question-shaped eval queries under AND semantics.)
    """
    terms = _FTS_TOKEN_RE.findall(query)
    return " OR ".join(f'"{t}"' for t in terms)


def fts_search_chunks(
    query: str,
    *,
    limit: int = 20,
    session_ids: Optional[Iterable[str]] = None,
) -> list[dict]:
    """BM25 (FTS5 rank) search over text + context_header.

    Returns [{chunk_id, session_id, rank}] best-first. ``session_ids``
    optionally restricts (per-meeting visibility filtering happens at
    the route layer; this is the mechanism).
    """
    expr = _fts_sanitize(query)
    if not expr:
        return []
    conn = _get_conn()
    sql = (
        "SELECT c.id AS chunk_id, c.session_id AS session_id, f.rank AS rank"
        " FROM chunks_fts f JOIN chunks c ON c.rowid = f.rowid"
        " WHERE chunks_fts MATCH ?"
    )
    params: list = [expr]
    if session_ids is not None:
        ids = list(session_ids)
        if not ids:
            return []
        sql += f" AND c.session_id IN ({','.join('?' * len(ids))})"
        params.extend(ids)
    sql += " ORDER BY f.rank LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        {"chunk_id": r["chunk_id"], "session_id": r["session_id"], "rank": r["rank"]}
        for r in rows
    ]


def vec_search_chunks(
    query_vec: list[float],
    *,
    k: int = 20,
    session_ids: Optional[Iterable[str]] = None,
) -> list[dict]:
    """Dense ANN search via sqlite-vec. ``query_vec`` may be full-dim
    (gets Matryoshka-truncated to the index dim) or already index-dim.

    Returns [{chunk_id, session_id, distance}] nearest-first. Session
    filtering applies post-ANN (vec0 KNN can't take arbitrary WHERE),
    so we over-fetch when filtering.
    """
    if len(query_vec) != VEC_DIM:
        query_vec = truncate_matryoshka(query_vec, VEC_DIM)
    conn = _get_conn()
    fetch_k = k * 4 if session_ids is not None else k
    rows = conn.execute(
        "SELECT v.rowid AS rowid, v.distance AS distance"
        " FROM chunks_vec v WHERE v.embedding MATCH ? AND v.k = ?",
        (serialize_f32(query_vec), fetch_k),
    ).fetchall()
    if not rows:
        return []
    rowids = [r["rowid"] for r in rows]
    qs = ",".join("?" * len(rowids))
    chunk_rows = conn.execute(
        f"SELECT rowid, id, session_id FROM chunks WHERE rowid IN ({qs})", rowids
    ).fetchall()
    by_rowid = {r["rowid"]: (r["id"], r["session_id"]) for r in chunk_rows}
    allowed = set(session_ids) if session_ids is not None else None
    out = []
    for r in rows:
        info = by_rowid.get(r["rowid"])
        if info is None:
            continue  # orphan vec row
        cid, sid = info
        if allowed is not None and sid not in allowed:
            continue
        out.append({"chunk_id": cid, "session_id": sid, "distance": r["distance"]})
        if len(out) >= k:
            break
    return out
