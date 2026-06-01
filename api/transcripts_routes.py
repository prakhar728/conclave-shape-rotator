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

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from transcripts import store
from transcripts.models import Session

logger = logging.getLogger(__name__)


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


def can_see(
    viewer: Optional[str],
    session: Session,
    row: Optional[dict] = None,
) -> bool:
    """Permission rule — dual-mode for the v1 transition.

    Phase 1.6 added typed `workspace_id` / `owner_user_id` / `visibility`
    columns on `transcript_sessions`. New product sessions populate them;
    legacy cohort sessions (the 13+ historical fixtures) have
    `workspace_id IS NULL`. This function routes based on which world the
    row lives in:

    - `row` provided AND `row['workspace_id']` is set → **workspace mode**.
      Delegates to `can_user_see` using the typed columns + workspace
      membership + `meeting_shares`. `viewer` must be a User dict (or None
      for anonymous).
    - Otherwise → **legacy cohort mode**. `viewer` is a record_id string
      (or None). Matches the pre-1.7 logic exactly so existing cohort
      dashboards and tests keep working.

    Legacy cohort rule (unchanged from pre-1.7):
      1. `visibility == "cohort"` → True for everyone.
      2. `visibility == "owner-only"` and viewer is None → False.
      3. Owner sees their own session.
      4. A viewer whose `record_id` matches any speaker's `record_id` in
         `resolved_speakers` sees the session.
      5. Otherwise False.

    v1.5 will retire the cohort path once historical fixtures are
    migrated into a "Shape Rotator Cohort" workspace (see BUILD_DOC §11).
    """
    if row is not None and row.get("workspace_id"):
        # Workspace mode — viewer is a User dict or None.
        return can_user_see(viewer if isinstance(viewer, dict) else None, row)

    # Legacy cohort mode — viewer is a string record_id or None.
    md = session.metadata
    if (md.visibility or "cohort") == "cohort":
        return True
    if viewer is None or isinstance(viewer, dict):
        return False
    if md.owner and md.owner == viewer:
        return True
    for sp_meta in (md.resolved_speakers or {}).values():
        if isinstance(sp_meta, dict) and sp_meta.get("record_id") == viewer:
            return True
    return False


def can_user_see(user: Optional[dict], row: dict) -> bool:
    """Workspace-aware permission check using the typed columns.

    `row` is a transcript_sessions row dict carrying at minimum
    `session_id`, `workspace_id`, `owner_user_id`, `visibility`.
    `user` is the authenticated User dict (or None for anonymous).

    Visibility branches:
      - 'owner-only'  : user.id == row.owner_user_id
      - 'shared'      : owner OR explicit meeting_shares row for user.email
      - 'workspace'   : any member of row.workspace_id (reserved for v1.5;
                        v1 UI doesn't expose this option but the check
                        works if rows are set to it manually)
      - 'public-link' : False in v1 (BUILD_DOC §11 — public links deferred)
      - unknown       : False (defensive; CHECK constraint should prevent)
    """
    visibility = row.get("visibility") or "owner-only"
    owner_user_id = row.get("owner_user_id")
    workspace_id = row.get("workspace_id")

    if visibility == "public-link":
        # Deferred to v1.5 — the public branch needs token-link plumbing
        # that doesn't exist yet. Until then, treat public-link as private.
        return False

    if user is None:
        # All remaining branches require an authenticated user.
        return False

    if owner_user_id and owner_user_id == user["id"]:
        return True

    if visibility == "owner-only":
        return False

    if visibility == "shared":
        # Explicit grant via meeting_shares (Phase 2.x writes these).
        from infra.workspaces import has_meeting_share
        return has_meeting_share(row["session_id"], user["email"])

    if visibility == "workspace":
        from infra.workspaces import is_member
        return bool(workspace_id) and is_member(workspace_id, user["id"])

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
        # F4 (§D.1): the frontend renders the "hide from cohort" toggle
        # only when the current viewer is the owner. Surfacing both
        # fields here keeps the card a self-describing payload.
        "visibility": m.visibility or "cohort",
        "owner": m.owner,
        "seed": session.session_id,
    }


#: Signal kinds in the order we want them rendered on the dashboard
#: (decision-led, then commitments, then opens, then color-coded context).
#: Keys are the JSON-friendly pluralised names served under
#: ``signals_by_kind``; values are the matching ``Signal.kind`` strings.
_SIGNAL_KIND_GROUPS: list[tuple[str, str]] = [
    # v2.2: collapsed to 3 kinds (action_item absorbed decision; insight
    # absorbed impactful_point). Render priority: commitments first, then
    # unresolved threads, then notable observations.
    ("action_items",   "action_item"),
    ("open_questions", "open_question"),
    ("insights",       "insight"),
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


# ---------------------------------------------------------------------------
# Personal action-items + cohort roster — P4 (§D.1)
# ---------------------------------------------------------------------------

def _viewer_speaker_labels(viewer: str, session: Session) -> set[str]:
    """Reverse-lookup: which speaker labels in this session map to viewer?

    `resolved_speakers` is `{label: {"record_id": ..., "name": ..., ...}}`.
    A signal's `said_by` / `about_person` arrays carry speaker labels (or
    raw name strings), so to ask "is the viewer implicated?" we first
    have to map viewer.record_id back to the labels they appear under.
    """
    labels: set[str] = set()
    for label, meta in (session.metadata.resolved_speakers or {}).items():
        if isinstance(meta, dict) and meta.get("record_id") == viewer:
            labels.add(label)
    return labels


@router.get("/me/action-items")
def get_my_action_items(viewer: str) -> list[dict]:
    """Personal action-items queue.

    Walks every session the viewer can see; for each, picks signals
    where `kind == "action_item"` AND the viewer is implicated (their
    record_id maps to a speaker label that appears in `said_by` or
    `about_person`). Returns one entry per implicated signal.

    Phase 1.5: drop the `viewer` query param in favor of an auth header
    and resolve identity server-side; the rest of this function is
    unchanged.
    """
    v = _resolve_viewer(viewer)
    if v is None:
        raise HTTPException(status_code=400, detail="viewer query param is required")
    out: list[dict] = []
    sessions = store.list_sessions()
    sessions.sort(key=lambda s: (s.metadata.date, s.session_id), reverse=True)
    for s in sessions:
        if not can_see(v, s):
            continue
        labels = _viewer_speaker_labels(v, s)
        if not labels:
            continue
        for sig in (s.derived.signals or []):
            if sig.kind != "action_item":
                continue
            said_by = set(sig.said_by or [])
            about = set(sig.about_person or [])
            if labels & (said_by | about):
                out.append({
                    "session_id": s.session_id,
                    "session_date": s.metadata.date,
                    "signal": sig.model_dump(),
                })
    return out


@router.get("/_cohort/roster")
def get_cohort_roster() -> list[dict]:
    """Roster for the identity picker (§D.1 frontend).

    Source: MOCK_DIRECTORY (cohort-data) ∪ resolved_speakers across all
    sessions. Deduped by record_id. Each entry: {record_id, label, source}
    where `source` is "directory" or "speaker" — the picker can use it
    to flag speaker-only ids (people without a cohort-data file).

    Demo-only — Phase 1.5 replaces with a real cohort-OS lookup.
    """
    from transcripts.identity import MOCK_DIRECTORY

    seen: dict[str, dict] = {}
    # Directory entries first — they win the `source` tag.
    for label, record_id in MOCK_DIRECTORY.items():
        if record_id not in seen:
            seen[record_id] = {"record_id": record_id, "label": label, "source": "directory"}
    # Then speaker-derived ids that the directory doesn't cover.
    for s in store.list_sessions():
        for label, meta in (s.metadata.resolved_speakers or {}).items():
            if not isinstance(meta, dict):
                continue
            rid = meta.get("record_id")
            if rid and rid not in seen:
                seen[rid] = {"record_id": rid, "label": label, "source": "speaker"}
    return sorted(seen.values(), key=lambda e: e["record_id"])


# ---------------------------------------------------------------------------
# Canonical ingest webhook (`STRATEGY.md` Appendix A.3)
# ---------------------------------------------------------------------------
#
# `POST /transcripts/ingest` is Conclave's **public ingestion contract**. Any
# producer (Recato, Otter adapter, in-house bot) POSTs a canonical-shape
# payload signed with HMAC-SHA256 over the raw body; the route verifies the
# signature, dedupes by `event_id`, persists the raw session, returns 202
# with `session_id`, and kicks LLM enrichment as a background task. Producers
# never block on enrichment latency.
#
# Producer secrets live in env vars: `CONCLAVE_INGEST_SECRET_<NAME>` (uppercase
# name; e.g. `CONCLAVE_INGEST_SECRET_RECATO`). The `source` field on the
# payload picks which secret to verify against — case-insensitive lookup.
# This is the v1 / demo posture; DB-backed producer registration is deferred
# until there's a second real producer asking (Appendix A.3, "registration").


def _load_producer_secrets() -> dict[str, str]:
    """Snapshot of producer signing secrets from env (read once per request).

    Lazy and per-call by design — lets tests override individual env vars
    via `monkeypatch` without restarting the process, and lets ops rotate
    a key without bouncing the dashboard.
    """
    prefix = "CONCLAVE_INGEST_SECRET_"
    return {
        k[len(prefix):].lower(): v
        for k, v in os.environ.items()
        if k.startswith(prefix) and v
    }


def _verify_signature(body: bytes, header_value: Optional[str], secret: str) -> bool:
    """HMAC-SHA256 verification, Stripe/GitHub/Vexa-compatible.

    Header format: ``sha256=<hex digest>``. ``hmac.compare_digest`` is used
    so the comparison is constant-time and not vulnerable to timing analysis.
    """
    if not header_value or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header_value)


class _CanonicalSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    language: Optional[str] = None
    absolute_start: Optional[str] = None
    absolute_end: Optional[str] = None


class _CanonicalMeeting(BaseModel):
    external_id: str
    platform: Optional[str] = None       # gmeet | zoom | teams | in_person | other
    url: Optional[str] = None
    title: Optional[str] = None
    start_time: Optional[str] = None     # ISO 8601
    end_time: Optional[str] = None
    participants: Optional[list[str]] = None


class CanonicalIngestPayload(BaseModel):
    """Public ingestion contract. Versioned by `api_version` for forward-compat."""
    event_id: str
    event_type: str = Field(..., pattern=r"^transcript\.ingest$")
    api_version: str = Field(..., pattern=r"^v\d+$")
    produced_at: Optional[str] = None
    source: str = Field(..., min_length=1, max_length=64)
    meeting: _CanonicalMeeting
    segments: list[_CanonicalSegment]


def _build_and_save_session(payload_dict: dict) -> Session:
    """Pure pipeline: canonical payload → NormalizedInput → Session → store.

    Mirrors the file-ingest flow in `transcripts.ingest.ingest_path` but
    skips the file I/O and the `_iter_files` discovery — the payload *is*
    the input. Identity resolution still runs so `resolved_speakers` is
    populated for downstream `can_see` and the dashboard's identity picker.
    """
    from transcripts.sources import read_canonical
    from transcripts.parse import build_session
    from transcripts.identity import resolve_speakers

    ni = read_canonical(payload_dict)
    if not ni.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="canonical payload contains no usable segments",
        )
    session = build_session(ni)
    session.metadata.resolved_speakers = resolve_speakers(session)
    store.save_session(session)
    return session


def _enrich_in_background(session_id: str) -> None:
    """Run enrichment on a stored session; log and swallow exceptions.

    Mirrors the load → enrich → persist-derived flow used by
    ``transcripts.enrich.enrich_pending``: enrichment mutates the session
    object only, so we must `set_derived` + `set_metadata` after the call
    to persist the LLM output.

    The webhook returns 202 the moment the raw session is persisted — the
    LLM run happens after. Failures here must NOT propagate (no response
    listener); they're logged and surfaced via session status only.
    Re-enrichment is always available via the existing CLI / batch path
    (`enrich_pending` will pick up any session whose derived is empty or
    whose prompt version is stale).
    """
    try:
        from transcripts.enrich import enrich_session
        session = store.load_session(session_id)
        if session is None:
            logger.error("background enrich: session %s not found", session_id)
            return
        enrich_session(session)
        store.set_derived(session.session_id, session.derived)
        store.set_metadata(session.session_id, session.metadata)
    except Exception:
        logger.exception("background enrich failed for session %s", session_id)


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Canonical transcript ingestion webhook (STRATEGY.md Appendix A.3)",
)
async def ingest_transcript(
    request: Request,
    payload: CanonicalIngestPayload,
    x_conclave_signature: Optional[str] = Header(default=None, alias="X-Conclave-Signature"),
) -> dict:
    """Accept a canonical transcript payload from any registered producer.

    Returns ``{"session_id": ..., "status": "accepted" | "duplicate"}``.
    The body has already been parsed by FastAPI for Pydantic validation,
    but signature verification needs the **raw** bytes — we re-read them
    from `request` (FastAPI caches the body, so this is a dict lookup,
    not a re-stream).
    """
    # ── 1. Auth: HMAC-SHA256 ───────────────────────────────────────────────
    secrets = _load_producer_secrets()
    source_key = payload.source.lower()
    secret = secrets.get(source_key)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"unknown producer source: {payload.source!r}",
        )
    raw_body = await request.body()
    if not _verify_signature(raw_body, x_conclave_signature, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="signature verification failed",
        )

    # ── 2. Idempotency: dedupe by meeting.external_id ─────────────────────
    # `external_id` flows through `read_canonical` → `provenance.session_id`
    # → `Session.session_id` (deterministic per `parse._session_id`). So a
    # session for this meeting already exists iff `load_session(external_id)`
    # finds one. event_id is preserved in provenance for audit, but is NOT
    # used as the dedupe key — same meeting POSTed twice (e.g. webhook
    # retry) yields one session.
    existing = store.load_session(payload.meeting.external_id)
    if existing is not None:
        return {"session_id": existing.session_id, "status": "duplicate"}

    # ── 3. Persist raw (sync — fast; no LLM) ──────────────────────────────
    session = _build_and_save_session(payload.model_dump())

    # ── 4. Kick async enrichment, return 202 immediately ──────────────────
    asyncio.create_task(asyncio.to_thread(_enrich_in_background, session.session_id))

    return {"session_id": session.session_id, "status": "accepted"}


