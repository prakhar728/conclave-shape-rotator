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


def can_see_transcript(user: Optional[dict], row: dict) -> bool:
    """Gate the RAW transcript — stricter than `can_user_see`.

    Until the Transcript Saving feature, `raw_diarization` was NEVER served at
    the API boundary (the old blanket privacy guard). This opens it, but only
    to people the owner explicitly trusted with it:

      - owner of the meeting                              → yes
      - 'workspace' visibility + workspace member         → yes (full members)
      - 'shared' recipient with 'summary_and_transcript'  → yes
      - 'shared' recipient with 'summary_only'            → NO (summary only)
      - everyone else / anonymous / 'owner-only' non-owner→ no

    A caller who passes `can_see_transcript` may also see the derived view; the
    reverse is NOT true — `summary_only` recipients pass `can_user_see` (so they
    get the summary) but fail here (so the raw transcript stays withheld).
    """
    if user is None:
        return False

    owner_user_id = row.get("owner_user_id")
    if owner_user_id and owner_user_id == user["id"]:
        return True

    visibility = row.get("visibility") or "owner-only"

    if visibility == "workspace":
        from infra.workspaces import is_member
        workspace_id = row.get("workspace_id")
        return bool(workspace_id) and is_member(workspace_id, user["id"])

    if visibility == "shared":
        from infra.workspaces import get_meeting_share_scope
        scope = get_meeting_share_scope(row["session_id"], user["email"])
        return scope == "summary_and_transcript"

    # 'owner-only' (non-owner), 'public-link', or unknown → withhold raw.
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


def _apply_consent_backstop(session: Session, workspace_id: str) -> None:
    """Refresh `resolved_speakers` names from FPM's live consent decision (P4 read-time gate).

    Pulls the current name/visibility for the session's voiceprints (cached ~60s) so a confirm
    that happened without a re-tag surfaces on next load, and revoked consent withholds the name
    at read time. Fail-open: if FPM is unreachable, the stored names stand. Rewrites only
    `resolved_speakers[label]["name"]` — never the label key or `raw_diarization` (C3).
    """
    speakers = session.metadata.resolved_speakers or {}
    vids = sorted({m["voiceprint_id"] for m in speakers.values()
                   if isinstance(m, dict) and m.get("voiceprint_id")})
    if not vids:
        return
    from config import settings
    from infra import fpm_consent
    try:
        resolved = fpm_consent.consent_resolve_batch_sync(settings.fpm_workspace_for(workspace_id), vids)
    except Exception:  # noqa: BLE001 — never let a consent lookup break the read
        return
    changed = False
    for meta in speakers.values():
        if isinstance(meta, dict) and meta.get("voiceprint_id") in resolved:
            new_name = resolved[meta["voiceprint_id"]].get("name")
            if meta.get("name") != new_name:
                meta["name"] = new_name
                changed = True
    if changed:
        from transcripts import store as _store
        _store.set_metadata(session.session_id, session.metadata)


def to_transcript(session: Session) -> dict:
    """Raw-transcript projection — the ONLY shape that carries verbatim text.

    Served exclusively by `GET /sessions/{id}/transcript`, behind
    `can_see_transcript`. Each segment maps the diarizer's anonymous label to a
    resolved display name when speaker resolution ran, so the UI can show real
    names without the caller re-joining `resolved_speakers`.
    """
    speakers = session.metadata.resolved_speakers or {}

    def _name_for(label: str) -> Optional[str]:
        meta = speakers.get(label)
        if isinstance(meta, dict):
            return meta.get("name")
        return None

    segments = [
        {
            "speaker": seg.speaker,
            "speaker_name": _name_for(seg.speaker),
            "text": seg.text,
            "start": seg.start,
            "end": seg.end,
        }
        for seg in (session.raw_diarization or [])
    ]
    return {
        "session_id": session.session_id,
        "segment_count": len(segments),
        "segments": segments,
    }


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


_EXAMPLE_SESSION_ID = "example-conclave-demo"

#: Demo sessions seeded by Alembic 0009 (3.5e) — same any-authed-user
#: visibility contract as the 0005 example session.
DEMO_SESSION_IDS = frozenset({
    _EXAMPLE_SESSION_ID,
    "demo-elocute",
    "demo-dstack-intro-salon",
    "demo-project-intros-agents-day3",
})


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    request: Request,
    viewer: Optional[str] = None,
) -> dict:
    """Detail view for a single session.

    Dual-mode permission per 1.7's `can_see` dispatcher:
      - if the cookie resolves to an authenticated User AND the session
        has a workspace_id, route to workspace-mode (typed columns)
      - otherwise, fall back to the legacy cohort path with the
        `viewer` query param (existing cohort dashboards stay green)
    """
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    from auth.session import try_current_user
    user = try_current_user(request)

    # Example/demo session is visible to any authenticated user — it's the
    # empty-state placeholder seeded by Alembic 0005 (BUILD_DOC §4 D-EBR).
    # Anonymous viewers still get blocked so the marketing landing page
    # doesn't accidentally leak it.
    if session_id in DEMO_SESSION_IDS:
        if user is None:
            raise HTTPException(status_code=403, detail="not allowed")
        view = to_view(session)
        # Demo sessions are readable in full by any authed user (see
        # get_session_transcript), so their transcript panel renders too.
        view["can_view_transcript"] = True
        return view
    # Only consult the workspace columns when there's an authed user — keeps
    # anonymous cohort traffic on the legacy path and means test DBs without
    # the 1.6 columns (some legacy fixtures use init_db without alembic) are
    # never touched.
    row = None
    if user is not None:
        try:
            ws_row = store.get_workspace_fields(session_id)
        except Exception:  # noqa: BLE001 — defensive vs schema drift in test DBs
            ws_row = None
        if ws_row and ws_row.get("workspace_id"):
            row = {"session_id": session_id, **ws_row}

    # Workspace mode when both pieces are present; otherwise legacy cohort.
    if user is not None and row is not None:
        if not can_user_see(user, row):
            raise HTTPException(status_code=403, detail="not allowed")
        view = to_view(session)
        # Decorate with workspace-side metadata the frontend needs to render
        # owner controls (visibility toggle, add-attendee form) and the
        # typed visibility value (separate from the legacy JSON one).
        view["effective_visibility"] = row.get("visibility")
        view["is_owner"] = row.get("owner_user_id") == user["id"]
        # The meeting's workspace — the UI needs it to POST speaker tags
        # (/api/workspaces/{workspace_id}/meetings/{id}/tag-speaker).
        view["workspace_id"] = row.get("workspace_id")
        # Lets the transcript panel pick its state (show transcript vs.
        # "not shared with you") without a round-trip that 403s.
        view["can_view_transcript"] = can_see_transcript(user, row)
        # Retention state — drives the auto-deleted note + (owner-only) the
        # per-meeting override control. retention_override: None=inherit |
        # 'keep_forever' | '<int>' days.
        view["raw_transcript_deleted"] = bool(ws_row.get("raw_transcript_deleted_at"))
        view["retention_override"] = ws_row.get("retention_override")
        return view

    v = _resolve_viewer(viewer)
    if not can_see(v, session):
        raise HTTPException(status_code=403, detail="not allowed")
    return to_view(session)


@router.get("/sessions/{session_id}/transcript")
def get_session_transcript(session_id: str, request: Request) -> dict:
    """Raw transcript for a single session — the gated privacy surface.

    Transcript Saving feature. Unlike `get_session` (derived-only, dual-mode),
    this endpoint serves verbatim text and is therefore:

      - authenticated-only (no anonymous / legacy `?viewer=` path), and
      - gated by `can_see_transcript`, which grants the owner, full workspace
        members, and 'summary_and_transcript' recipients — and denies
        'summary_only' recipients and everyone else.

    Legacy cohort sessions (no `workspace_id`) keep the old invariant: the raw
    transcript is never served, so they 403 here regardless of viewer.

    Phase 2 adds the `raw_transcript_deleted_at` retention state; once that
    lands, a purged transcript returns 410 Gone instead of the segments.
    """
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")

    # Demo/example sessions: any authenticated user may read them in full,
    # mirroring get_session's empty-state placeholder contract.
    if session_id in DEMO_SESSION_IDS:
        return to_transcript(session)

    try:
        ws_row = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001 — defensive vs schema drift in test DBs
        ws_row = None
    if not ws_row or not ws_row.get("workspace_id"):
        # Legacy cohort session — raw transcript was never exposed for these.
        raise HTTPException(status_code=403, detail="not allowed")

    row = {"session_id": session_id, **ws_row}
    if not can_see_transcript(user, row):
        raise HTTPException(status_code=403, detail="not allowed")
    # Retention: an authorized viewer whose raw transcript was auto-deleted
    # gets 410 Gone (the summary remains on the detail endpoint). Checked
    # AFTER the gate so 'summary_only' recipients still see 403, not 410.
    if ws_row.get("raw_transcript_deleted_at"):
        raise HTTPException(status_code=410, detail="transcript auto-deleted")
    # P4: refresh names from FPM's live consent decision before projecting (cached, fail-open).
    _apply_consent_backstop(session, ws_row["workspace_id"])
    return to_transcript(session)


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


def _ws_row(session_id: str) -> Optional[dict]:
    """The session's workspace row when it has a workspace binding, else None
    (legacy cohort session). Defensive against schema drift in test DBs."""
    try:
        row = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001
        row = None
    return {"session_id": session_id, **row} if (row and row.get("workspace_id")) else None


@router.get("/sessions/{session_id}/v2")
def get_session_v2(session_id: str, request: Request) -> dict:
    """The editable v2 draft (corrected segments + annotations + status) for the
    refinement editor. Authenticated-only, and gated like the transcript surface
    (it carries verbatim text): workspace members/owner per `can_user_see`;
    legacy cohort sessions are visible to any authed user."""
    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if store.load_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    row = _ws_row(session_id)
    if row is not None and not can_user_see(user, row):
        raise HTTPException(status_code=403, detail="not allowed")
    v2 = store.load_v2(session_id)
    if v2 is None:
        raise HTTPException(status_code=404, detail="no v2 draft for this session")
    return v2.model_dump()


def _refine_debug_enabled() -> bool:
    return os.environ.get("CONCLAVE_REFINE_DEBUG", "").lower() in ("1", "true", "yes")


@router.get("/sessions/{session_id}/debug")
def get_session_v2_debug(session_id: str, request: Request) -> dict:
    """Dev-only persistence trail for the refine editor — the v2 state + per-user
    vocab + graduation stats + entity/fact counts, re-read from the DB. Gated behind
    CONCLAVE_REFINE_DEBUG and owner-only. Powers a live 'backend state' panel so a
    front-end edit can be verified to persist where Part 2 will read it."""
    if not _refine_debug_enabled():
        raise HTTPException(status_code=404, detail="debug disabled")
    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if store.load_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    row = _ws_row(session_id)
    if row is not None and row.get("owner_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="owner only")
    v2 = store.load_v2(session_id)
    if v2 is None:
        raise HTTPException(status_code=404, detail="no v2 draft")

    from storage import sqlite as _sql
    from transcripts import trust
    owner = user["id"]
    vocab_rows = _sql.list_vocab(owner)
    try:
        conn = _sql._get_conn()
        n_ent = conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
        n_fact = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
        rows = conn.execute(
            "SELECT correction_count, approved_at FROM meeting_corrections "
            "WHERE user_id=? ORDER BY approved_at DESC LIMIT 10",
            (owner,),
        ).fetchall()
        corr = [{"count": c["correction_count"], "approved_at": c["approved_at"]} for c in rows]
    except Exception:  # noqa: BLE001
        n_ent = n_fact = None
        corr = []
    return {
        "status": v2.status,
        "insights_stale": v2.insights_stale,
        "segments": [{"speaker": s.speaker_name or s.speaker_label, "text": s.text} for s in v2.segments],
        "annotations": [
            {"surface": a.surface, "state": a.state, "type": a.type, "source": a.source}
            for a in v2.annotations
        ],
        "vocab": [
            {"surface": v["surface_norm"], "type": v.get("type"), "provenance": v.get("provenance")}
            for v in vocab_rows
        ],
        "recent_corrections": corr,
        "trust_state": trust.state_for(owner),
        "entity_count": n_ent,
        "fact_count": n_fact,
    }


@router.post("/sessions/{session_id}/approve")
def approve_session_v2(session_id: str, request: Request) -> dict:
    """Approve the v2 draft and run the (gated) KB build over the corrected
    transcript. Owner-only on workspace sessions; any authed user on legacy
    cohort sessions."""
    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if store.load_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    row = _ws_row(session_id)
    if row is not None and row.get("owner_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="only the owner can approve")
    if store.load_v2(session_id) is None:
        raise HTTPException(status_code=404, detail="no v2 draft to approve")
    approve_and_build(session_id)
    return {"session_id": session_id, "status": "approved"}


# --- Editor write API (Part 1, 6c) — the POSTs the refinement editor calls ---

class _EditTokenBody(BaseModel):
    segment_id: int
    token_idx: int
    new_text: str


class _TagEntityBody(BaseModel):
    segment_id: int
    token_start: int
    token_end: int
    surface: str
    type: Optional[str] = None


class _AssignSpeakerBody(BaseModel):
    segment_id: int
    name: Optional[str] = None


def _require_editor(request: Request, session_id: str) -> dict:
    """Auth + owner gate shared by the editor-write endpoints. Returns the user.
    401 unauth · 404 no session · 403 not owner (workspace sessions)."""
    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if store.load_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    row = _ws_row(session_id)
    if row is not None and row.get("owner_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="only the owner can edit")
    return user


def _v2_write(session_id: str, fn):
    """Run a v2-mutating op, mapping store errors to HTTP. Returns the fn result."""
    try:
        return fn()
    except KeyError:
        raise HTTPException(status_code=404, detail="no v2 draft for this session")
    except ValueError:
        raise HTTPException(status_code=409, detail="v2 already approved; edits not allowed")
    except IndexError:
        raise HTTPException(status_code=400, detail="segment/token index out of range")


@router.post("/sessions/{session_id}/v2/edit-token")
def v2_edit_token(session_id: str, body: _EditTokenBody, request: Request) -> dict:
    user = _require_editor(request, session_id)
    from transcripts import ground_truth, trust
    decision = _v2_write(session_id, lambda: ground_truth.correct_word(
        session_id, body.segment_id, body.token_idx, body.new_text, user["id"]))
    trust.bump_correction(user["id"], session_id)  # graduation signal
    return {"decision": decision, "v2": store.load_v2(session_id).model_dump()}


@router.post("/sessions/{session_id}/v2/tag-entity")
def v2_tag_entity(session_id: str, body: _TagEntityBody, request: Request) -> dict:
    user = _require_editor(request, session_id)
    from transcripts import ground_truth, trust
    _v2_write(session_id, lambda: ground_truth.tag_entity(
        session_id, body.segment_id, body.token_start, body.token_end,
        body.surface, body.type, user["id"]))
    trust.bump_correction(user["id"], session_id)
    return {"v2": store.load_v2(session_id).model_dump()}


@router.post("/sessions/{session_id}/v2/assign-speaker")
def v2_assign_speaker(session_id: str, body: _AssignSpeakerBody, request: Request) -> dict:
    user = _require_editor(request, session_id)
    from transcripts import trust
    _v2_write(session_id, lambda: store.assign_speaker(session_id, body.segment_id, body.name))
    trust.bump_correction(user["id"], session_id)
    return {"v2": store.load_v2(session_id).model_dump()}


@router.get("/sessions/{session_id}/suggestions/speakers")
def get_speaker_suggestions(session_id: str, request: Request) -> dict:
    """Speaker-name suggestions for the editor (warm voiceprints + invitees +
    mentions). Authed + can-see (read surface, not owner-only)."""
    from auth.session import try_current_user
    from transcripts import suggest
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if store.load_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    row = _ws_row(session_id)
    if row is not None and not can_user_see(user, row):
        raise HTTPException(status_code=403, detail="not allowed")
    return {"speakers": suggest.speaker_suggestions(session_id)}


@router.get("/suggestions/vocab")
def get_vocab_suggestions(request: Request, prefix: str = "") -> dict:
    """Per-user vocab autocomplete (the requester's own dictionary)."""
    from auth.session import try_current_user
    from transcripts import suggest
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return {"vocab": suggest.vocab_suggestions(user["id"], prefix)}


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


def _refine_gate_enabled() -> bool:
    """Whether the Part-1 refinement gate is on: pause the KB build until the
    user approves the v2 draft. Default OFF — today's behavior is unchanged
    until trust-state (the ramp-up slice) drives this. See docs/plans §8/§10."""
    return os.environ.get("CONCLAVE_REFINE_GATE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _build_kb(session_id: str) -> None:
    """The gated half of the pipeline: KB index + extract. Runs immediately when
    the gate is off, or on approval when it's on. Each stage is isolated and
    failure-swallowing (the C11 backfill / extract re-run can redo either)."""
    try:
        from transcripts.kb_pipeline import index_session
        index_session(session_id)
    except Exception:
        logger.exception("kb indexing failed for session %s", session_id)

    # Phase 3.5b — KB extraction is itself behind ENABLE_KB_PIPELINE (default
    # off): extract_session() is a no-op unless the flag is set.
    try:
        from transcripts.kb_extract import extract_session
        extract_session(session_id)
    except Exception:
        logger.exception("kb extraction failed for session %s", session_id)


def _rederive_insights_from_v2(session_id: str) -> None:
    """Re-run v1 enrichment over the APPROVED corrected v2 text (not raw), then
    clear the stale flag. This is the only insight generation Part 1 does on
    approve; the richer/detailed pass is Part 2's. Isolated + failure-swallowing.
    """
    try:
        from transcripts.enrich import enrich_session
        from transcripts.models import RawSegment
        session = store.load_session(session_id)
        if session is None:
            return
        segs = store.v2_segments_or_raw(session_id)  # corrected when approved
        corrected = session.model_copy(update={
            "raw_diarization": [RawSegment(speaker=s["speaker"], text=s["text"]) for s in segs],
        })
        enrich_session(corrected)
        store.set_derived(session_id, corrected.derived)
        store.clear_insights_stale(session_id)
    except Exception:
        logger.exception("insight re-derive failed for session %s", session_id)


def approve_and_build(session_id: str) -> None:
    """Approve the v2 draft, re-derive v1 insights over the corrected text, and
    run the (previously gated) KB build over it.

    Idempotent: re-approving an already-approved session does NOT re-derive or
    rebuild (so insights/graph aren't doubled). The approval flip itself is
    idempotent in `store.approve_v2`.
    """
    try:
        v2 = store.load_v2(session_id)
        already_approved = v2 is not None and v2.status == "approved"
        store.approve_v2(session_id)
    except Exception:
        logger.exception("approve failed for session %s", session_id)
        return
    if not already_approved:
        # Record this approved meeting toward the owner's graduation window.
        owner = (_ws_row(session_id) or {}).get("owner_user_id")
        if owner:
            from transcripts import trust
            trust.finalize(owner, session_id)
        _rederive_insights_from_v2(session_id)
        _build_kb(session_id)


def _refine_timeout_hours() -> float:
    try:
        return float(os.environ.get("CONCLAVE_REFINE_TIMEOUT_HOURS", "8"))
    except ValueError:
        return 8.0


def _parse_v2_ts(s: Optional[str]):
    if not s:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(s.replace("Z", ""))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


def run_timeout_sweep(now=None) -> list[str]:
    """Auto-approve **auto-graduated** users' draft v2s older than the timeout
    window (default 8h, `CONCLAVE_REFINE_TIMEOUT_HOURS`). Gated users are never
    auto-approved — their drafts wait for explicit approval. Returns the
    session_ids approved this tick. Safe to run repeatedly (idempotent approve)."""
    from datetime import datetime, timedelta, timezone
    from transcripts import trust
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_refine_timeout_hours())
    approved: list[str] = []
    for row in store.list_draft_v2_sessions():
        sid = row["session_id"]
        created = _parse_v2_ts(row.get("created_at"))
        if created is None or created > cutoff:
            continue  # not old enough
        owner = (_ws_row(sid) or {}).get("owner_user_id")
        if not owner or trust.state_for(owner) != "auto":
            continue  # gated / no owner → waits for manual approval
        approve_and_build(sid)
        approved.append(sid)
    return approved


def _reminder_hours() -> float:
    try:
        return float(os.environ.get("CONCLAVE_REFINE_REMINDER_HOURS", "1"))
    except ValueError:
        return 1.0


def _send_review_reminder(session_id: str, owner_user_id: str) -> None:
    """Best-effort: email the owner a magic-link to review their draft. Swallows
    failures (the sweep marks reminded regardless, so it never spam-retries)."""
    try:
        from infra import email as email_mod
        from infra import identity, magic_links
        owner = identity.get_user(owner_user_id)
        if not owner or not owner.get("email"):
            return
        token = magic_links.issue(user_email=owner["email"], meeting_session_id=session_id)
        email_mod.send_magic_link(
            recipient_email=owner["email"],
            magic_link_url=magic_links.url_for(token),
            meeting_title="Review your meeting transcript",
            inviter_email=None,
        )
    except Exception:
        logger.exception("review reminder send failed for %s", session_id)


def run_reminder_sweep(now=None) -> list[str]:
    """Send a ONE-TIME review reminder for draft transcripts whose meeting ended
    ~CONCLAVE_REFINE_REMINDER_HOURS ago (default 1h) — for BOTH gated and auto
    users. Returns session_ids reminded this tick."""
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_reminder_hours())
    reminded: list[str] = []
    for row in store.list_unreminded_draft_v2():
        sid = row["session_id"]
        created = _parse_v2_ts(row.get("created_at"))
        if created is None or created > cutoff:
            continue  # too soon to remind
        owner = (_ws_row(sid) or {}).get("owner_user_id")
        if not owner:
            continue
        _send_review_reminder(sid, owner)
        store.mark_v2_reminded(sid)  # fire exactly once
        reminded.append(sid)
    return reminded


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
        return

    # Part 1 — create the editable v2 draft from the now-enriched session.
    # Isolated: a v2 failure must not block magic-links or the (ungated) KB build.
    try:
        store.create_v2_draft(session_id)
    except Exception:
        logger.exception("v2 draft creation failed for session %s", session_id)

    # Phase 2.8 — post-enrichment magic-link blast. Wrapped in its own
    # try/except so an email-send failure never poisons the enrichment
    # result (the card is already visible to the owner regardless).
    try:
        _send_attendee_magic_links(session_id)
    except Exception:
        logger.exception("post-enrich email blast failed for session %s", session_id)

    # Part 1 GATE — when on, pause here; the KB build (index + extract) runs on
    # approval via approve_and_build(). Default off → build now, so existing
    # behavior is unchanged until trust-state flips the gate on per user.
    if _refine_gate_enabled():
        logger.info(
            "refine gate ON — KB build deferred until approval for %s", session_id
        )
        return

    _build_kb(session_id)


def _send_attendee_magic_links(session_id: str) -> None:
    """Issue + send magic links to every meeting_shares row for this session.

    Skips:
      - sessions without a workspace binding (legacy cohort sessions)
      - sessions with visibility != 'shared' (owner-only stays private)
      - the owner's own email (they already have direct access)
      - recipients who already received a magic link for this session
        (post-enrichment can fire on re-enrichment; we don't re-spam)
    """
    fields = store.get_workspace_fields(session_id)
    if not fields or not fields.get("workspace_id"):
        return
    if fields.get("visibility") != "shared":
        return

    from infra import email as email_mod
    from infra import identity, magic_links
    from infra.workspaces import list_meeting_shares
    from storage.sqlite import _get_conn

    shares = list_meeting_shares(session_id)
    if not shares:
        return

    owner = identity.get_user(fields["owner_user_id"]) if fields.get("owner_user_id") else None
    owner_email = owner["email"] if owner else None

    # Skip recipients we've already mailed for this session.
    sent_emails = {
        row["user_email"]
        for row in _get_conn().execute(
            "SELECT user_email FROM magic_links WHERE meeting_session_id = ?",
            (session_id,),
        ).fetchall()
    }

    session = store.load_session(session_id)
    title = session.derived.summary[:80] if session and session.derived and session.derived.summary else None

    for share in shares:
        recipient = share["user_email"]
        if owner_email and recipient == owner_email:
            continue
        if recipient in sent_emails:
            continue
        token = magic_links.issue(
            user_email=recipient,
            meeting_session_id=session_id,
        )
        try:
            email_mod.send_magic_link(
                recipient_email=recipient,
                magic_link_url=magic_links.url_for(token),
                meeting_title=title,
                inviter_email=owner_email,
            )
        except Exception:
            logger.exception(
                "magic-link send failed for %s/%s — token issued but email may not arrive",
                recipient,
                session_id,
            )


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


