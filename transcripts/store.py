"""Typed persistence for sessions over `storage.sqlite`.

Thin translation between `Session` models and the `transcript_sessions` table.
The immutability contract lives in the storage layer: `save_session` will not
overwrite `raw_diarization` once a row exists, so re-running enrichment only
moves `derived`/`metadata` forward.
"""
from __future__ import annotations

import json
from typing import Optional

from storage import sqlite
from transcripts.models import (
    CandidateAnnotation,
    Derived,
    RawSegment,
    Session,
    SessionMetadata,
    TranscriptV2,
    V2Segment,
)


def save_session(session: Session) -> None:
    sqlite.save_transcript_session(
        session_id=session.session_id,
        source=session.metadata.source,
        session_date=session.metadata.date,
        raw_diarization=[s.model_dump() for s in session.raw_diarization],
        metadata=session.metadata.model_dump(),
        derived=session.derived.model_dump(),
    )


def append_segment(
    native_meeting_id: str,
    seq: int,
    segment: dict,
    segment_id: Optional[str] = None,
) -> None:
    """Buffer one live capture segment for a meeting (P1 streaming ingest).

    Accumulates in `live_segments` (NOT `raw_diarization`, which is write-once);
    the finalize path materializes the buffer into a `Session` exactly once."""
    sqlite.append_live_segment(native_meeting_id, seq, segment, segment_id)


def live_segments(native_meeting_id: str) -> list[dict]:
    """Ordered live buffer for a meeting (live read + finalize)."""
    return sqlite.get_live_segments(native_meeting_id)


def clear_live_segments(native_meeting_id: str) -> None:
    """Drop a meeting's live buffer once it's been materialized into a Session (finalize)."""
    sqlite.clear_live_segments(native_meeting_id)


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


def set_raw_diarization(session_id: str, segments: list[dict]) -> None:
    """Overwrite raw_diarization with the authoritative post-pass result (in-person DiariZen upgrade ONLY).

    The sole sanctioned write-once exception (see sqlite.update_transcript_raw): diart's live transcript
    is replaced once by DiariZen's authoritative diarization at finalize."""
    sqlite.update_transcript_raw(session_id, segments)


def set_metadata(session_id: str, metadata: SessionMetadata) -> None:
    sqlite.update_transcript_metadata(session_id, metadata.model_dump())


def delete_session(session_id: str) -> bool:
    """Task #42 — hard-delete a meeting + all DB/audio it owns (reusable by the
    owner delete endpoint and #18 data-rights delete). Returns True iff it existed."""
    return sqlite.delete_session_cascade(session_id)


def reresolve_voiceprint(
    voiceprint_id: str,
    name: Optional[str],
    workspace_id: Optional[str] = None,
) -> int:
    """P4 — propagate a confirmed binding's name across every stored transcript.

    On observing a `confirmed` proposal (self-tag / autoconfirm), Conclave sweeps its
    sessions and rewrites **only** `resolved_speakers[label]["name"]` for entries whose
    `voiceprint_id` matches — never the label key (the immutable C3 join key for
    `Signal.said_by`) nor `raw_diarization`. Cross-transcript by construction: the same
    voiceprint in two meetings gets the name in both. Scoped to a workspace when given
    (P4 is per-room); global otherwise. Returns the number of sessions updated.

    Legacy cohort entries (`{record_id, name, mock}`, no `voiceprint_id`) never match,
    so the two `resolved_speakers` value shapes coexist untouched.
    """
    sessions = (
        list_workspace_sessions(workspace_id) if workspace_id is not None else list_sessions()
    )
    updated = 0
    for s in sessions:
        changed = False
        for entry in (s.metadata.resolved_speakers or {}).values():
            if isinstance(entry, dict) and entry.get("voiceprint_id") == voiceprint_id:
                if entry.get("name") != name:
                    entry["name"] = name
                    changed = True
        if changed:
            set_metadata(s.session_id, s.metadata)
            updated += 1
    return updated


# ---------------------------------------------------------------------------
# Task #13 — speaker-name stamp + projection (heal-on-open after deferred consent)
# ---------------------------------------------------------------------------

def _speaker_name_map(session: Session) -> dict[str, Optional[str]]:
    """Canonical basis for the stamp: ``raw_label -> resolved name or None``.

    Built from the **labels present in the immutable raw_diarization** joined
    to their currently-resolved name (``resolved_speakers[label]["name"]``), or
    ``None`` when still anonymous/pending. Pending tags never land in
    ``resolved_speakers``, so they don't appear here — "confirmed-only" by
    construction. ``raw_diarization`` is read, never mutated.
    """
    labels = {s.speaker for s in session.raw_diarization}
    resolved = session.metadata.resolved_speakers or {}
    out: dict[str, Optional[str]] = {}
    for label in labels:
        entry = resolved.get(label)
        name = entry.get("name") if isinstance(entry, dict) else None
        out[label] = name or None
    return out


def speakers_version(session: Session, *, length: int = 16) -> str:
    """Deterministic fingerprint of the resolved speaker-name set (Task #13 §3.1).

    ``sha256(canonical_json(sorted {raw_label → resolved_name_or_null}))[:length]``.
    Stable across processes (sorted keys, compact separators). At first enrich
    most labels are ``null`` → stamps the "all anonymous" state.
    """
    import hashlib
    mapping = _speaker_name_map(session)
    canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]


def has_confirmed_speaker(session: Session) -> bool:
    """True iff ≥1 raw label now resolves to a non-null name (the §3.2 guard)."""
    return any(v for v in _speaker_name_map(session).values())


def resolved_name_map(session: Session) -> dict[str, str]:
    """``raw_label -> confirmed name`` (non-null only), for projecting real names
    into the LLM text at enrich time (Task #13 §3.3). Labels still anonymous are
    omitted, so the projection keeps ``Speaker N`` for them."""
    return {k: v for k, v in _speaker_name_map(session).items() if v}


def mark_insights_stale(session_id: str) -> None:
    """Flip the v2 ``insights_stale`` flag on (idempotent). Reuses #9's badge +
    serves as the heal-in-flight dedup lock (Task #13 §3.5). Preserves status /
    approved_at — never re-opens an approved v2 to draft (unlike ``_editable_v2``).
    No-op when no v2 draft exists yet."""
    v2 = load_v2(session_id)
    if v2 is not None and not v2.insights_stale:
        v2.insights_stale = True
        _save_v2(v2)


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
        # Task #39 — project the server-stamped ingest timestamp read-only from the
        # DB column so DTOs can render time-of-day (metadata.date is date-granular).
        created_at=row.get("created_at"),
    )


# ---------------------------------------------------------------------------
# Phase 1.6 — workspace / owner / visibility (typed columns from Alembic 0004)
# ---------------------------------------------------------------------------

def set_workspace(
    session_id: str,
    workspace_id: Optional[str],
    owner_user_id: Optional[str],
    visibility: Optional[str] = None,
) -> None:
    """Bind a session to a workspace + owner (and optionally flip visibility).

    Pure setter — does NOT touch raw_diarization, metadata JSON, or derived.
    The JSON `metadata.owner` and `metadata.visibility` fields are now
    legacy mirrors; Phase 1.7's `can_see` will read the typed columns.
    """
    from storage import sqlite as _sqlite
    _sqlite.set_transcript_workspace(
        session_id=session_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        visibility=visibility,
    )


def get_workspace_fields(session_id: str) -> Optional[dict]:
    """Return `{workspace_id, owner_user_id, visibility, recorder_user_id,
    owner_only, retention_override, raw_transcript_deleted_at}` or None if missing."""
    from storage import sqlite as _sqlite
    return _sqlite.get_transcript_workspace_fields(session_id)


def set_recorder(session_id: str, recorder_user_id: Optional[str]) -> None:
    """Task #32 — stamp the member who recorded this meeting (the identify host)."""
    from storage import sqlite as _sqlite
    _sqlite.set_transcript_recorder(session_id, recorder_user_id)


def set_owner_only(session_id: str, owner_only: bool) -> None:
    """Task #32 — set the per-meeting confidential lock (blocks workspace sharing)."""
    from storage import sqlite as _sqlite
    _sqlite.set_transcript_owner_only(session_id, owner_only)


# ---------------------------------------------------------------------------
# Phase 2 — retention / auto-delete (typed columns from Alembic 0012)
# ---------------------------------------------------------------------------

def set_retention_override(session_id: str, retention_override: Optional[str]) -> None:
    """Per-meeting override: None (inherit), 'keep_forever', or '<int>' days."""
    from storage import sqlite as _sqlite
    _sqlite.set_transcript_retention_override(session_id, retention_override)


def purge_raw(session_id: str) -> None:
    """Auto-delete the raw transcript, keeping metadata + derived. Stamps
    `raw_transcript_deleted_at`."""
    from storage import sqlite as _sqlite
    _sqlite.purge_transcript_raw(session_id)


def list_retention_rows() -> list[dict]:
    """Projection the retention sweep iterates over (see sqlite layer)."""
    from storage import sqlite as _sqlite
    return _sqlite.list_transcript_retention_rows()


def list_workspace_sessions(workspace_id: str) -> list[Session]:
    """All sessions belonging to a workspace, newest-first. No visibility filter
    yet — Phase 1.7 layers `can_see` on top."""
    from storage import sqlite as _sqlite
    return [_row_to_session(r) for r in _sqlite.list_workspace_transcript_sessions(workspace_id)]


def list_owned_sessions(owner_user_id: str) -> list[Session]:
    """All sessions OWNED by a user, newest-first (Task #18 data export).

    Owner-scoped by construction (see
    ``sqlite.list_owned_transcript_sessions``) — the single filter that keeps
    one user's export free of any other user's meetings."""
    from storage import sqlite as _sqlite
    return [_row_to_session(r) for r in _sqlite.list_owned_transcript_sessions(owner_user_id)]


def save_session_with_workspace(
    session: Session,
    workspace_id: str,
    owner_user_id: str,
    visibility: str = "owner-only",
) -> None:
    """Save a session AND bind it to a workspace + owner in one go.

    Phase 2.x's Recato webhook + canonical ingest call this so newly-created
    sessions land already-scoped to the user who invited the bot.

    `save_session` writes the immutable raw + metadata + derived; the
    workspace columns are then set in a second statement. Both happen on
    the same connection so they're visible together to subsequent reads.
    """
    save_session(session)
    set_workspace(session.session_id, workspace_id, owner_user_id, visibility)


# ---------------------------------------------------------------------------
# Part 1 — transcript v2 (editable correction layer). Raw stays immutable;
# every seam here reads/writes only the `transcript_v2` row. See
# docs/plans/transcript-refine.md §4/§10.
# ---------------------------------------------------------------------------

def _save_v2(v2: TranscriptV2) -> None:
    doc = {
        "segments": [s.model_dump() for s in v2.segments],
        "annotations": [a.model_dump() for a in v2.annotations],
        "insights_stale": v2.insights_stale,
    }
    sqlite.save_transcript_v2(
        v2.session_id, v2.status, v2.approved_at, json.dumps(doc)
    )


def _owner_of(session_id: str) -> str:
    """The session's owner user_id (for per-user vocab lookup during detection),
    or '' for legacy/un-owned sessions (no vocab hits)."""
    try:
        row = sqlite.get_transcript_workspace_fields(session_id)
    except Exception:  # noqa: BLE001
        row = None
    return (row or {}).get("owner_user_id") or ""


def create_v2_draft(session_id: str) -> TranscriptV2:
    """Initialize the v2 draft from a session's immutable raw segments, running
    the candidate-detection pass ONCE per segment.

    Each raw segment → a `V2Segment` (same index) whose tokens come from the
    detector (spaCy tokens when available, else whitespace) so candidate-span
    anchors align with the editable token list. Candidate spans (state
    known/candidate/oov via the owner's vocab + dictionary) land as
    `source="nlp"` annotations. The raw diarizer label is copied as the immutable
    join key; `speaker_name` starts empty. Raw is never touched.
    """
    from transcripts import candidate
    from transcripts.models import TokenSpan

    session = load_session(session_id)
    if session is None:
        raise KeyError(session_id)
    owner = _owner_of(session_id)
    segments: list[V2Segment] = []
    annotations: list[CandidateAnnotation] = []
    for i, seg in enumerate(session.raw_diarization):
        tokens, spans = candidate.detect(seg.text, owner)
        segments.append(
            V2Segment(segment_id=i, speaker_label=seg.speaker, tokens=tokens)
        )
        for sp in spans:
            annotations.append(
                CandidateAnnotation(
                    span=TokenSpan(
                        segment_id=i, token_start=sp.token_start, token_end=sp.token_end
                    ),
                    surface=sp.surface, state=sp.state, type=sp.type, source=sp.source,
                )
            )
    v2 = TranscriptV2(
        session_id=session_id, status="draft", segments=segments, annotations=annotations
    )
    _save_v2(v2)
    return v2


def list_draft_v2_sessions() -> list[dict]:
    """Sessions whose v2 is still a draft — the timeout sweep's worklist."""
    return sqlite.list_draft_v2_sessions()


def list_unreminded_draft_v2() -> list[dict]:
    """Draft sessions that haven't had their review reminder sent yet."""
    return sqlite.list_unreminded_draft_v2()


def mark_v2_reminded(session_id: str) -> None:
    sqlite.mark_v2_reminded(session_id)


def load_v2(session_id: str) -> Optional[TranscriptV2]:
    row = sqlite.get_transcript_v2(session_id)
    if row is None:
        return None
    doc = row["doc"] or {}
    return TranscriptV2(
        session_id=row["session_id"],
        status=row["status"],
        approved_at=row["approved_at"],
        segments=[V2Segment(**s) for s in doc.get("segments", [])],
        annotations=[CandidateAnnotation(**a) for a in doc.get("annotations", [])],
        insights_stale=bool(doc.get("insights_stale", False)),
    )


def _editable_v2(session_id: str) -> TranscriptV2:
    """Return the v2 in an editable state.

    - Raises KeyError if no v2 exists for this session.
    - If the v2 is approved, re-opens it to draft (status="draft",
      approved_at=None, insights_stale=True) so the caller can edit freely;
      the caller's subsequent _save_v2 persists the re-open.
    - If already a draft, returns as-is.
    """
    v2 = load_v2(session_id)
    if v2 is None:
        raise KeyError(session_id)
    if v2.status == "approved":
        v2.status = "draft"
        v2.approved_at = None
        v2.insights_stale = True
    return v2


def edit_token(
    session_id: str, segment_id: int, token_idx: int, new_text: str
) -> TranscriptV2:
    """Replace a single token's text (count unchanged → token indices, and thus
    all other span anchors, stay valid). If the v2 is approved, editing
    re-opens it to draft (insights become stale; owner re-approves to re-derive)."""
    v2 = _editable_v2(session_id)
    v2.segments[segment_id].tokens[token_idx] = new_text
    v2.insights_stale = True
    _save_v2(v2)
    return v2


def add_annotation(session_id: str, annotation: CandidateAnnotation) -> TranscriptV2:
    """Append a candidate-span annotation (entity/type/new-vocab) to the draft."""
    v2 = _editable_v2(session_id)
    v2.annotations.append(annotation)
    v2.insights_stale = True
    _save_v2(v2)
    return v2


def assign_speaker(session_id: str, segment_id: int, name: Optional[str]) -> TranscriptV2:
    """Set the confirmed speaker name on a v2 segment. The raw diarizer label
    (the immutable join key) is never touched."""
    v2 = _editable_v2(session_id)
    v2.segments[segment_id].speaker_name = name
    v2.insights_stale = True
    _save_v2(v2)
    return v2


def clear_insights_stale(session_id: str) -> None:
    """Clear the stale flag (called after insights are re-derived on approve)."""
    v2 = load_v2(session_id)
    if v2 is not None and v2.insights_stale:
        v2.insights_stale = False
        _save_v2(v2)


def approve_v2(session_id: str) -> TranscriptV2:
    """Flip the draft to approved (one-way; idempotent — re-approving keeps the
    original `approved_at`). This is the gate the KB build waits on."""
    v2 = load_v2(session_id)
    if v2 is None:
        raise KeyError(session_id)
    if v2.status != "approved":
        v2.status = "approved"
        v2.approved_at = sqlite._now()
        _save_v2(v2)
    return v2


def v2_segments_or_raw(session_id: str) -> list[dict]:
    """Segment source for the KB build + the transcript DTO: the **approved** v2
    (corrected tokens + confirmed speaker) when present, else the immutable raw.

    Draft (un-approved) v2 is deliberately NOT used — the KB only ever builds
    from human-approved corrections. Returns `[{speaker, text, start, end}]`; the
    KB (`kb_pipeline.index_session`) reads `speaker`/`text` and ignores the rest,
    while `to_transcript` needs `start`/`end` for the timestamp display, the
    per-segment clip player, and click-to-seek (Task #41). `V2Segment` itself has
    no timestamps, so the approved-v2 path carries them from the raw segment at
    the matching index (v2 `segment_id` mirrors the raw index)."""
    session = load_session(session_id)
    if session is None:
        return []
    raw = session.raw_diarization
    v2 = load_v2(session_id)
    if v2 is not None and v2.status == "approved":
        out = []
        for seg in v2.segments:
            r = raw[seg.segment_id] if 0 <= seg.segment_id < len(raw) else None
            out.append({
                "speaker": (seg.speaker_name or seg.speaker_label),
                "text": seg.text,
                "start": r.start if r else None,
                "end": r.end if r else None,
            })
        return out
    return [{"speaker": s.speaker, "text": s.text, "start": s.start, "end": s.end}
            for s in raw]
