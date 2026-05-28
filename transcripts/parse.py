"""Normalize raw diarization into an immutable `Session` (derived all None).

Accepts several input shapes so the same entry point works for VoxTerm and
generic ASR tools:

- A VoxTerm hivemind batch: ``{"record_id", "started_at", "ended_at",
  "origin_device", "location"?, "segments": [{"t", "speaker", "text"}, ...]}``
  (the wire format VoxTerm POSTs to a hivemind sink).
- A list of VoxTerm batches sharing a ``record_id`` — concatenated in
  ``batch_index`` then timestamp order into one session.
- A generic transcript: ``{"segments": [{"speaker", "start", "end", "text"}]}``
  or a bare list of such segment dicts (Whisper / AssemblyAI style).

Speaker labels are passed through verbatim (``speaker_1`` etc.) — no name
resolution happens here; that's a Layer-2 concern.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from transcripts.models import Derived, RawSegment, Session, SessionMetadata


def _looks_like_batch(obj: Any) -> bool:
    return isinstance(obj, dict) and "segments" in obj


def _iso_date(value: Optional[str]) -> Optional[str]:
    """Pull a YYYY-MM-DD date out of an ISO-8601 string, tolerantly."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        # Fall back to the leading 10 chars if they parse as a date.
        head = value[:10]
        try:
            datetime.strptime(head, "%Y-%m-%d")
            return head
        except ValueError:
            return None


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalize_segment(seg: dict) -> Optional[RawSegment]:
    text = str(seg.get("text") or "").strip()
    if not text:
        return None
    speaker = (
        seg.get("speaker")
        or seg.get("speaker_label")
        or (f"speaker_{seg['speaker_id']}" if "speaker_id" in seg else None)
        or "speaker_unknown"
    )
    # VoxTerm carries a single timestamp `t`; generic ASR carries start/end.
    start = seg.get("start")
    if start is None:
        start = seg.get("t")
    end = seg.get("end")
    return RawSegment(
        speaker=str(speaker),
        text=text,
        start=float(start) if start is not None else None,
        end=float(end) if end is not None else None,
    )


def _collect_batches(raw: Any) -> tuple[list[dict], list[dict]]:
    """Return (segments, source_batches). source_batches drive provenance."""
    if isinstance(raw, dict):
        if _looks_like_batch(raw):
            return list(raw.get("segments") or []), [raw]
        if "raw_diarization" in raw:  # already-structured-ish input
            return list(raw.get("raw_diarization") or []), [raw]
        if "batches" in raw:
            batches = list(raw.get("batches") or [])
            segs: list[dict] = []
            for b in sorted(batches, key=lambda b: b.get("batch_index", 0)):
                segs.extend(b.get("segments") or [])
            return segs, batches
        # Unknown dict — treat the whole thing as a single empty-provenance batch.
        return [], [raw]
    if isinstance(raw, list):
        if raw and _looks_like_batch(raw[0]):
            batches = sorted(raw, key=lambda b: b.get("batch_index", 0))
            segs = []
            for b in batches:
                segs.extend(b.get("segments") or [])
            return segs, batches
        return list(raw), []  # bare segment list
    raise ValueError(f"unsupported transcript input type: {type(raw).__name__}")


def _infer_source(batches: list[dict], explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    # A hivemind batch is unmistakably VoxTerm: it has origin_device + record_id.
    for b in batches:
        if isinstance(b, dict) and ("origin_device" in b or "record_id" in b):
            return "voxterm"
    return "unknown"


def parse_transcript(
    raw: Any,
    *,
    source: Optional[str] = None,
    session_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Session:
    """Build an immutable `Session` from raw diarization. `derived` is all None."""
    seg_dicts, batches = _collect_batches(raw)
    segments = [s for s in (_normalize_segment(d) for d in seg_dicts) if s is not None]
    # Stable order: by start time, unknown starts last but keeping input order.
    segments.sort(key=lambda s: (s.start is None, s.start or 0.0))

    src = _infer_source(batches, source)

    # Provenance from the first batch that has it.
    record_id = next((b.get("record_id") for b in batches if b.get("record_id")), None)
    origin_device = next((b.get("origin_device") for b in batches if b.get("origin_device")), None)
    location = next((b.get("location") for b in batches if b.get("location")), None)
    started_at = next((b.get("started_at") for b in batches if b.get("started_at")), None)
    # ended_at: the last batch's, if any.
    ended_at = next((b.get("ended_at") for b in reversed(batches) if b.get("ended_at")), None)

    date = _iso_date(started_at) or _today()

    sid = session_id or record_id or _derive_session_id(date, src, segments)

    metadata = SessionMetadata(
        date=date,
        source=src,
        tags=list(tags or []),
        record_id=record_id,
        origin_device=origin_device,
        location=location,
        started_at=started_at,
        ended_at=ended_at,
    )
    return Session(
        session_id=sid,
        raw_diarization=segments,
        metadata=metadata,
        derived=Derived(),
    )


def _derive_session_id(date: str, source: str, segments: list[RawSegment]) -> str:
    """Deterministic id from content so re-ingesting the same file is idempotent."""
    h = hashlib.sha256()
    for s in segments:
        h.update(f"{s.speaker}\x1f{s.text}\x1e".encode("utf-8"))
    return f"{date}-{source}-{h.hexdigest()[:8]}"
