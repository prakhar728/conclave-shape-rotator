"""Transcript intelligence pipeline — shared context layer for cohorts/teams.

Layer 1 (this package, now): per-transcript intelligence. Take a raw diarized
transcript (e.g. a VoxTerm hivemind batch, or generic Whisper/AssemblyAI
output), parse it into an immutable structured session, and run a first-pass
LLM enrichment that fills `derived` with a summary, signals, and entities.
Sessions persist in the shared SQLite store (`storage.sqlite`).

Layer 2 (later, not built here): cross-transcript connection finding —
speaker resolution, matching `derived.entities` to Shape Rotator OS graph
nodes, similarity/relation queries across sessions, and natural-language
organizer queries. Every Layer-2 stage reads a session and writes back ONLY
to `metadata` / `derived`; `raw_diarization` is never mutated. That contract
is what lets us extend the pipeline tomorrow without reprocessing anything.
"""
from transcripts.models import (
    PIPELINE_VERSION,
    Derived,
    Entity,
    RawSegment,
    Session,
    SessionMetadata,
    Signal,
)

__all__ = [
    "PIPELINE_VERSION",
    "Derived",
    "Entity",
    "RawSegment",
    "Session",
    "SessionMetadata",
    "Signal",
]
