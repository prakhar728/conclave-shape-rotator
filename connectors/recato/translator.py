"""Vexa/Recato TranscriptionResponse → Conclave canonical payload.

Pure data transform. No I/O, no network, no env reads. ``to_canonical`` is
the only entry point the rest of the package needs; ``consumer.py`` and
``cli.py`` both call it after fetching.

The two schemas are documented:

- Recato's ``TranscriptionResponse`` —
  ``Recato/services/meeting-api/meeting_api/schemas.py:1066``
- Conclave's canonical payload —
  ``conclave-shape-rotator/STRATEGY.md`` Appendix A.3
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4


def to_canonical(
    vexa_response: dict,
    *,
    source: str = "recato",
    event_id: Optional[str] = None,
    produced_at: Optional[str] = None,
) -> dict:
    """Translate one Vexa ``TranscriptionResponse`` dict into a canonical payload.

    Vexa's segment shape uses ``start``/``end`` as floats (its
    ``TranscriptionSegment`` aliases ``start_time``/``end_time`` → ``start``/``end``
    when serialized). The canonical schema uses the same names with the same
    semantics, so the segment translation is mostly a passthrough — speaker
    label preserved verbatim, language carried through, absolute timestamps
    promoted to their canonical names.

    Caller is responsible for HMAC-signing the JSON dump of this dict and
    POSTing it to ``/transcripts/ingest``.
    """
    if not isinstance(vexa_response, dict):
        raise TypeError(
            f"vexa_response must be a dict, got {type(vexa_response).__name__}"
        )

    # --- Meeting metadata -------------------------------------------------
    # external_id: prefer `native_meeting_id` (Recato's own stable identifier
    # for the meeting on its platform — e.g. "abc-defg-hij" for a Meet code);
    # fall back to the DB-internal `id` only if native is missing.
    external_id = vexa_response.get("native_meeting_id") or vexa_response.get("id")
    if external_id is None:
        raise ValueError("vexa_response is missing both native_meeting_id and id")
    external_id = str(external_id)

    platform = vexa_response.get("platform")
    if hasattr(platform, "value"):  # tolerate Pydantic Enum coming through
        platform = platform.value
    if platform is not None:
        platform = str(platform).lower()

    meeting = {"external_id": external_id}
    if platform:
        meeting["platform"] = platform
    if vexa_response.get("constructed_meeting_url"):
        meeting["url"] = str(vexa_response["constructed_meeting_url"])

    notes = vexa_response.get("notes")
    if notes:
        # Recato's "notes" is a freeform meeting note; treat as title for now.
        # If Recato later adds an explicit title field, prefer that.
        meeting["title"] = str(notes)[:200]

    if vexa_response.get("start_time"):
        meeting["start_time"] = _to_iso(vexa_response["start_time"])
    if vexa_response.get("end_time"):
        meeting["end_time"] = _to_iso(vexa_response["end_time"])

    # --- Segments ---------------------------------------------------------
    vexa_segments = vexa_response.get("segments") or []
    seen_speakers: list[str] = []
    seen_set: set[str] = set()
    segments: list[dict] = []
    for seg in vexa_segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start")
        if start is None:
            start = seg.get("start_time")
        end = seg.get("end")
        if end is None:
            end = seg.get("end_time")
        speaker = seg.get("speaker") or "Speaker"
        speaker = str(speaker)

        canonical_seg: dict[str, Any] = {
            "start": float(start) if start is not None else 0.0,
            "end": float(end) if end is not None else 0.0,
            "text": text,
            "speaker": speaker,
        }
        if seg.get("language"):
            canonical_seg["language"] = str(seg["language"])
        if seg.get("absolute_start_time"):
            canonical_seg["absolute_start"] = _to_iso(seg["absolute_start_time"])
        if seg.get("absolute_end_time"):
            canonical_seg["absolute_end"] = _to_iso(seg["absolute_end_time"])
        segments.append(canonical_seg)

        # Track distinct named speakers for the participants list — same
        # heuristic as `sources.read_canonical`'s fallback path.
        if speaker not in seen_set:
            seen_set.add(speaker)
            seen_speakers.append(speaker)

    if seen_speakers:
        meeting["participants"] = seen_speakers

    # --- Envelope ---------------------------------------------------------
    return {
        "event_id": event_id or f"evt_{uuid4().hex}",
        "event_type": "transcript.ingest",
        "api_version": "v1",
        "produced_at": produced_at or _utc_now(),
        "source": source,
        "meeting": meeting,
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_iso(value: Any) -> str:
    """Best-effort ISO-8601 serialization.

    Vexa typically already serializes datetimes via Pydantic so ``value`` is
    a string. When the caller hands us a Python ``datetime``, normalize it.
    """
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
