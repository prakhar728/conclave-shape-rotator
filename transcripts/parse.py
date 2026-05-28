"""Generic normalizer: ``NormalizedInput`` → immutable ``Session``.

After the C2 refactor (`IMPLEMENTATION_PLAN.md` §G3), this module no longer
knows about VoxTerm batches, file formats, or origin devices. Source-shaped
reading lives in ``sources.py``; this module *only* turns a source-agnostic
``NormalizedInput`` into a ``Session`` with ``derived = Derived()``.

The convenience entry point ``parse_transcript(raw, ...)`` is preserved so
existing callers (tests, CLI) keep working — it now thins down to
``sources.read_obj`` + ``build_session``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from transcripts.models import Derived, RawSegment, Session, SessionMetadata
from transcripts.sources import NormalizedInput, read_obj


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_session(
    norm: NormalizedInput,
    *,
    session_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Session:
    """Turn a ``NormalizedInput`` into an immutable ``Session``.

    ``session_id`` precedence: explicit arg > ``provenance.session_id``
    (which sources sets to ``record_id`` for VoxTerm and a filename slug
    for Otter) > a content hash. ``derived`` is left empty — enrichment
    fills it in a later pass.
    """
    segments = _segments(norm)
    sid = _session_id(norm, session_id, segments)
    metadata = _metadata(norm, tags)
    return Session(
        session_id=sid,
        raw_diarization=segments,
        metadata=metadata,
        derived=Derived(),
    )


def parse_transcript(
    raw: Any,
    *,
    source: Optional[str] = None,
    session_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Session:
    """Backwards-compatible entry: ``raw`` (any shape) → ``Session``.

    Defers source-shape reading to ``sources.read_obj`` and then builds the
    session generically. The historical 7 tests in
    ``tests/test_transcript_pipeline.py`` exercise this path.
    """
    # ``sources.read_obj`` treats ``source="otter"`` as the *default* string
    # parser; for non-string raw inputs that default is harmless (it only
    # matters when ``raw`` is a str).
    ni = read_obj(raw, source=source or "otter")
    if source:
        # Caller wants this source label even if the JSON has no batch hints.
        ni.provenance["source"] = source
        ni.source = source
    return build_session(ni, session_id=session_id, tags=tags)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _segments(norm: NormalizedInput) -> list[RawSegment]:
    """Validate, drop blank-text, sort by start (unknowns last in input order)."""
    out: list[RawSegment] = []
    for d in norm.segments:
        text = str(d.get("text") or "").strip()
        # Note: ``sources._parse_otter`` keeps empty bodies (per §G1) — a real
        # utterance can be just punctuation. Here in the generic normalizer
        # we still drop pure-whitespace text, matching pre-refactor behavior.
        if not text:
            continue
        speaker = str(d.get("speaker") or "speaker_unknown")
        start = d.get("start")
        end = d.get("end")
        out.append(
            RawSegment(
                speaker=speaker,
                text=text,
                start=float(start) if start is not None else None,
                end=float(end) if end is not None else None,
            )
        )
    out.sort(key=lambda s: (s.start is None, s.start or 0.0))
    return out


def _session_id(
    norm: NormalizedInput,
    override: Optional[str],
    segments: list[RawSegment],
) -> str:
    if override:
        return override
    pid = norm.provenance.get("session_id")
    if pid:
        return str(pid)
    date = norm.provenance.get("date") or _today()
    return _derive_session_id(date, norm.source, segments)


def _metadata(norm: NormalizedInput, tags: Optional[list[str]]) -> SessionMetadata:
    prov = norm.provenance
    date = prov.get("date") or _today()
    return SessionMetadata(
        date=date,
        source=prov.get("source") or norm.source or "unknown",
        tags=list(tags or []),
        record_id=prov.get("record_id"),
        origin_device=prov.get("origin_device"),
        location=prov.get("location"),
        started_at=prov.get("started_at"),
        ended_at=prov.get("ended_at"),
    )


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _derive_session_id(date: str, source: str, segments: list[RawSegment]) -> str:
    """Deterministic id from content so re-ingesting the same file is idempotent."""
    h = hashlib.sha256()
    for s in segments:
        h.update(f"{s.speaker}\x1f{s.text}\x1e".encode("utf-8"))
    return f"{date}-{source}-{h.hexdigest()[:8]}"
