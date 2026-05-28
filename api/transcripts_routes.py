"""Read-only HTTP surface for the transcripts dashboard.

`IMPLEMENTATION_PLAN.md` §G12 / §H C10. Two endpoints — both return only
the **derived projection** of a session, never the raw diarization. The
``raw_diarization`` field is the immutable input bytes (`§A`); leaking it
into a response would defeat the whole point of separating raw from
derived. ``test_api_transcripts.py`` enforces this with an explicit
no-raw-anywhere assertion.

Permissions in Phase 1: ``can_see`` is a stub that returns ``True`` for
everyone (the all-access posture from `§L`). Phase 1.5 implements real
``can_see(viewer, session)`` — that's the **one function** to change
when membership-based permissions land.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from transcripts import store
from transcripts.models import Session


router = APIRouter(prefix="/transcripts", tags=["transcripts"])


# ---------------------------------------------------------------------------
# Permission stub — the seam Phase 1.5 swaps
# ---------------------------------------------------------------------------

def can_see(viewer: Optional[str], session: Session) -> bool:
    """Phase-1 stub: everyone sees everything.

    The viewer arg is the seat for 1.5's real check
    (``session.metadata.visibility == "cohort"`` + membership lookup,
    or ``owner-only`` + viewer == owner). Defined now so the dashboard
    can already call it; the body changes at 1.5 without a signature change.
    """
    _ = viewer  # unused in Phase 1
    return True


# ---------------------------------------------------------------------------
# Projection: derived-only "card" shape
# ---------------------------------------------------------------------------

def to_card(session: Session) -> dict:
    """Minimal payload for a dashboard card — newest-first list view.

    NEVER includes ``raw_diarization``. Includes the resolved-speaker chips
    so the card can render real names + record_ids from C5 immediately.
    ``seed`` is a stable per-session string the shape-ui glyph uses so the
    same session always renders the same shape.
    """
    d = session.derived
    return {
        "session_id": session.session_id,
        "date": session.metadata.date,
        "source": session.metadata.source,
        "summary": d.summary,
        "signal_count": len(d.signals or []),
        "entity_count": len(d.entities or []),
        "chunk_count": session.metadata.chunk_count,
        "model_id": session.metadata.model_id,
        "enrich_prompt_version": session.metadata.enrich_prompt_version,
        "resolved_speakers": dict(session.metadata.resolved_speakers or {}),
        "seed": session.session_id,
    }


def to_view(session: Session) -> dict:
    """Detail view — card payload + the full derived signals & entities.

    Still no raw_diarization. The dashboard's per-session detail panel
    consumes this shape; signal/entity counts in ``to_card`` come straight
    from the lengths of these arrays so the two surfaces never disagree.
    """
    card = to_card(session)
    d = session.derived
    card.update({
        "signals": [s.model_dump() for s in (d.signals or [])],
        "entities": [e.model_dump() for e in (d.entities or [])],
        # Derived's `graph_nodes` field is Phase-2 territory but listing
        # it here keeps the response shape stable across phases.
        "graph_nodes": d.graph_nodes,
    })
    return card


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/sessions")
def list_sessions(
    source: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Newest-first list of session cards. Phase-1 all-access."""
    sessions = store.list_sessions(source=source, date_from=date_from, date_to=date_to)
    # Most-recent first by date (then session_id for a stable tiebreaker).
    sessions.sort(key=lambda s: (s.metadata.date, s.session_id), reverse=True)
    return [to_card(s) for s in sessions if can_see(None, s)]


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    if not can_see(None, session):
        # Phase 1.5: this becomes a real 403 with a proper auth context.
        raise HTTPException(status_code=403, detail="not allowed")
    return to_view(session)
