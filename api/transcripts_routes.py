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

from infra.meeting_lifecycle import meeting_lifecycle
from infra.meeting_origin import resolve_origin
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

    Grants (Task #32 — meetings are OWNER-PRIVATE by default; bare workspace
    membership does NOT expose a meeting):
      - owner of the meeting                              → yes
      - an explicit per-recipient `meeting_shares` row     → yes (an outside email
        OR a specific member — checked regardless of the visibility mode, so an
        owner-only meeting shared to one person grants that person)
      - a whole-workspace share + the viewer is a member   → yes (§0b-D one-click
        "share to the whole workspace" grant, covers current + future members)
      - legacy `visibility == 'workspace'` + member         → yes (back-compat: the
        pre-#32 in-person default; new meetings default owner-private instead)
      - 'public-link'                                       → False (deferred)
      - everyone else / anonymous                           → False
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

    # Task #39: the RECORDER can always see their own in-person recording's artifacts (transcript /
    # audio / insights), even when the workspace CREATOR — not them — was stamped as owner at bind.
    # Without this the person who recorded a walk-up meeting can 403 on their OWN audio. recorder_user_id
    # is set when a logged-in OS-app user records (infra.inperson_recorder / set_recorder).
    if row.get("recorder_user_id") and row.get("recorder_user_id") == user["id"]:
        return True

    from infra.workspaces import (
        has_meeting_share,
        has_meeting_workspace_share,
        is_member,
    )

    # Explicit per-recipient grant (outside email OR a specific member) — checked
    # independently of the visibility mode so an owner-only meeting shared to one
    # person grants exactly that person (§0b-D: an explicit share, not membership).
    if has_meeting_share(row["session_id"], user["email"]):
        return True

    # Whole-workspace grant (or the legacy 'workspace' visibility) → every member.
    member = bool(workspace_id) and is_member(workspace_id, user["id"])
    if member and (has_meeting_workspace_share(row["session_id"]) or visibility == "workspace"):
        return True

    return False


#: The three independently-shareable artifacts (Task #31). Each maps to the
#: matching boolean on a `meeting_shares` row (via ShareConfig).
_ARTIFACTS = ("transcript", "insights", "audio")


def can_see_artifact(user: Optional[dict], row: dict, artifact: str) -> bool:
    """Per-artifact gate — stricter than `can_user_see` (Task #31).

    `artifact` ∈ {"transcript", "insights", "audio"}. Grants:

      - owner of the meeting                          → yes (all artifacts)
      - 'workspace' visibility + workspace member      → yes (full members)
      - 'shared' recipient                             → iff that artifact's flag
                                                          is set on their share
      - everyone else / anonymous / 'owner-only'       → no

    'insights' (summary/signals/entities) is now a real gate: pre-#31 every
    share saw insights, so a `summary_only`-era row back-fills to insights=on.
    """
    if artifact not in _ARTIFACTS:
        raise ValueError(f"artifact must be one of {_ARTIFACTS}, got {artifact!r}")
    if user is None:
        return False

    owner_user_id = row.get("owner_user_id")
    if owner_user_id and owner_user_id == user["id"]:
        return True

    # Task #39: the RECORDER always sees their own in-person recording's artifacts (transcript /
    # audio / insights), even when the workspace CREATOR — not them — was stamped as owner at bind.
    # Without this the person who recorded a walk-up meeting 403s on their OWN audio.
    if row.get("recorder_user_id") and row.get("recorder_user_id") == user["id"]:
        return True

    visibility = row.get("visibility") or "owner-only"
    workspace_id = row.get("workspace_id")
    session_id = row["session_id"]

    from infra.workspaces import (
        get_meeting_share_scope,
        has_meeting_share,
        has_meeting_workspace_share,
        is_member,
    )

    # Task #32 decision B: a workspace MEMBER granted the meeting (via a
    # whole-workspace share, the legacy 'workspace' visibility, or a member-specific
    # share) gets FULL artifacts — transcript + insights + audio all pass.
    member = bool(workspace_id) and is_member(workspace_id, user["id"])
    if member and (
        has_meeting_workspace_share(session_id)
        or visibility == "workspace"
        or has_meeting_share(session_id, user["email"])
    ):
        return True

    # A NON-member recipient (an outside-workspace, by-email share) keeps #31's
    # per-artifact gating — only the flags on their share row are granted.
    config = get_meeting_share_scope(session_id, user["email"])
    if config is None:
        return False
    return bool(getattr(config, artifact))


def can_see_transcript(user: Optional[dict], row: dict) -> bool:
    """Gate the RAW transcript — see :func:`can_see_artifact`.

    Kept as a named wrapper: a caller who passes this may also see the derived
    view via `can_user_see`, but the reverse is NOT true — a share that withholds
    the transcript still passes `can_user_see` (session-level) yet fails here.
    """
    return can_see_artifact(user, row, "transcript")


def can_see_insights(user: Optional[dict], row: dict) -> bool:
    """Gate the derived INSIGHTS (summary/signals/entities) — Task #31.

    NEW gate: before #31 these were served ungated to every share. Now a share
    can withhold them (insights=off) while still granting transcript and/or audio.
    """
    return can_see_artifact(user, row, "insights")


def can_see_audio(user: Optional[dict], row: dict) -> bool:
    """Gate the stored AUDIO recording (Task #30 endpoint) — Task #31."""
    return can_see_artifact(user, row, "audio")


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
        # Task #39 — full server-stamped ingest timestamp (UTC ISO) for time-of-day
        # rendering; None for legacy sessions with only a date (FE degrades to `date`).
        "created_at": session.created_at,
        "source": m.source,
        # Task #38 — canonical origin ("in_person"/"google_meet"/"upload"/"demo"/…)
        # derived from (source, platform) with a legacy bot_invitations fallback.
        # The frontend maps this to a quiet badge (label + lucide icon).
        "origin": resolve_origin(session),
        # Task #40 — short meeting title. An owner rename (manual_title) wins over
        # the LLM-generated derived.title; None → the FE falls back to the summary's
        # first line (legacy meetings enriched before titles existed).
        "title": m.manual_title or d.title,
        "summary": d.summary,
        "signal_count": len(d.signals or []),
        "entity_count": len(d.entities or []),
        "chunk_count": m.chunk_count,
        "model_id": m.model_id,
        "enrich_prompt_version": m.enrich_prompt_version,
        "team_context_version": m.team_context_version,
        # Provenance: non-null iff a per-meeting intent (calendar description or
        # manual focus) was compiled into the <meeting_intent> grounding block.
        # Surfaced so a silent break in calendar → insights is visible on the UI.
        "meeting_intent_version": m.meeting_intent_version,
        # Task #30: whether this meeting's (encrypted) audio was stored — drives the
        # meeting-page audio player. None = unknown/legacy (the UI may probe).
        "store_audio": m.store_audio,
        # Task #39: server "DiariZen post-pass complete" timestamp (None = not done yet). The
        # in-person detail view keys its finalized state (LIVE→final badge, voiceprint hint) off this.
        "diarized_at": m.diarized_at,
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
        # Lets the meeting page explain empty insights (no LLM vs found-nothing).
        "enrichment_status": session.metadata.enrichment_status,
        # Task #42 — coarse lifecycle (processing/failed/done) with the staleness
        # cutoff applied, so the meeting page can show a "couldn't generate
        # insights" state + Retry/Delete instead of a perpetual spinner.
        "enrichment_state": meeting_lifecycle(
            session.metadata.enrichment_status, bool(d.summary), session.created_at,
        ),
    })
    return card


#: Fields of a `to_view()` payload that constitute the derived "insights"
#: (summary/signals/entities) gated by `can_see_insights` (Task #31).
_INSIGHT_VIEW_FIELDS = (
    "summary",
    "signals",
    "signals_by_kind",
    "entities",
    "graph_nodes",
    "signal_count",
    "entity_count",
)


def _redact_insights(view: dict) -> dict:
    """Strip the derived insights from a view when the viewer lacks the
    insights grant (Task #31). Mutates + returns `view`.

    Empties summary/signals/entities (+ their counts) so an insights=off share
    sees the meeting shell (date/participants/transcript+audio availability)
    without the summary or extracted signals/entities.
    """
    view["summary"] = None
    view["signals"] = []
    view["signals_by_kind"] = {plural: [] for plural, _ in _SIGNAL_KIND_GROUPS}
    view["entities"] = []
    view["graph_nodes"] = None
    view["signal_count"] = 0
    view["entity_count"] = 0
    return view


def _apply_resolved_names(speakers: dict, resolved: dict) -> bool:
    """Apply an FPM consent-resolve map onto `resolved_speakers`. Returns whether
    anything changed. Shared by the persisted baseline + the per-viewer overlay.

    Task #3 Part (a): a CONSENTED (claimed + identify-allowed) recognition auto-applies
    its name; a named-but-UNCLAIMED one is NOT silently applied — its name is withheld
    and surfaced to the host as a "Proposed: <name>" one-click confirm instead. WS5
    anonymous / unnamed stays nameless.
    """
    changed = False
    for meta in speakers.values():
        if not (isinstance(meta, dict) and meta.get("voiceprint_id") in resolved):
            continue
        r = resolved[meta["voiceprint_id"]]
        name = r.get("name")
        consented = bool(r.get("consented"))
        applied = name if (name and consented) else None
        proposed = name if (name and not consented) else None
        if (meta.get("name") != applied or meta.get("proposed_name") != proposed
                or bool(meta.get("consented")) != consented):
            meta["name"] = applied
            meta["proposed_name"] = proposed
            meta["consented"] = consented
            changed = True
    return changed


def _resolve_names(session: Session, workspace_id: str, host_user: Optional[str]) -> Optional[dict]:
    """Fetch FPM's consent-resolve map for this session's voiceprints under `host_user`.

    Returns the `{vid: {...}}` map, or None on no-voiceprints / FPM error (fail-open)."""
    speakers = session.metadata.resolved_speakers or {}
    vids = sorted({m["voiceprint_id"] for m in speakers.values()
                   if isinstance(m, dict) and m.get("voiceprint_id")})
    if not vids:
        return None
    from config import settings
    from infra import fpm_consent
    try:
        return fpm_consent.consent_resolve_batch_sync(
            settings.fpm_workspace_for(workspace_id), vids, host_user=host_user)
    except Exception:  # noqa: BLE001 — never let a consent lookup break the read
        return None


def _apply_consent_backstop(session: Session, workspace_id: str) -> None:
    """Refresh `resolved_speakers` names from FPM's live consent decision (P4 read-time gate).

    Resolves under the SCOPE-WIDE floor (`host_user=None`) so the PERSISTED baseline never
    carries an adder-only private name — that would leak it to other workspace members (Task
    #32). A confirm/revoke that happened without a re-tag still surfaces on next load. Fail-open:
    if FPM is unreachable, the stored names stand. Rewrites only `resolved_speakers[label]["name"]`
    — never the label key or `raw_diarization` (C3).

    The per-viewer adder-only overlay is a SEPARATE, non-persisted step (`_overlay_viewer_names`),
    and the Task #13 heal-on-open (`_maybe_heal_on_open`) keys off THIS scope-wide baseline so the
    summary regen is deterministic across viewers.
    """
    resolved = _resolve_names(session, workspace_id, host_user=None)
    if resolved is None:
        return
    if _apply_resolved_names(session.metadata.resolved_speakers or {}, resolved):
        from transcripts import store as _store
        _store.set_metadata(session.session_id, session.metadata)


def _overlay_viewer_names(session: Session, workspace_id: str, viewer_email: Optional[str]) -> None:
    """Task #32 decision A — per-viewer adder-only name overlay (response only, NOT persisted).

    Re-resolves this session's voiceprints under `host_user = the viewing member`, so an
    adder-only edge resolves ONLY for whoever added it — even across members viewing the SAME
    meeting. Applied to the in-memory `session` (mutated, then read by `to_view`/`to_transcript`)
    but NEVER written back with `set_metadata`, so two viewers never clobber each other's names or
    trigger heal churn. No-op when the viewer is anonymous or FPM is unreachable (fail-open to the
    scope-wide baseline the backstop already applied).
    """
    if not viewer_email:
        return
    resolved = _resolve_names(session, workspace_id, host_user=viewer_email)
    if resolved is None:
        return
    _apply_resolved_names(session.metadata.resolved_speakers or {}, resolved)


def _maybe_heal_on_open(session: Session) -> bool:
    """Task #13 — lazy heal-on-open after a deferred speaker-name confirm.

    Call AFTER `_apply_consent_backstop` has refreshed the names (so `session`'s resolved set
    is as fresh as FPM's consent decision). Compares the currently-resolved speaker-name set
    against the stamp the summary was built with (`metadata.enrich_speakers_version`). On a
    real difference WITH ≥1 confirmed name (a name appeared / was corrected / a wrong tag was
    fixed out-of-band), enqueues a background re-enrich so the summary regenerates with the
    real name — **this meeting only**. Returns whether a heal is needed/in-flight (for the
    badge).

    Guards:
      - `current == stamp` → no-op (free reads stay free; idempotent — the re-enrich re-stamps
        to `current`, so the next unchanged open is a no-op: self-converging, no loop).
      - no confirmed name (all anonymous, incl. unstamped legacy) → no-op (no spurious regen on
        the all-anonymous first open).
      - in-flight dedup: two concurrent opens both see the difference, but the first marks the
        v2 `insights_stale` lock + enqueues; the second sees the lock and reports the badge
        without re-enqueueing → exactly one regen.
    """
    from transcripts import store as _store

    current = _store.speakers_version(session)
    if current == session.metadata.enrich_speakers_version:
        return False
    if not _store.has_confirmed_speaker(session):
        return False
    v2 = _store.load_v2(session.session_id)
    if v2 is None or not v2.insights_stale:
        _store.mark_insights_stale(session.session_id)
        from connectors.jobs import enqueue
        enqueue.enrich(session.session_id)
    return True


def to_transcript(session: Session) -> dict:
    """Raw-transcript projection — serves approved v2 when present, else raw.

    Served exclusively by `GET /sessions/{id}/transcript`, behind
    `can_see_transcript`. Each segment maps the diarizer's anonymous label to a
    resolved display name when speaker resolution ran, so the UI can show real
    names without the caller re-joining `resolved_speakers`.

    When an approved v2 draft exists, the corrected tokens + speaker names are
    returned instead of the immutable raw diarization — so an editor-approved
    transcript immediately surfaces on the meeting page without a re-upload.
    """
    from transcripts import store as _tstore
    speakers = session.metadata.resolved_speakers or {}

    def _meta_for(label: str) -> dict:
        meta = speakers.get(label)
        return meta if isinstance(meta, dict) else {}

    raw_segs = _tstore.v2_segments_or_raw(session.session_id)
    segments = []
    for seg in raw_segs:
        m = _meta_for(seg["speaker"])
        vid = m.get("voiceprint_id")
        segments.append({
            "speaker": seg["speaker"],
            "speaker_name": m.get("name"),          # applied only for consented (Task #3 Part a)
            # Task #3 Part (a): a recognized-but-unconsented name the host can one-click confirm.
            "proposed_name": m.get("proposed_name"),
            "voiceprint_id": vid,
            "consented": bool(m.get("consented")) if vid else None,
            "text": seg["text"],
            "start": seg.get("start"),
            "end": seg.get("end"),
        })
    # Task #37 — coalesce consecutive same-speaker spans into turns (a display
    # projection). `segments` (spans) stay for edit/clip/seek; `turns` wrap them for
    # rendering. Export (#18) and the editor inherit the same grouping.
    from transcripts.turns import group_into_turns

    return {
        "session_id": session.session_id,
        "segment_count": len(segments),
        "segments": segments,
        "turns": group_into_turns(segments),
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
        # get_session_transcript), so every panel renders.
        view["can_view_transcript"] = True
        view["can_view_insights"] = True
        view["can_view_audio"] = True
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
        # Task #13 — refresh names from FPM consent (cached, fail-open), then heal the
        # summary on open if a deferred confirm changed the resolved name set since the
        # last enrich. `regenerating` drives the meeting page's "updating insights" badge.
        _apply_consent_backstop(session, row["workspace_id"])
        regenerating = _maybe_heal_on_open(session)
        # Task #32 decision A: overlay THIS viewer's adder-only names (response only, no
        # persist) AFTER heal keys off the scope-wide baseline.
        _overlay_viewer_names(session, row["workspace_id"], user.get("email"))
        view = to_view(session)
        # Task #31 — insights (summary/signals/entities) are now independently
        # withholdable. A share with insights=off sees the meeting shell but not
        # the derived view. Owner + full members always pass.
        insights_ok = can_see_insights(user, row)
        if not insights_ok:
            view = _redact_insights(view)
        view["insights_regenerating"] = regenerating
        # Decorate with workspace-side metadata the frontend needs to render
        # owner controls (visibility toggle, add-attendee form) and the
        # typed visibility value (separate from the legacy JSON one).
        view["effective_visibility"] = row.get("visibility")
        view["is_owner"] = row.get("owner_user_id") == user["id"]
        # Task #32 — sharing state for the owner controls (whole-workspace grant +
        # confidential lock). Cheap single-row lookups; only meaningful to the owner.
        from infra.workspaces import has_meeting_workspace_share
        view["shared_to_workspace"] = has_meeting_workspace_share(session_id)
        view["owner_only"] = bool(ws_row.get("owner_only"))
        # The meeting's workspace — the UI needs it to POST speaker tags
        # (/api/workspaces/{workspace_id}/meetings/{id}/tag-speaker).
        view["workspace_id"] = row.get("workspace_id")
        # Lets the frontend pick each panel's state (show vs. "not shared with
        # you") without a round-trip that 403s.
        view["can_view_transcript"] = can_see_transcript(user, row)
        view["can_view_insights"] = insights_ok
        view["can_view_audio"] = can_see_audio(user, row)
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
        members, and recipients whose share has the transcript flag on (Task
        #31) — and denies everyone else (a share with transcript=off still sees
        the summary via `get_session` but 403s here).

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
    # Task #32 decision A: per-viewer adder-only overlay (response only, not persisted).
    _overlay_viewer_names(session, ws_row["workspace_id"], user.get("email"))
    return to_transcript(session)


# ---------------------------------------------------------------------------
# Audio playback — Task #30. Decrypt-on-read serving of the stored meeting
# recording (full, or a `?start=&end=` segment clip). Never writes plaintext
# back to disk. This is the BASE endpoint #3 extends to also accept an
# FPM-signed capability; #31 adds the dedicated `audio` share flag.
# ---------------------------------------------------------------------------


def _slice_wav(data: bytes, start: Optional[float], end: Optional[float]) -> bytes:
    """Return the [start, end)-second slice of a WAV blob (seconds → frames).

    Non-WAV blobs (e.g. a gMeet webm) can't be sliced frame-accurately, so the
    whole blob is returned — full playback still works, only clipping is WAV-only.
    """
    import io
    import wave

    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            sr = w.getframerate()
            nframes = w.getnframes()
            sampwidth = w.getsampwidth()
            channels = w.getnchannels()
            s = int(max(0.0, start or 0.0) * sr)
            e = int((end if end is not None else nframes / sr) * sr)
            s = min(s, nframes)
            e = min(max(e, s), nframes)
            w.setpos(s)
            frames = w.readframes(e - s)
        out = io.BytesIO()
        with wave.open(out, "wb") as ww:
            ww.setnchannels(channels)
            ww.setsampwidth(sampwidth)
            ww.setframerate(sr)
            ww.writeframes(frames)
        return out.getvalue()
    except wave.Error:
        return data


def _audio_response(audio: bytes, request: Request):
    """Serve WAV bytes with HTTP Range support so the `<audio>` element can SEEK
    (Task #41). Without `Accept-Ranges`/206 partial content, `preload="metadata"`
    can't jump to an unbuffered offset — setting `currentTime` silently no-ops,
    which breaks both the click-to-seek ▶ and the waveform scrubber. A request
    with no/invalid Range still gets the full 200 (+ `Accept-Ranges`)."""
    from fastapi.responses import Response

    total = len(audio)
    rng = request.headers.get("range")
    if not rng or not rng.strip().lower().startswith("bytes="):
        return Response(content=audio, media_type="audio/wav",
                        headers={"Accept-Ranges": "bytes"})
    try:
        spec = rng.split("=", 1)[1].split(",")[0].strip()
        s, _, e = spec.partition("-")
        start_b = int(s) if s else 0
        end_b = int(e) if e else total - 1
        end_b = min(end_b, total - 1)
        if start_b < 0 or start_b > end_b or start_b >= total:
            raise ValueError
    except ValueError:
        return Response(status_code=416, media_type="audio/wav",
                        headers={"Content-Range": f"bytes */{total}", "Accept-Ranges": "bytes"})
    chunk = audio[start_b:end_b + 1]
    return Response(content=chunk, status_code=206, media_type="audio/wav",
                    headers={"Accept-Ranges": "bytes",
                             "Content-Range": f"bytes {start_b}-{end_b}/{total}",
                             "Content-Length": str(len(chunk))})


@router.get("/sessions/{session_id}/audio")
def get_session_audio(
    session_id: str,
    request: Request,
    start: Optional[float] = None,
    end: Optional[float] = None,
    cap: Optional[str] = None,
):
    """Decrypt + serve a meeting's stored audio (full, or a segment clip).

    Two auth paths:
      1. Session cookie (Task #31): gated by the dedicated `can_see_audio` flag (owner +
         full workspace members + recipients whose share has audio=on). Legacy cohort
         sessions never exposed audio, so they 403.
      2. Task #3 clip capability (`?cap=`): an FPM-signed, expiring, subject-scoped token
         (from the "is this you?" box) authorizing ONLY the one [start,end] clip in the
         capability. A non-member subject can hear their own segment — nothing else. FPM
         never streams bytes; it only signs the pointer.

    Decryption happens in memory (`_assemble_audio`); plaintext is never re-written to disk.
    For capture meetings `session_id == native_meeting_id` (the audio-dir key).
    """
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    from fastapi.responses import Response

    # ── path 2: FPM-signed clip capability (bounded to one segment of THIS session) ──
    if cap is not None:
        from infra.clip_capability import verify_capability

        payload = verify_capability(cap)
        if payload is None:
            raise HTTPException(status_code=403, detail="invalid or expired capability")
        clip_ref = payload.get("clip_ref") or {}
        cap_session = clip_ref.get("conclave_session_id") or clip_ref.get("native_meeting_id")
        # A capability for session A must never fetch session B (path is authoritative).
        if cap_session != session_id:
            raise HTTPException(status_code=403, detail="capability does not match this session")
        from connectors.capture.identify import _assemble_audio
        audio = _assemble_audio(session_id)
        if not audio:
            raise HTTPException(status_code=404, detail="no stored audio for this meeting")
        # Slice is fixed by the capability, not the query — the token can only ever yield
        # its own bounded [start,end] clip, never the whole recording.
        audio = _slice_wav(audio, clip_ref.get("start"), clip_ref.get("end"))
        return Response(content=audio, media_type="audio/wav")

    # ── path 1: signed-in member / recipient (Task #31 gate) ──
    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")

    try:
        ws_row = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001 — defensive vs schema drift in test DBs
        ws_row = None
    if not ws_row or not ws_row.get("workspace_id"):
        raise HTTPException(status_code=403, detail="not allowed")
    row = {"session_id": session_id, **ws_row}
    if not can_see_audio(user, row):
        raise HTTPException(status_code=403, detail="not allowed")

    from connectors.capture.identify import _assemble_audio
    audio = _assemble_audio(session_id)
    if not audio:
        raise HTTPException(status_code=404, detail="no stored audio for this meeting")
    if start is not None or end is not None:
        # A bounded per-segment clip (#3 / segment player) — no seeking needed.
        return Response(content=_slice_wav(audio, start, end), media_type="audio/wav")

    # The full recording — Range-enabled so the player can seek (Task #41).
    return _audio_response(audio, request)


@router.delete("/sessions/{session_id}/audio")
def delete_session_audio(session_id: str, request: Request) -> dict:
    """Delete a meeting's stored audio from the meeting page (Task #30 §3.4).

    Owner-gated. Removes the encrypted files + sha256 sidecars and flips the
    read-side `store_audio` metadata to False so the player disappears. The
    transcript/insights are untouched — only the recording is forgotten. This is
    the shared deletion seam #1/#3 reuse (clips die with their source audio).
    """
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")

    try:
        ws_row = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001
        ws_row = None
    owner_id = (ws_row or {}).get("owner_user_id")
    if not owner_id or owner_id != user.get("id"):
        raise HTTPException(status_code=403, detail="only the owner can delete audio")

    from storage import sqlite as _sqlite
    removed = _sqlite.cleanup_session_audio(session_id)
    try:
        session.metadata.store_audio = False
        store.set_metadata(session_id, session.metadata)
    except Exception:  # noqa: BLE001 — metadata flip is a UI nicety, not the deletion itself
        logger.exception("delete_session_audio: store_audio flip failed for %s", session_id)
    return {"deleted": removed, "session_id": session_id}


# ---------------------------------------------------------------------------
# Task #40 — owner rename. Sets `metadata.manual_title`, which WINS over the
# LLM-generated `derived.title` and survives regeneration. An empty/blank title
# clears the override (reverts to the auto title / summary-first-line fallback).
# ---------------------------------------------------------------------------

class _TitleUpdate(BaseModel):
    title: str  # blank/whitespace clears the manual override


@router.patch("/sessions/{session_id}/title")
def rename_session(session_id: str, body: _TitleUpdate, request: Request) -> dict:
    """Owner-gated meeting rename. Stores the manual title on metadata (not on
    `derived`, so a later regen never clobbers it). Returns the effective title."""
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")

    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")

    try:
        ws_row = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001
        ws_row = None
    owner_id = (ws_row or {}).get("owner_user_id")
    if not owner_id or owner_id != user.get("id"):
        raise HTTPException(status_code=403, detail="only the owner can rename this meeting")

    cleaned = " ".join(body.title.split()).strip()
    session.metadata.manual_title = cleaned or None
    store.set_metadata(session_id, session.metadata)
    effective = session.metadata.manual_title or (
        session.derived.title if session.derived else None
    )
    return {"session_id": session_id, "title": effective,
            "manual": session.metadata.manual_title is not None}


# ---------------------------------------------------------------------------
# Task #42 — owner delete (hard) + retry a stuck/failed enrich.
# ---------------------------------------------------------------------------

def _require_meeting_owner(session_id: str, request: Request):
    """Load a session and assert the caller is its workspace owner. Returns the
    loaded `Session`. Raises 404 (missing), 401 (unauth), or 403 (not owner)."""
    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    from auth.session import try_current_user
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        ws_row = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001
        ws_row = None
    owner_id = (ws_row or {}).get("owner_user_id")
    if not owner_id or owner_id != user.get("id"):
        raise HTTPException(status_code=403, detail="only the owner can do that")
    return session


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request) -> dict:
    """Owner-gated HARD delete of a meeting (Task #42). Removes the transcript
    (raw + derived), shares, KB mentions/obligations, encrypted audio, and the
    live-segment/bot-invitation side rows via `store.delete_session` — the same
    cascade #18's data-rights delete reuses. The subject's FPM voiceprint is NOT
    touched (deleted separately via #1); only this meeting's local refs die."""
    _require_meeting_owner(session_id, request)
    existed = store.delete_session(session_id)
    return {"deleted": existed, "session_id": session_id}


@router.post("/sessions/{session_id}/retry-enrich")
def retry_enrich(session_id: str, request: Request) -> dict:
    """Owner-gated retry of a failed/stuck enrichment (Task #42). Resets the
    status to `pending` and re-enqueues the enrich job (#16). No-op-safe to call
    on an already-done meeting (it just re-derives)."""
    session = _require_meeting_owner(session_id, request)
    session.metadata.enrichment_status = "pending"
    store.set_metadata(session_id, session.metadata)
    from connectors.jobs import enqueue
    enqueue.enrich(session_id)
    return {"session_id": session_id, "status": "pending"}


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
async def approve_session_v2(session_id: str, request: Request) -> dict:
    """Approve the v2 draft, then run the (gated) KB build over the corrected
    transcript in the BACKGROUND. Owner-only on workspace sessions; any authed user
    on legacy cohort sessions."""
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
    # Flip approval synchronously so the response + DB are immediately consistent, then
    # run the slow build (insight re-derive + KB) off the request thread — otherwise a
    # large transcript / LLM call blocks the response and the editor shows a false
    # "Couldn't approve" even though the approval already persisted.
    if _approve_v2_now(session_id):
        # Task #16: the heavy re-derive + KB build runs as a durable `regen` job when the queue is on
        # (so #9's post-approve re-derive — and #13's tag-regen — ride a restart-proof substrate),
        # else the same in-process background task as before.
        from connectors.jobs import enqueue
        enqueue.regen(session_id)
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


def _kb_index_only(session_id: str) -> None:
    """KB index stage in isolation — the `kb_index` job handler (Task #16). Failure-swallowing."""
    try:
        from transcripts.kb_pipeline import index_session
        index_session(session_id)
    except Exception:
        logger.exception("kb indexing failed for session %s", session_id)


def _kb_extract_only(session_id: str) -> None:
    """KB extract stage in isolation — the `kb_extract` job handler (Task #16). Failure-swallowing."""
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
    if _should_skip_enrich():
        # LLM disabled (no key / CONCLAVE_SKIP_ENRICH) → don't burn tokens or block on
        # the network. Just settle the stale flag; there are no insights to re-derive.
        try:
            store.clear_insights_stale(session_id)
        except Exception:
            logger.exception("clear stale failed for session %s", session_id)
        return
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
        # Task #13 — re-stamp `enrich_speakers_version` from the ORIGINAL session's
        # immutable-raw labels (corrected.raw_diarization carries v2 *names*, so its own
        # stamp would use the wrong basis and the meeting would immediately re-heal on
        # open). Persisting metadata here is what makes #9's approve path re-stamp.
        corrected.metadata.enrich_speakers_version = store.speakers_version(session)
        store.set_metadata(session_id, corrected.metadata)
        store.clear_insights_stale(session_id)
    except Exception:
        logger.exception("insight re-derive failed for session %s", session_id)


def _approve_v2_now(session_id: str) -> bool:
    """Flip the draft → approved and record graduation. FAST + synchronous (safe to run
    inside the HTTP request). Returns True if NEWLY approved (caller should run the heavy
    post-approve build), False if it was already approved or the flip failed.
    """
    try:
        v2 = store.load_v2(session_id)
        already_approved = v2 is not None and v2.status == "approved"
        store.approve_v2(session_id)
    except Exception:
        logger.exception("approve failed for session %s", session_id)
        return False
    if already_approved:
        return False
    # Record this approved meeting toward the owner's graduation window.
    owner = (_ws_row(session_id) or {}).get("owner_user_id")
    if owner:
        from transcripts import trust
        try:
            trust.finalize(owner, session_id)
        except Exception:
            logger.exception("trust.finalize failed for session %s", session_id)
    return True


def _post_approve_build(session_id: str) -> None:
    """The HEAVY half of approval — re-derive insights + KB build. Slow (LLM / indexing),
    so the HTTP endpoint runs this in the BACKGROUND; the auto-approve sweep runs it
    inline. Each stage is isolated + failure-swallowing."""
    _rederive_insights_from_v2(session_id)
    _build_kb(session_id)


def approve_and_build(session_id: str) -> None:
    """Approve the v2 draft + run the post-approve build synchronously. Used by non-HTTP
    callers (the auto-approve timeout sweep). The HTTP endpoint instead flips approval
    fast and backgrounds the build so a big transcript / LLM call can't time out the
    request (and produce a false "Couldn't approve" after the approval already persisted).

    Idempotent: re-approving an already-approved session does NOT re-derive or rebuild.
    """
    if _approve_v2_now(session_id):
        _post_approve_build(session_id)


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


def _should_skip_enrich() -> bool:
    """Skip the LLM enrichment (no token spend) when force-disabled via
    CONCLAVE_SKIP_ENRICH or no LLM is configured. A module-level seam so tests can
    control it deterministically."""
    from config import settings
    return os.environ.get("CONCLAVE_SKIP_ENRICH") == "1" or not settings.llm_configured()


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
    session = store.load_session(session_id)
    if session is None:
        logger.error("background enrich: session %s not found", session_id)
        return

    # Task #42 — empty-transcript fast-fail. A cancelled recording / silence-only
    # capture lands as a session with no usable text; enriching it would burn an
    # LLM call to produce nothing and leave the card spinning. Mark it failed
    # immediately (no LLM call) so the UI shows "couldn't generate insights" +
    # Retry/Delete. Retry re-enqueues, so a transient upstream can still recover.
    if not any((seg.text or "").strip() for seg in session.raw_diarization):
        session.metadata.enrichment_status = "failed"
        store.set_metadata(session_id, session.metadata)
        store.clear_insights_stale(session_id)
        logger.info("enrich fast-failed for %s — empty transcript", session_id)
        return

    # The editable v2 draft (spaCy candidate detection) needs NOTHING from the LLM, so
    # build it FIRST — it's fast (~1-2s) and unblocks /refine immediately, independent
    # of (and surviving) the slow LLM enrichment that follows. Isolated try/except.
    # Task #13: build it ONCE — a re-enrich (heal-on-open) must NOT rebuild it, or it
    # would clobber an approved v2 / the owner's corrections (save_transcript_v2 upserts).
    try:
        if store.load_v2(session_id) is None:
            store.create_v2_draft(session_id)
    except Exception:
        logger.exception("v2 draft creation failed for session %s", session_id)

    # LLM enrichment (the v1 meeting insights). Skipped (NO LLM call → no tokens) when
    # none is configured or it's force-disabled; we record WHY so the UI can explain
    # empty insights ("no LLM" vs "found nothing" vs "unreachable").
    if _should_skip_enrich():
        session.metadata.enrichment_status = "skipped"
        store.set_metadata(session_id, session.metadata)
        # Task #13 (H4): release the heal-in-flight lock even when enrich is skipped —
        # the stamp is NOT advanced, so a later open re-fires the heal once an LLM is
        # configured. Holding the lock would stick the badge AND block retry forever.
        store.clear_insights_stale(session_id)
        logger.info("enrich skipped for %s (no LLM configured / CONCLAVE_SKIP_ENRICH)", session_id)
    else:
        try:
            from transcripts.enrich import enrich_session
            enrich_session(session)
            session.metadata.enrichment_status = "ok"
            store.set_derived(session_id, session.derived)
            store.set_metadata(session_id, session.metadata)
            # Task #13: enrich_session re-stamped `enrich_speakers_version` to the
            # current resolved-name set; clear the heal-in-flight lock so the next
            # open with unchanged names is a no-op (self-converging, no loop). Initial
            # enrich: a no-op (flag already clear).
            store.clear_insights_stale(session_id)
        except Exception:
            logger.exception("background enrich failed for session %s", session_id)
            session.metadata.enrichment_status = "failed"
            store.set_metadata(session_id, session.metadata)
            # Task #13 (H4): a FAILED re-enrich (e.g. LLM down) must still release the
            # in-flight lock. enrich_session threw BEFORE stamping, so
            # `enrich_speakers_version` is unchanged (stays diverged) → the next open
            # re-fires the heal and retries once the LLM recovers. Without this the lock
            # (which doubles as the heal dedup key) never releases → stuck badge + no retry.
            store.clear_insights_stale(session_id)

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

    Delegates the per-recipient work to :func:`_send_one_attendee_magic_link`,
    which the Task #15 tag "email transcript" toggle reuses for a single person.
    """
    fields = store.get_workspace_fields(session_id)
    if not fields or not fields.get("workspace_id"):
        return
    if fields.get("visibility") != "shared":
        return

    from infra.workspaces import list_meeting_shares

    for share in list_meeting_shares(session_id):
        _send_one_attendee_magic_link(session_id, share["user_email"])


def _send_one_attendee_magic_link(session_id: str, recipient: str) -> None:
    """Issue + send ONE magic link for `recipient` on a shared session.

    The per-recipient half of :func:`_send_attendee_magic_links`, exposed so the
    Task #15 tag toggle can notify a single person immediately on tag. Same
    guards as the blast: no-op unless the session is workspace-bound and
    ``shared``; never mails the owner; never re-mails someone already sent a link
    for this session (idempotent). Link-only — never transcript content.
    """
    fields = store.get_workspace_fields(session_id)
    if not fields or not fields.get("workspace_id"):
        return
    if fields.get("visibility") != "shared":
        return

    from infra import email as email_mod
    from infra import identity, magic_links
    from storage.sqlite import _get_conn

    owner = identity.get_user(fields["owner_user_id"]) if fields.get("owner_user_id") else None
    owner_email = owner["email"] if owner else None
    if owner_email and recipient == owner_email:
        return

    already = _get_conn().execute(
        "SELECT 1 FROM magic_links WHERE meeting_session_id = ? AND user_email = ?",
        (session_id, recipient),
    ).fetchone()
    if already is not None:
        return

    session = store.load_session(session_id)
    title = session.derived.summary[:80] if session and session.derived and session.derived.summary else None
    token = magic_links.issue(user_email=recipient, meeting_session_id=session_id)
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
    # Durable via the job queue when on (Task #16), else the same in-process background task.
    from connectors.jobs import enqueue
    enqueue.enrich(session.session_id)

    return {"session_id": session.session_id, "status": "accepted"}


