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
from pydantic import BaseModel

from transcripts import store
from transcripts.models import Session


router = APIRouter(prefix="/transcripts", tags=["transcripts"])


# ---------------------------------------------------------------------------
# Permission layer — demo-hardcoded (Phase 1.5 swaps `_resolve_viewer` to
# a real auth callback; the rule + endpoint surface stay identical).
# See IMPLEMENTATION_PLAN.md §D.1 for the full rationale.
# ---------------------------------------------------------------------------

def _resolve_viewer(viewer: Optional[str]) -> Optional[str]:
    """One-line seam between the public endpoint and `can_see`.

    Today: trust the `?viewer=<record_id>` query param verbatim — no
    auth, no verification (the demo posture). Phase 1.5 replaces this
    with an OAuth/cookie callback that returns the authenticated
    record_id (or None if anonymous). The signature stays the same so
    every call site is unaffected.
    """
    return viewer


def can_see(viewer: Optional[str], session: Session) -> bool:
    """Demo permission rule (§D.1).

    1. `visibility == "cohort"` (default) → True for everyone, anonymous
       included. This keeps existing dashboards working without any
       viewer threading.
    2. `visibility == "owner-only"` and viewer is None → False.
    3. Owner sees their own session.
    4. A viewer whose `record_id` matches any speaker's `record_id` in
       `resolved_speakers` sees the session (you can see meetings you
       spoke in).
    5. Otherwise False.

    Phase 1.5 supersedes this with the real `auth.py` check; the
    rule's structure stays the same so the contract doesn't move.
    """
    md = session.metadata
    if (md.visibility or "cohort") == "cohort":
        return True
    if viewer is None:
        return False
    if md.owner and md.owner == viewer:
        return True
    for sp_meta in (md.resolved_speakers or {}).values():
        if isinstance(sp_meta, dict) and sp_meta.get("record_id") == viewer:
            return True
    return False


# ---------------------------------------------------------------------------
# Projection: derived-only "card" shape
# ---------------------------------------------------------------------------

def to_card(session: Session) -> dict:
    """Minimal payload for a dashboard card — newest-first list view.

    NEVER includes ``raw_diarization``. Includes the resolved-speaker chips
    so the card can render real names + record_ids from C5 immediately.
    ``seed`` is a stable per-session string the shape-ui glyph uses so the
    same session always renders the same shape.

    v1/v2 additions (post-PoC): ``topics`` for meeting-list filtering,
    ``participants_count`` for the audience-size pill, plus provenance
    (``team_context_version``) so dashboard URLs can be deep-linked to a
    specific v2 enrichment baseline.
    """
    d = session.derived
    m = session.metadata
    participants = m.participants if m.participants else None
    return {
        "session_id": session.session_id,
        "date": m.date,
        "source": m.source,
        "summary": d.summary,
        "signal_count": len(d.signals or []),
        "entity_count": len(d.entities or []),
        "chunk_count": m.chunk_count,
        "model_id": m.model_id,
        "enrich_prompt_version": m.enrich_prompt_version,
        "team_context_version": m.team_context_version,
        "resolved_speakers": dict(m.resolved_speakers or {}),
        "topics": list(d.topics or []),
        "participants": list(participants) if participants else None,
        "participants_count": len(participants) if participants else None,
        "seed": session.session_id,
    }


#: Signal kinds in the order we want them rendered on the dashboard
#: (decision-led, then commitments, then opens, then color-coded context).
#: Keys are the JSON-friendly pluralised names served under
#: ``signals_by_kind``; values are the matching ``Signal.kind`` strings.
_SIGNAL_KIND_GROUPS: list[tuple[str, str]] = [
    ("decisions",        "decision"),        # decision-led, lands first
    ("action_items",     "action_item"),     # commitments, second
    ("open_questions",   "open_question"),   # unresolved threads, third
    ("impactful_points", "impactful_point"), # consequential facts, fourth
    ("insights",         "insight"),         # non-obvious observations, last
]


def to_view(session: Session) -> dict:
    """Detail view — card payload + the full derived signals & entities.

    Still no raw_diarization. The dashboard's per-session detail panel
    consumes this shape; signal/entity counts in ``to_card`` come straight
    from the lengths of these arrays so the two surfaces never disagree.

    Signals carry the v1 schema additions (``said_by`` / ``about_person``
    / ``source_quote``) and entities carry ``cohort_status`` /
    ``affiliation`` — all surfaced via ``model_dump()`` so the JSON shape
    tracks the model automatically. Raw transcript content
    (``raw_diarization``) remains the only field stripped at the API
    boundary; ``source_quote`` IS served (TEE is the privacy boundary,
    not the API field surface — see IMPLEMENTATION_PLAN v1 §3).

    v1.1: ``signals_by_kind`` is a convenience server-side grouping so the
    dashboard can render distinct sections ("DECISIONS", "ACTION ITEMS",
    "OPEN QUESTIONS"…) without re-filtering ``signals[]`` client-side.
    The flat ``signals[]`` array is also still served, in original model
    order, for callers that want it.
    """
    card = to_card(session)
    d = session.derived
    flat_signals = [s.model_dump() for s in (d.signals or [])]
    signals_by_kind = {
        plural: [s for s in flat_signals if s.get("kind") == kind]
        for plural, kind in _SIGNAL_KIND_GROUPS
    }
    card.update({
        "signals": flat_signals,
        "signals_by_kind": signals_by_kind,
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
    viewer: Optional[str] = None,
) -> list[dict]:
    """Newest-first list of session cards, filtered by `can_see`.

    `viewer` is the demo-hardcoded identity hint (see `_resolve_viewer`).
    Omit it and the caller is anonymous; cohort-visible sessions still
    return (default visibility is "cohort"), so the existing dashboard
    keeps working unchanged.
    """
    v = _resolve_viewer(viewer)
    sessions = store.list_sessions(source=source, date_from=date_from, date_to=date_to)
    # Most-recent first by date (then session_id for a stable tiebreaker).
    sessions.sort(key=lambda s: (s.metadata.date, s.session_id), reverse=True)
    return [to_card(s) for s in sessions if can_see(v, s)]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, viewer: Optional[str] = None) -> dict:
    v = _resolve_viewer(viewer)
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    if not can_see(v, session):
        raise HTTPException(status_code=403, detail="not allowed")
    return to_view(session)


# ---------------------------------------------------------------------------
# Visibility toggle — P3 (§D.1). Owner-gated. Body carries the viewer
# (the demo identity) because there's no auth header yet; Phase 1.5
# replaces this with a session-cookie / Authorization-header check and
# the body shrinks to just `{"visibility": ...}`.
# ---------------------------------------------------------------------------

class _VisibilityUpdate(BaseModel):
    visibility: str   # "cohort" | "owner-only"
    viewer: Optional[str] = None


_VALID_VISIBILITY = {"cohort", "owner-only"}


@router.post("/sessions/{session_id}/visibility")
def set_visibility(session_id: str, body: _VisibilityUpdate) -> dict:
    if body.visibility not in _VALID_VISIBILITY:
        raise HTTPException(
            status_code=400,
            detail=f"visibility must be one of {sorted(_VALID_VISIBILITY)}",
        )
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    v = _resolve_viewer(body.viewer)
    owner = session.metadata.owner
    # Only the stamped owner can flip a session's visibility. If owner
    # was never set (e.g. ingest didn't use --owner-from-first-speaker),
    # no one can toggle — the session stays at whatever it was. That's
    # the safe demo posture; Phase 1.5 layers real auth on top.
    if owner is None or v != owner:
        raise HTTPException(status_code=403, detail="only the session owner can change visibility")

    store.set_visibility(session_id, body.visibility, owner=owner)
    return {"session_id": session_id, "visibility": body.visibility, "owner": owner}
