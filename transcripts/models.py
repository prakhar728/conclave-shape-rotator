"""Pydantic models for the transcript pipeline.

The shape mirrors the storage row in `storage.sqlite.transcript_sessions`:
a session is `raw_diarization` (immutable) + `metadata` + `derived`. At
Layer-1 insert every `derived` field is None; enrichment fills `summary`,
`signals`, and `entities`. `graph_nodes` is reserved for Layer-2 matching.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

#: Bump when the pipeline's output contract changes. Stored on every session
#: so future stages can tell which version produced a given `derived` block.
PIPELINE_VERSION = "transcript-pipeline/0.1.0"


class RawSegment(BaseModel):
    """One diarized utterance. Never mutated after storage.

    `speaker` is the diarizer's anonymous label (e.g. "speaker_1") — real
    names are resolved later into `SessionMetadata.resolved_speakers`, never
    by editing this. `start`/`end` are seconds from session start; VoxTerm
    segments carry a single timestamp, mapped to `start` with `end=None`.
    """

    speaker: str
    text: str
    start: Optional[float] = None
    end: Optional[float] = None


class SessionMetadata(BaseModel):
    date: str  # ISO date (YYYY-MM-DD), used for Layer-2 date-range queries
    source: str  # 'voxterm', 'whisper', 'assemblyai', ...
    # label -> speaker metadata; empty until speaker resolution runs. Two value
    # shapes share this field (mutable JSON, no SQL migration):
    #   - record/voiceprint path (C3): {voiceprint_id, name, confidence} — the
    #     stable key P4 (email binding) / P5 (redaction) build on. name is a
    #     read-time projection of voiceprint_id; the label string is the
    #     immutable join key for already-enriched Signal.said_by.
    #   - legacy cohort path: {record_id, name, mock} (identity.resolve_speakers).
    resolved_speakers: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    pipeline_version: str = PIPELINE_VERSION
    # Provenance carried through from the source when present.
    record_id: Optional[str] = None
    origin_device: Optional[str] = None
    location: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    #: Capture platform carried through from the ingest canonical payload
    #: (`inperson` for in-person diarization, `google_meet`/`zoom`/`teams` for
    #: the online bot). None for pasted/uploaded transcripts and legacy
    #: sessions created before this field existed. The origin badge (Task #38)
    #: derives its in-person-vs-online label from this — `source` alone can't,
    #: since both capture paths write the same ingest `source`.
    platform: Optional[str] = None
    # --- Permissions (defined now, enforced at 1.5; live in JSON metadata
    # so no SQL migration is required — see IMPLEMENTATION_PLAN.md §D). ---
    visibility: str = "cohort"  # "cohort" | "owner-only"
    owner: Optional[str] = None  # record_id of the owner
    # --- Enrichment provenance (set by enrich.enrich_pending). ---
    model_id: Optional[str] = None
    enrich_prompt_version: Optional[str] = None
    chunk_count: Optional[int] = None
    #: Lifecycle of the v1 LLM enrichment, for the UI: "pending" (not run yet),
    #: "ok" (insights generated), "skipped" (no LLM configured / force-disabled),
    #: "failed" (LLM unreachable). Drives the meeting-page no-insights placeholder.
    enrichment_status: str = "pending"
    # --- v1 ---
    #: SHA-256 prefix (first 8 chars) of the loaded team_context XML body
    #: at enrich time. Lets A/B-tests over the XML show up as a distinct
    #: backfill key without conflating with prompt-version changes.
    team_context_version: Optional[str] = None
    #: Per-meeting intent — freeform text stating what the meeting is about /
    #: what the organizer wants out of the notes (agenda, focus, desired
    #: outputs). Sourced from the Google Calendar event description or a manual
    #: "focus" field at invite/upload time. Compiled at enrich time into a
    #: structured grounding fragment (see transcripts/compile_intent.py). JSON
    #: metadata, so no SQL migration.
    raw_intent: Optional[str] = None
    #: SHA-256 prefix (first 8 chars) of the raw_intent compiled at enrich
    #: time — the intent analogue of team_context_version (A/B + provenance).
    meeting_intent_version: Optional[str] = None
    #: Task #13 — fingerprint of the speaker-name set the summary was built
    #: with: sha256(canonical_json(sorted {raw_label → resolved_name_or_null}))[:16].
    #: Stamped on every enrich (initial, #9 approve-regen, #13 heal). On read,
    #: the heal-on-open compare recomputes this against the *currently-resolved*
    #: names; a difference (a deferred consent confirmed a name out-of-band)
    #: triggers a background re-enrich so the summary heals with the real name.
    #: None on sessions enriched before this feature — the ≥1-non-null-name
    #: guard keeps those from spuriously re-enriching on their first open.
    enrich_speakers_version: Optional[str] = None
    #: Explicit attendance roster when known (Google Meet / Zoom / calendar
    #: connector, future v1.1 work). When None, callers fall back to
    #: deriving "who was in the room" from distinct speaker labels in
    #: ``raw_diarization`` (an undercount when audience members never spoke).
    #: Listeners per signal = (participants or members) − said_by.
    participants: Optional[list[str]] = None
    #: Task #30 — whether this meeting's audio was stored (encrypted at rest).
    #: Set at finalize from the in-person WS toggle / gMeet invite decision. Drives
    #: the meeting-page audio player (show only when True). None = unknown/legacy
    #: (player falls back to probing the serving endpoint). JSON metadata, no migration.
    store_audio: Optional[bool] = None


class Signal(BaseModel):
    """One notable moment extracted from the conversation.

    v1 splits the participant axis: ``said_by`` is the verbatim speaker
    label(s) at the turn the signal was extracted from; ``about_person``
    is the explicit subject(s) — which may or may not be in the room
    (e.g. *"Hang mentioned Tina to Andrew"* → said_by=["Hang"],
    about_person=["Tina", "Andrew"]; Tina may not be on the call at all).
    """

    # v2.2: collapsed to 3 kinds.
    # action_item    — anyone commits to a course of action, group or individual,
    #                  soft or hard. Absorbed the old "decision" kind in v2.2;
    #                  legacy DB rows carrying kind="decision" remain readable
    #                  (Pydantic ignores unknown literal values), but new
    #                  enrichment never emits decision/impactful_point.
    # open_question  — non-rhetorical question raised in the chunk that is
    #                  NOT answered within the same chunk.
    # insight        — notable nugget: specific, praiseworthy, or a synthesised
    #                  observation across a stretch of dialogue. Absorbed the
    #                  old "impactful_point" kind in v2.2.
    kind: str
    text: str
    #: Verbatim speaker label(s) at the turn this signal was anchored to.
    #: Replaces the pre-v1 ``speakers`` field. (Old DB rows carry an unused
    #: ``"speakers"`` key on the JSON until re-enriched under v2.)
    said_by: list[str] = Field(default_factory=list)
    #: Explicit subject(s) of the signal, distinct from the speaker.
    #: Empty for most signals; populated only when the model is confident
    #: about an addressee or a mentioned third party.
    about_person: list[str] = Field(default_factory=list)
    #: Verbatim quote (≤120 chars) anchoring the signal to a span in the
    #: source chunk. API-served alongside the rest of ``derived``; the C10
    #: raw-leak guard continues to protect ``raw_diarization`` (the bulk
    #: transcript blob), not these per-signal highlights.
    source_quote: Optional[str] = None


class Entity(BaseModel):
    """A person, project, technology, org, or concept mentioned — a candidate graph-node match."""

    name: str
    #: person | project | technology | org | concept
    #: "technology" was added in v1 to recover an entity class (TDX, SGX,
    #: RATLS, Whisper, Matrix, MCP, ATLS…) previously dumped into "concept".
    type: str
    evidence: str = ""  # short why-it-was-extracted note, for Layer-2 matching
    # --- v1 ---
    #: Roster status for Person entities. Set deterministically post-dedup
    #: by ``enrich._dedup_entities`` (no LLM call). Stays ``None`` for
    #: non-Person types where the concept doesn't apply.
    #:   "member"   — name matched MOCK_DIRECTORY roster
    #:   "external" — Person extracted but not in the roster (e.g. Alex (flashbots?))
    #:   "unknown"  — ambiguous parenthetical that didn't normalize
    cohort_status: Optional[Literal["member", "external", "unknown"]] = None
    #: Parenthetical affiliation hint captured by identity.resolve_identity
    #: ("Alex (flashbots?)" → affiliation="flashbots") when the base name
    #: doesn't match the roster. Powers the dashboard's "external — flashbots"
    #: chip subtitle.
    affiliation: Optional[str] = None


class Derived(BaseModel):
    """Everything the pipeline produces. All None at Layer-1 insert."""

    summary: Optional[str] = None
    signals: Optional[list[Signal]] = None
    entities: Optional[list[Entity]] = None
    #: v1: themes/areas (3-6 per chunk), deterministically dedup'd and
    #: capped at 8 in the reduce step. Distinct from entities — topics are
    #: themes ("attestation", "context management", "RAG"), entities are
    #: named things ("Phala", "Conclave"). Filters the dashboard meeting list.
    topics: Optional[list[str]] = None
    # Layer-2: ids of matched Shape Rotator OS nodes. Left None by Layer 1.
    graph_nodes: Optional[list[dict]] = None


class Session(BaseModel):
    session_id: str
    raw_diarization: list[RawSegment]  # IMMUTABLE after storage
    metadata: SessionMetadata
    derived: Derived = Field(default_factory=Derived)
    #: Server-stamped ingest timestamp (full UTC ISO, e.g. "2026-07-02T14:23:01.5Z"),
    #: projected read-only from the `transcript_sessions.created_at` column at load
    #: (Task #39 time-of-day). None for a freshly-constructed in-memory Session that
    #: hasn't round-tripped through the store yet. Not written back on save — the DB
    #: column is stamped once at insert and is authoritative.
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Part 1 — transcript refinement (the editable `v2` correction layer).
# Raw stays immutable; the user's edits + ground-truth tags live on `v2`.
# See docs/plans/transcript-refine.md §4/§15.
# ---------------------------------------------------------------------------


class TokenSpan(BaseModel):
    """A token/segment-relative anchor (NOT a flat char-range), §12 #1.

    Anchored by token index within a segment, so a single-token edit that only
    changes a word's *character* length leaves every other token's index — and
    therefore every other span — valid (the V2-9 guarantee).
    """

    segment_id: int
    token_start: int
    token_end: int  # exclusive


class CandidateAnnotation(BaseModel):
    """A span the editor renders with state. Produced by the candidate-detection
    pass (`source="nlp"`), a user correction (`"correction"`), or a manual tag
    (`"user"`). Carries an optional entity `type` once known/typed."""

    span: TokenSpan
    surface: str
    state: Literal["known", "candidate", "oov"]
    type: Optional[str] = None
    source: Literal["nlp", "correction", "user"] = "nlp"
    confidence: Optional[float] = None


class V2Segment(BaseModel):
    """One segment of the corrected document, mirroring a raw segment by index.

    `speaker_label` is the raw diarizer label copied verbatim (the immutable C3
    join key — never edited here). `speaker_name` is the v2-only confirmed
    assignment. `tokens` is the editable word list; `text` re-joins them.
    """

    segment_id: int
    speaker_label: str
    speaker_name: Optional[str] = None
    tokens: list[str] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


class TranscriptV2(BaseModel):
    """The editable, span-annotated correction layer for a session.

    Lives in the `transcript_v2` table alongside (never replacing) the immutable
    `raw_diarization`. `status` goes draft → approved (one-way in Part 1); the
    KB build (Part 2) only ever reads an `approved` v2.
    """

    session_id: str
    status: Literal["draft", "approved"] = "draft"
    segments: list[V2Segment] = Field(default_factory=list)
    annotations: list[CandidateAnnotation] = Field(default_factory=list)
    approved_at: Optional[str] = None
    #: v1 insights go stale on any edit and are re-derived on approve (§7). The
    #: flag is flipped by the edit seams WITHOUT recomputing (the latency guard).
    insights_stale: bool = False


class VocabEntry(BaseModel):
    """One per-user vocab entry — the dictionary value (docs/plans §12 #2).

    `surface_norm` is the normalized lookup key (casefold + collapsed
    whitespace). Per-user by construction; never shared across users.
    """

    user_id: str
    surface_norm: str
    is_entity: bool = True
    type: Optional[str] = None
    canonical_id: Optional[str] = None
    provenance: Literal["nlp", "correction", "user"] = "user"
