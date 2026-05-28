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


def _row_to_session(row: dict) -> Session:
    return Session(
        session_id=row["session_id"],
        raw_diarization=[RawSegment(**s) for s in row["raw_diarization"]],
        metadata=SessionMetadata(**row["metadata"]),
        derived=Derived(**row["derived"]),
    )
