"""Task #37 — speaker-turn coalescing (a display PROJECTION, never a raw mutation).

The pipeline emits many small per-span segments (diart streams per-finalized-span;
DiariZen also spans one person's speech). Rendering one row per span makes a single
speaker read as N fragments. `group_into_turns` merges **consecutive same-speaker
spans into one turn**, closing a turn only on a real speaker change.

Core invariant: `raw_diarization` stays span-level and immutable — a turn WRAPS its
spans (keeps their `start`/`end`/`text` under `turn["spans"]`) so per-segment clips
(#3), the v2 editor (#9), and click-to-seek (#41) still operate on spans. This is a
deterministic view; re-running it after a tag / #13-heal (names change → grouping
changes) is free.

Shared with the frontend: `frontend/src/lib/turns.ts` mirrors this exactly (the live
page coalesces the streaming spans client-side). Keep the two in lockstep.
"""
from __future__ import annotations

from typing import Any

#: Same-speaker gap (seconds) beyond which we insert a PARAGRAPH BREAK inside the
#: turn (still one turn — never a split). Configurable; a long monologue pause reads
#: better broken up. Tune here + in turns.ts together.
PARAGRAPH_GAP_SEC = 10.0


def _speaker_key(seg: dict) -> tuple:
    """The STABLE merge key for a span. Prefer the resolved identity so the same
    person merges even across different diarizer local labels; fall back to the raw
    local label so two DISTINCT unknown speakers (different labels) never merge.

    A `proposed_name` (recognized-but-unconsented, #3) is NOT a merge key — it isn't
    confirmed, so it must not silently glue two speakers together.
    """
    vid = seg.get("voiceprint_id")
    if vid:
        return ("vp", vid)
    name = seg.get("speaker_name")
    if name:
        return ("name", name)
    return ("local", seg.get("speaker"))


#: Fields copied from a turn's first (text-bearing) span onto the turn itself, so the
#: UI renders the speaker header without re-joining resolved_speakers.
_IDENTITY_FIELDS = ("speaker", "speaker_name", "proposed_name", "voiceprint_id", "consented")


def _join_text(prev_text: str, prev_end: Any, seg: dict) -> str:
    """Append a span's text to the turn's running text — a single space between
    spans, or a paragraph break when the same speaker paused longer than
    `PARAGRAPH_GAP_SEC`."""
    text = (seg.get("text") or "").strip()
    if not prev_text:
        return text
    start = seg.get("start")
    gap = None
    if isinstance(start, (int, float)) and isinstance(prev_end, (int, float)):
        gap = start - prev_end
    sep = "\n\n" if (gap is not None and gap > PARAGRAPH_GAP_SEC) else " "
    return f"{prev_text}{sep}{text}"


def group_into_turns(segments: list[dict]) -> list[dict]:
    """Coalesce consecutive same-speaker spans into turns.

    Each turn: ``{speaker, speaker_name, proposed_name, voiceprint_id, consented,
    start (first span), end (last span), text (joined), spans: [<original span
    dicts>]}``. Empty/whitespace spans never OPEN or FLIP a turn — they're absorbed
    into the open turn (span kept, `end` extended) or skipped when nothing is open.
    Input order is preserved (callers pass time-ordered spans).
    """
    turns: list[dict] = []
    open_turn: dict | None = None
    open_key: tuple | None = None

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            # Silence / empty span: never opens or flips a turn. Absorb into the
            # current turn (keep the span, extend end) so clips/seek still see it.
            if open_turn is not None:
                open_turn["spans"].append(seg)
                if seg.get("end") is not None:
                    open_turn["end"] = seg.get("end")
            continue

        key = _speaker_key(seg)
        if open_turn is not None and key == open_key:
            open_turn["text"] = _join_text(open_turn["text"], open_turn["_prev_end"], seg)
            open_turn["spans"].append(seg)
            if seg.get("end") is not None:
                open_turn["end"] = seg.get("end")
            open_turn["_prev_end"] = seg.get("end")
            continue

        # Speaker change (or first span) → close the open turn, open a new one.
        if open_turn is not None:
            turns.append(_finalize(open_turn))
        open_turn = {
            **{f: seg.get(f) for f in _IDENTITY_FIELDS},
            "start": seg.get("start"),
            "end": seg.get("end"),
            "text": text,
            "spans": [seg],
            "_prev_end": seg.get("end"),
        }
        open_key = key

    if open_turn is not None:
        turns.append(_finalize(open_turn))
    return turns


def _finalize(turn: dict) -> dict:
    turn.pop("_prev_end", None)  # internal join cursor
    return turn
