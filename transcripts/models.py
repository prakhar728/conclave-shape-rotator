"""Pydantic models for the transcript pipeline.

The shape mirrors the storage row in `storage.sqlite.transcript_sessions`:
a session is `raw_diarization` (immutable) + `metadata` + `derived`. At
Layer-1 insert every `derived` field is None; enrichment fills `summary`,
`signals`, and `entities`. `graph_nodes` is reserved for Layer-2 matching.
"""
from __future__ import annotations

from typing import Any, Optional

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
    # label -> {name, confidence, ...}; empty until Layer-2 speaker resolution.
    resolved_speakers: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    pipeline_version: str = PIPELINE_VERSION
    # Provenance carried through from the source when present.
    record_id: Optional[str] = None
    origin_device: Optional[str] = None
    location: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


class Signal(BaseModel):
    """One notable moment extracted from the conversation."""

    # decision | insight | impactful_point | action_item | open_question
    kind: str
    text: str
    speakers: list[str] = Field(default_factory=list)  # diarized labels involved


class Entity(BaseModel):
    """A person, project, or concept mentioned — a candidate graph-node match."""

    name: str
    type: str  # person | project | concept | org
    evidence: str = ""  # short why-it-was-extracted note, for Layer-2 matching


class Derived(BaseModel):
    """Everything the pipeline produces. All None at Layer-1 insert."""

    summary: Optional[str] = None
    signals: Optional[list[Signal]] = None
    entities: Optional[list[Entity]] = None
    # Layer-2: ids of matched Shape Rotator OS nodes. Left None by Layer 1.
    graph_nodes: Optional[list[dict]] = None


class Session(BaseModel):
    session_id: str
    raw_diarization: list[RawSegment]  # IMMUTABLE after storage
    metadata: SessionMetadata
    derived: Derived = Field(default_factory=Derived)
