"""Shared connective layer for external-dataset evaluations.

This is the reusable asset both the component eval (QMSum/AMI) and the
later cross-session eval sit on top of. It pushes a normalized list of
meetings through the **real production ingest seam** so every eval
re-measures whatever the live pipeline currently does:

    store.save_session  ->  kb_pipeline.index_session  (chunk->header->embed->index)
                            [+ extract_session, behind ENABLE_KB_PIPELINE]

`index_session` is the exact call the ingest webhook makes after
enrichment (`api/transcripts_routes.py`). We deliberately do NOT
hand-rewire chunk->embed->index here (that is how
`tests/test_search_regression.py` can silently drift from the product):
if those internals change, only `index_session` changes, and this layer
— plus every eval built on it — tracks the change for free.

Normalized meeting form (one dict per meeting)::

    {
      "session_id": str,                       # unique id in the eval DB
      "segments": [{"speaker": str, "text": str}, ...],
      "date": str | None,                      # ISO YYYY-MM-DD (default EVAL_DATE)
      "source": str,                           # default "eval"
      "owner": str | None,                     # for Phase-3 permission evals
      "visibility": str,                       # default "cohort"
    }

Re-ingest is idempotent (chunks + session row are replaced), so a scorer
can be re-run against a warm DB safely.
"""
from __future__ import annotations

import logging
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

logger = logging.getLogger("eval.ingest_harness")

#: Fixed date for eval sessions (deterministic; no real meeting date).
EVAL_DATE = "2026-01-01"


def ensure_schema(db_path: str) -> str:
    """Point storage at ``db_path`` and bring it to full schema.

    Mirrors ``tests/conftest.py``: create the legacy ``transcript_sessions``
    schema first (so Alembic's ALTERs have something to touch), then run
    ``alembic upgrade head`` to add the KB tables (chunks / embeddings /
    chunks_vec / users / workspaces / ...). Safe to call repeatedly.
    """
    db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.environ["CONCLAVE_DB_PATH"] = db_path

    from storage import sqlite as _sqlite

    _sqlite._DB_PATH = db_path
    _sqlite._conn = None
    _sqlite._get_conn()  # legacy schema (transcript_sessions) before Alembic

    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(_REPO, "alembic.ini"))
    os.environ["CONCLAVE_DB_URL"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")
    logger.info("eval DB ready at %s", db_path)
    return db_path


def ingest_meeting(meeting: dict, *, with_headers: bool = False) -> dict | None:
    """Save + index one normalized meeting through the production seam.

    ``with_headers`` defaults to False: the in-sample 0.814 baseline in
    ``transcripts/EVAL.md`` was measured headers-off, and headers cost a
    per-chunk LLM call. Flip it on to measure the full production default.

    Returns ``index_session``'s stage-timing/count dict (or None if the
    meeting had no usable segments).
    """
    from storage import kb
    from transcripts import store
    from transcripts.kb_pipeline import index_session
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata

    sid = meeting["session_id"]
    segments = meeting["segments"]

    # Idempotent re-ingest: drop prior chunks (FK children) before the row.
    kb.delete_chunks_for_session(sid)
    session = Session(
        session_id=sid,
        raw_diarization=[
            RawSegment(speaker=s["speaker"], text=s["text"]) for s in segments
        ],
        metadata=SessionMetadata(
            date=meeting.get("date") or EVAL_DATE,
            source=meeting.get("source", "eval"),
            tags=[],
            visibility=meeting.get("visibility", "cohort"),
            owner=meeting.get("owner"),
        ),
        derived=Derived(),
    )
    store.replace_session(session)  # delete + save -> raw-write-once safe re-run
    return index_session(sid, with_headers=with_headers)


def ingest_corpus(
    meetings: list[dict], *, with_headers: bool = False, log_every: int = 5
) -> list[tuple[str, dict | None]]:
    """Ingest a list of normalized meetings; returns [(session_id, metrics)]."""
    out: list[tuple[str, dict | None]] = []
    total = len(meetings)
    for i, m in enumerate(meetings):
        metrics = ingest_meeting(m, with_headers=with_headers)
        out.append((m["session_id"], metrics))
        if (i + 1) % log_every == 0 or (i + 1) == total:
            emb = sum(1 for _, mx in out if mx and mx.get("embedded"))
            print(
                f"  ingested {i + 1}/{total} meetings "
                f"({emb} with embeddings)",
                flush=True,
            )
    return out
