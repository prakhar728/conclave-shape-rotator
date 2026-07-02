"""Task #39 — meeting time-of-day.

`metadata.date` is date-granular; the full server-stamped ingest timestamp lives
in the `transcript_sessions.created_at` column but was never projected onto the
`Session` / DTOs. This exposes it read-only for time-of-day rendering.
"""
from __future__ import annotations

from api.transcripts_routes import to_card, to_view
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


def _save(sid: str) -> Session:
    sess = Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text="hi", start=0.0)],
        metadata=SessionMetadata(date="2026-07-02", source="capture", platform="inperson"),
        derived=Derived(summary="s"),
    )
    store.save_session(sess)
    return sess


def test_created_at_projected_onto_loaded_session():
    _save("ca-1")
    loaded = store.load_session("ca-1")
    assert loaded is not None
    # Full UTC ISO timestamp (has a clock time, not just a date), authoritative DB stamp.
    assert loaded.created_at is not None
    assert loaded.created_at.endswith("Z")
    assert "T" in loaded.created_at  # date + time, not date-only


def test_freshly_built_session_has_no_created_at():
    """An in-memory Session that hasn't round-tripped through the store carries None
    (the FE degrades to the date-only display)."""
    sess = Session(
        session_id="mem",
        raw_diarization=[RawSegment(speaker="A", text="hi", start=0.0)],
        metadata=SessionMetadata(date="2026-07-02", source="otter"),
    )
    assert sess.created_at is None


def test_to_card_and_to_view_expose_created_at():
    _save("ca-2")
    loaded = store.load_session("ca-2")
    card = to_card(loaded)
    assert card["created_at"] == loaded.created_at
    assert to_view(loaded)["created_at"] == loaded.created_at


def test_created_at_is_immutable_across_resave():
    """created_at is stamped once at insert and never overwritten (re-save only
    touches metadata/derived)."""
    _save("ca-3")
    first = store.load_session("ca-3").created_at
    # Re-save (e.g. an enrich pass) updates derived but must not move created_at.
    s = store.load_session("ca-3")
    s.derived = Derived(summary="updated")
    store.save_session(s)
    assert store.load_session("ca-3").created_at == first
