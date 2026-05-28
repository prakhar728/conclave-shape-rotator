"""Typed persistence for sessions over `storage.sqlite`.

Thin translation between `Session` models and the `transcript_sessions` table.
The immutability contract lives in the storage layer: `save_session` will not
overwrite `raw_diarization` once a row exists, so re-running enrichment only
moves `derived`/`metadata` forward.
"""
from __future__ import annotations

from typing import Optional

from storage import sqlite
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


def save_session(session: Session) -> None:
    sqlite.save_transcript_session(
        session_id=session.session_id,
        source=session.metadata.source,
        session_date=session.metadata.date,
        raw_diarization=[s.model_dump() for s in session.raw_diarization],
        metadata=session.metadata.model_dump(),
        derived=session.derived.model_dump(),
    )


def load_session(session_id: str) -> Optional[Session]:
    row = sqlite.get_transcript_session(session_id)
    return _row_to_session(row) if row else None


def list_sessions(
    source: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[Session]:
    rows = sqlite.list_transcript_sessions(source=source, date_from=date_from, date_to=date_to)
    return [_row_to_session(r) for r in rows]


def set_derived(session_id: str, derived: Derived) -> None:
    sqlite.update_transcript_derived(session_id, derived.model_dump())


def set_metadata(session_id: str, metadata: SessionMetadata) -> None:
    sqlite.update_transcript_metadata(session_id, metadata.model_dump())


def replace_session(session: Session) -> None:
    """Hard-replace a session row (delete + save). Use only for `--force` ingest;
    the default ingest path is `save_session` (raw-write-once)."""
    sqlite.delete_transcript_session(session.session_id)
    save_session(session)


def set_visibility(
    session_id: str,
    visibility: str,
    owner: Optional[str] = None,
) -> None:
    """Phase-1.5 hook (declared now): update the visibility/owner fields.

    Lives in the JSON metadata column → no SQL migration. Phase-1.5 promotes
    `visibility` to a typed column when permission filtering needs SQL pushdown.
    """
    current = load_session(session_id)
    if current is None:
        raise KeyError(session_id)
    md = current.metadata.model_copy(update={"visibility": visibility, "owner": owner})
    set_metadata(session_id, md)


def list_pending(current_prompt_version: Optional[str] = None) -> list[Session]:
    """Sessions that still need enrichment.

    Pending = `derived.summary` is empty OR the stored
    `metadata.enrich_prompt_version` doesn't match the caller's current
    version (the backfill key). Python-side filter for Phase 1 — small N
    (`IMPLEMENTATION_PLAN.md` §E). Promote to a typed column when scale grows.
    """
    out: list[Session] = []
    for s in list_sessions():
        derived_empty = not (s.derived and s.derived.summary)
        stale = (
            current_prompt_version is not None
            and s.metadata.enrich_prompt_version is not None
            and s.metadata.enrich_prompt_version != current_prompt_version
        )
        if derived_empty or stale:
            out.append(s)
    return out


def _row_to_session(row: dict) -> Session:
    return Session(
        session_id=row["session_id"],
        raw_diarization=[RawSegment(**s) for s in row["raw_diarization"]],
        metadata=SessionMetadata(**row["metadata"]),
        derived=Derived(**row["derived"]),
    )
