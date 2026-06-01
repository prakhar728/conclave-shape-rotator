"""Read a hand-provided transcript file into a source-agnostic ``NormalizedInput``.

This is the **source seam** (`IMPLEMENTATION_PLAN.md` §G1): the *only* place
that knows the input file format. Downstream (`parse.build_session`) consumes
a ``NormalizedInput`` and never touches source specifics.

Phase 1 ships two readers:

- **Otter.ai-style transcript** (the 13 real cohort transcripts at
  ``tests/fixtures/transcripts/*.txt``). Format:

      ``Header\n<body>\n\n``  blocks, repeating.
      Header line  = ``Name  M:SS`` / ``MM:SS`` / ``H:MM:SS`` (2+ spaces
      between speaker label and timestamp; timestamp is elapsed seconds).
      Body         = every line until the next header. Blank line separates.

  Speaker labels pass through **verbatim** — plain names (``Shaw``), names
  with parentheticals (``Alex (flashbots?)``), and anonymous diarization
  labels (``Speaker 1``). Identity work happens in ``identity.py``.

- **VoxTerm / generic JSON** (the existing ``parse_transcript`` input
  shapes — kept here so parse can route through this module in C2 without
  breaking the 7 legacy tests).

Pure module: no LLM, no I/O beyond ``read_file``.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional


HEADER_RE = re.compile(r"^(.+?)\s{2,}(\d{1,3}:\d{2}(?::\d{2})?)\s*$")
ANON_SPEAKER_RE = re.compile(r"^Speaker\s+\d+$", re.IGNORECASE)
BOM = "﻿"


@dataclass
class NormalizedInput:
    """Source-agnostic transcript representation.

    ``segments``: list of ``{speaker, text, start, end}`` dicts (all four
    keys always present; ``start``/``end`` may be ``None``). Speaker labels
    are verbatim from the source.

    ``provenance``: source-specific metadata that downstream consumers may
    use. Documented keys: ``source``, ``session_id`` (str, optional),
    ``date`` (ISO ``YYYY-MM-DD``, optional), ``members`` (list[str] —
    distinct non-anonymous speakers in insertion order), ``file_path``
    (optional). Source-specific extras (``record_id``, ``origin_device``,
    ``location``, ``started_at``, ``ended_at``) flow through as additional
    keys when the source carries them.

    ``source``: short tag (``"otter"``, ``"voxterm"``, ``"whisper"`` …).
    """

    segments: list[dict] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    source: str = "unknown"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def read_file(path: os.PathLike | str) -> NormalizedInput:
    """Read a transcript file from disk → ``NormalizedInput``.

    Strips a UTF-8 BOM if present. ``.txt`` is read as Otter; ``.json`` is
    handed to ``read_obj`` after JSON parsing. The file path is recorded in
    ``provenance.file_path`` and, when the filename carries a date, in
    ``provenance.date``; otherwise falls back to the file's mtime.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.startswith(BOM):
        text = text[len(BOM):]
    if p.suffix.lower() == ".json":
        import json
        obj = json.loads(text)
        ni = read_obj(obj, path=p)
    else:
        ni = read_obj(text, source="otter", path=p)
    ni.provenance.setdefault("file_path", str(p))
    if not ni.provenance.get("date"):
        # Filename date first; mtime as last-resort fallback.
        d = _date_from_name(p.stem) or _date_from_mtime(p)
        if d:
            ni.provenance["date"] = d
    if not ni.provenance.get("session_id"):
        ni.provenance["session_id"] = _slug(p.stem)
    return ni


def read_obj(
    obj: Any,
    *,
    source: str = "otter",
    path: Optional[os.PathLike | str] = None,
) -> NormalizedInput:
    """Build a ``NormalizedInput`` from in-memory data.

    Accepts a string (Otter-style text) or a dict/list (VoxTerm/generic
    JSON shapes — see ``parse.py`` for the historical input contract).
    """
    if isinstance(obj, str):
        return _from_otter_text(obj, path=path)
    return _from_json(obj, explicit_source=source if source != "otter" else None)


# ---------------------------------------------------------------------------
# Otter reader
# ---------------------------------------------------------------------------

def _parse_otter(text: str) -> list[dict]:
    """Header-regex pass over Otter-style text → segment dicts.

    Returns ``[{speaker, text, start, end}]``. ``end`` = next segment's
    ``start``; the last segment's ``end`` stays ``None`` (the transcript
    doesn't carry audio end-time). Empty bodies are kept — a real utterance
    can be just ``"way"`` or ``"MK OSI,"``.
    """
    lines = text.split("\n")
    headers: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if m:
            headers.append((i, m.group(1).strip(), m.group(2)))
    segments: list[dict] = []
    for j, (i, speaker, ts) in enumerate(headers):
        next_i = headers[j + 1][0] if j + 1 < len(headers) else len(lines)
        body = "\n".join(lines[i + 1:next_i]).strip()
        segments.append({
            "speaker": speaker,
            "text": body,
            "start": _seconds(ts),
            "end": None,
        })
    for k in range(len(segments) - 1):
        segments[k]["end"] = segments[k + 1]["start"]
    return segments


def _from_otter_text(text: str, *, path: Optional[os.PathLike | str]) -> NormalizedInput:
    segments = _parse_otter(text)
    members: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        sp = seg["speaker"]
        if ANON_SPEAKER_RE.match(sp):
            continue
        if sp not in seen:
            seen.add(sp)
            members.append(sp)
    provenance: dict = {"source": "otter", "members": members}
    if path is not None:
        p = Path(path)
        provenance["file_path"] = str(p)
        provenance["session_id"] = _slug(p.stem)
        d = _date_from_name(p.stem)
        if d:
            provenance["date"] = d
    return NormalizedInput(segments=segments, provenance=provenance, source="otter")


def _seconds(ts: str) -> float:
    """``"1:23"`` / ``"01:23"`` / ``"1:02:03"`` → seconds (float)."""
    parts = ts.split(":")
    if len(parts) == 2:
        m, s = parts
        return float(int(m) * 60 + int(s))
    h, m, s = parts
    return float(int(h) * 3600 + int(m) * 60 + int(s))


# ---------------------------------------------------------------------------
# JSON reader (VoxTerm batch / list of batches / generic ASR shape)
# ---------------------------------------------------------------------------

def _looks_like_batch(obj: Any) -> bool:
    return isinstance(obj, dict) and "segments" in obj


def _collect_batches(raw: Any) -> tuple[list[dict], list[dict]]:
    """Return (raw_segment_dicts, source_batches). Mirrors ``parse._collect_batches``."""
    if isinstance(raw, dict):
        if _looks_like_batch(raw):
            return list(raw.get("segments") or []), [raw]
        if "raw_diarization" in raw:
            return list(raw.get("raw_diarization") or []), [raw]
        if "batches" in raw:
            batches = list(raw.get("batches") or [])
            segs: list[dict] = []
            for b in sorted(batches, key=lambda b: b.get("batch_index", 0)):
                segs.extend(b.get("segments") or [])
            return segs, batches
        return [], [raw]
    if isinstance(raw, list):
        if raw and _looks_like_batch(raw[0]):
            batches = sorted(raw, key=lambda b: b.get("batch_index", 0))
            segs: list[dict] = []
            for b in batches:
                segs.extend(b.get("segments") or [])
            return segs, batches
        return list(raw), []  # bare segment list
    raise ValueError(f"unsupported transcript input type: {type(raw).__name__}")


def _infer_source(batches: list[dict], explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    for b in batches:
        if isinstance(b, dict) and ("origin_device" in b or "record_id" in b):
            return "voxterm"
    return "unknown"


def _normalize_json_segment(seg: dict) -> Optional[dict]:
    """One raw JSON segment dict → ``{speaker, text, start, end}`` or ``None``."""
    text = str(seg.get("text") or "").strip()
    if not text:
        return None
    speaker = (
        seg.get("speaker")
        or seg.get("speaker_label")
        or (f"speaker_{seg['speaker_id']}" if "speaker_id" in seg else None)
        or "speaker_unknown"
    )
    start = seg.get("start")
    if start is None:
        start = seg.get("t")
    end = seg.get("end")
    return {
        "speaker": str(speaker),
        "text": text,
        "start": float(start) if start is not None else None,
        "end": float(end) if end is not None else None,
    }


def _from_json(obj: Any, *, explicit_source: Optional[str]) -> NormalizedInput:
    seg_dicts, batches = _collect_batches(obj)
    segments = [s for s in (_normalize_json_segment(d) for d in seg_dicts) if s is not None]
    src = _infer_source(batches, explicit_source)

    # Provenance carried through from batches (first non-empty wins).
    record_id = next((b.get("record_id") for b in batches if b.get("record_id")), None)
    origin_device = next((b.get("origin_device") for b in batches if b.get("origin_device")), None)
    location = next((b.get("location") for b in batches if b.get("location")), None)
    started_at = next((b.get("started_at") for b in batches if b.get("started_at")), None)
    ended_at = next((b.get("ended_at") for b in reversed(batches) if b.get("ended_at")), None)

    members: list[str] = []
    seen: set[str] = set()
    for s in segments:
        sp = s["speaker"]
        if ANON_SPEAKER_RE.match(sp):
            continue
        if sp not in seen:
            seen.add(sp)
            members.append(sp)

    provenance: dict = {"source": src, "members": members}
    if record_id:
        provenance["session_id"] = record_id
        provenance["record_id"] = record_id
    if origin_device:
        provenance["origin_device"] = origin_device
    if location:
        provenance["location"] = location
    if started_at:
        provenance["started_at"] = started_at
        d = _iso_date(started_at)
        if d:
            provenance["date"] = d
    if ended_at:
        provenance["ended_at"] = ended_at
    return NormalizedInput(segments=segments, provenance=provenance, source=src)


# ---------------------------------------------------------------------------
# Canonical ingest reader (webhook payload → NormalizedInput)
# ---------------------------------------------------------------------------
#
# Spec: ``STRATEGY.md`` Appendix A.3. Conclave's ``POST /transcripts/ingest``
# webhook accepts a **canonical** payload — not a producer-native one. Producers
# (Recato, in-house bots, third-party adapters) translate their native shape to
# this canonical envelope before POSTing. Keeps Conclave decoupled from any
# specific capture tool: one schema in, N producers out.
#
# Payload shape (v1):
#     {
#       "event_id", "event_type": "transcript.ingest", "api_version": "v1",
#       "produced_at", "source": "<producer-id>",
#       "meeting": {external_id, platform?, url?, title?, start_time, end_time,
#                   participants?: [str]},
#       "segments": [{start: float, end: float, text: str, speaker: str,
#                     language?: str, absolute_start?: iso, absolute_end?: iso}]
#     }
#
# Pure function — no I/O, no LLM, no network. Verification (HMAC signature,
# idempotency on event_id, async enrich kick) is the route handler's job;
# this module only knows how to *shape* the payload.

def read_canonical(payload: Any) -> NormalizedInput:
    """Convert a canonical-ingest webhook payload to ``NormalizedInput``.

    Mirrors ``_from_json``'s contract (same segment shape, same provenance
    discipline) but consumes the public canonical schema rather than any
    producer-native format. Speaker labels pass through verbatim — identity
    resolution remains a downstream concern (``identity.resolve_speakers``).
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"canonical payload must be a dict, got {type(payload).__name__}"
        )

    source = str(payload.get("source") or "unknown")
    meeting = payload.get("meeting") if isinstance(payload.get("meeting"), dict) else {}

    # Segments — same {speaker, text, start, end} shape Conclave uses internally.
    # Whisper-verbose_json fields pass through; absolute timestamps are kept in
    # provenance, not segments (segments are relative-second-floats by contract).
    raw_segments = payload.get("segments") or []
    segments: list[dict] = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start")
        end = seg.get("end")
        segments.append({
            "speaker": str(seg.get("speaker") or "speaker_unknown"),
            "text": text,
            "start": float(start) if start is not None else None,
            "end": float(end) if end is not None else None,
        })

    # Members: prefer explicit `participants` (the producer asserted who attended);
    # fall back to distinct non-anonymous speaker labels in insertion order, same
    # heuristic the Otter/JSON paths use.
    explicit_participants = meeting.get("participants") if isinstance(meeting.get("participants"), list) else None
    if explicit_participants:
        members = [str(p) for p in explicit_participants if p]
    else:
        members = []
        seen: set[str] = set()
        for s in segments:
            sp = s["speaker"]
            if ANON_SPEAKER_RE.match(sp):
                continue
            if sp not in seen:
                seen.add(sp)
                members.append(sp)

    provenance: dict = {"source": source, "members": members}

    # session_id: producer's external_id (so re-POSTing the same meeting is
    # idempotent at the storage layer too, not just the webhook).
    external_id = meeting.get("external_id")
    if external_id:
        provenance["session_id"] = str(external_id)

    # Optional meeting metadata flows through as provenance keys, matching the
    # "source-specific extras pass through" rule documented on NormalizedInput.
    for key in ("platform", "url", "title"):
        v = meeting.get(key)
        if v:
            provenance[key] = v

    start_time = meeting.get("start_time")
    if start_time:
        provenance["started_at"] = start_time
        d = _iso_date(start_time)
        if d:
            provenance["date"] = d
    end_time = meeting.get("end_time")
    if end_time:
        provenance["ended_at"] = end_time

    # Event metadata for idempotency / audit (the route uses event_id to dedupe
    # double-deliveries; preserving it here means the audit trail survives on
    # disk too).
    if payload.get("event_id"):
        provenance["event_id"] = str(payload["event_id"])
    if payload.get("produced_at"):
        provenance["produced_at"] = payload["produced_at"]
    if payload.get("api_version"):
        provenance["ingest_api_version"] = payload["api_version"]

    return NormalizedInput(segments=segments, provenance=provenance, source=source)


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Match `May 19 2026`, `May 19, 2026`, `May 19`, `_May_20`, `May_20`.
_DATE_RE = re.compile(
    r"(?<![A-Za-z])(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"[ _]+(\d{1,2})(?:[, _]+(\d{4}))?",
    re.IGNORECASE,
)


def _date_from_name(name: str) -> Optional[str]:
    """Pull an ISO date out of a filename stem. Defaults year to today's year."""
    m = _DATE_RE.search(name)
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return None
    day = int(m.group(2))
    year = int(m.group(3)) if m.group(3) else datetime.now(timezone.utc).year
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _date_from_mtime(p: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).date().isoformat()
    except OSError:
        return None


def _iso_date(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        head = value[:10]
        try:
            datetime.strptime(head, "%Y-%m-%d")
            return head
        except ValueError:
            return None


def _slug(name: str) -> str:
    """Filename stem → kebab-case ASCII slug suitable for ``session_id``."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(ch for ch in n if not unicodedata.combining(ch))
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", "-", n)
    return n.strip("-") or "session"
