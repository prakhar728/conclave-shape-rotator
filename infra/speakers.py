"""Speaker aggregation across sessions (Phase 3.5d C29).

Case-insensitive name match over diarization speaker labels.
DOCUMENTED LIMITATION: this is NOT cross-meeting person identity —
"Andrew Miller" in two meetings becomes one node because the strings
match, not because we resolved a person. Real identity resolution is
v1.5 (roadmap deferral table). Anonymous labels ("Speaker 1") are
excluded — they're per-session artifacts and merging them across
sessions would be wrong.
"""
from __future__ import annotations

import re

ANON_RE = re.compile(r"^speaker[\s_]*\d+$", re.IGNORECASE)


def aggregate_speakers(sessions: list) -> dict[str, dict]:
    """``sessions``: Session objects. → {key: {name, session_ids, turn_count}}.

    Key is the casefolded name; ``name`` keeps the first-seen casing.
    """
    out: dict[str, dict] = {}
    for s in sessions:
        for seg in (s.raw_diarization or []):
            label = (seg.speaker or "").strip()
            if not label or ANON_RE.match(label):
                continue
            key = label.casefold()
            if key not in out:
                out[key] = {"name": label, "session_ids": [], "turn_count": 0}
            rec = out[key]
            if s.session_id not in rec["session_ids"]:
                rec["session_ids"].append(s.session_id)
            rec["turn_count"] += 1
    return out
