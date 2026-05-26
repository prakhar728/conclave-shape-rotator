"""
Layer 4 — cross-session aggregation for one interviewee.

Single interviews are noise. The Pipeline A value compounds across a sequence
of sessions for the same interviewee: which themes recur, how attribution
shifts over time, which topics show in-flight reframes.

This module owns:

    append_digest(slug, digest)            — persist one session's NovelOutput
    load_digests(slug)                     — ordered history for an interviewee
    run_aggregate(digests)                 — derive recurring themes, deltas, trajectory

Storage layout:

    data/interview_reflection/<slug>.jsonl

One line per session, append-only. Each line is the post-guardrail Novel
payload plus an ingest_timestamp. Raw transcripts are NEVER written here —
guardrails have already stripped them at this stage.

Naming note: build_pipeline.md Step 7 specifies `storage/interview_reflection/`
but `storage/` is already the Python package for SQLite-backed storage. The
on-disk data root in this repo is `data/`. The path here follows that
convention; the architecture intent is the same (append-only per-slug
ledger).

Theme matching is exact + case-insensitive in v0. Fuzzy / embedding-based
matching is a later phase (Pipeline B v0.1 clustering).
"""
from __future__ import annotations

import datetime as _dt
import json
from collections import Counter
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_ROOT = REPO_ROOT / "data" / "interview_reflection"

# Attribution trajectory thresholds — the late-session internal share has to
# move this far from the early-session share to count as a real shift.
INTERNAL_SHIFT_THRESHOLD: float = 0.15

# A theme has to appear in at least this many sessions to count as recurring.
RECURRING_MIN_SESSIONS: int = 2


# --- Storage ---

def _path_for(slug: str, root: Optional[Path] = None) -> Path:
    base = Path(root) if root is not None else DEFAULT_STORAGE_ROOT
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{slug}.jsonl"


def append_digest(slug: str, digest: dict, root: Optional[Path] = None) -> None:
    """Append one session's Novel digest to the per-slug JSONL ledger.

    Adds an `ingest_timestamp` (UTC ISO 8601) if the caller hasn't already
    set one. Raw transcripts must already have been stripped by guardrails.
    """
    record = dict(digest)
    record.setdefault("ingest_timestamp", _dt.datetime.now(_dt.UTC).isoformat())
    path = _path_for(slug, root)
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def load_digests(slug: str, root: Optional[Path] = None) -> list[dict]:
    """Return the slug's ledger as an ordered list. Empty list if no file."""
    path = _path_for(slug, root)
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --- Aggregation ---

def _normalize_theme(t: str) -> str:
    return " ".join(t.lower().split())


def _internal_share(digest: dict) -> Optional[float]:
    ap = digest.get("attribution_patterns") or {}
    internal = ap.get("internal")
    external = ap.get("external")
    if not isinstance(internal, (int, float)) or not isinstance(external, (int, float)):
        return None
    total = internal + external
    if total <= 0:
        return None
    return internal / total


def _label_trajectory(early: float, late: float) -> str:
    delta = late - early
    if delta >= INTERNAL_SHIFT_THRESHOLD:
        return "shifted_internal"
    if delta <= -INTERNAL_SHIFT_THRESHOLD:
        return "shifted_external"
    if late >= 0.6:
        return "stable_internal"
    if late <= 0.4:
        return "stable_external"
    return "stable_mixed"


def run_aggregate(digests: list[dict]) -> dict:
    """Reduce an ordered digest history to a single per-interviewee summary.

    Inputs are post-guardrail Novel payloads — themes are short strings,
    attribution_patterns is {"internal": float, "external": float}, etc.

    Returns:
        session_count, first_ingest, last_ingest,
        recurring_themes:   list of {theme, sessions, first_seen_index, last_seen_index}
        new_themes:         themes appearing only in the most recent session
        dropped_themes:     themes that appeared previously but not in the latest
        attribution_series: list of internal-share floats (None when missing)
        attribution_trajectory: label (see _label_trajectory)
        overall_assessment: short string for downstream agents to read
    """
    if not digests:
        return {
            "session_count": 0,
            "first_ingest": None,
            "last_ingest": None,
            "recurring_themes": [],
            "new_themes": [],
            "dropped_themes": [],
            "attribution_series": [],
            "attribution_trajectory": "insufficient_signal",
            "overall_assessment": "no sessions",
        }

    # Theme occurrences across sessions
    theme_first_idx: dict[str, int] = {}
    theme_last_idx: dict[str, int] = {}
    theme_sessions: Counter[str] = Counter()
    canonical_form: dict[str, str] = {}

    for idx, digest in enumerate(digests):
        themes = digest.get("themes") or []
        seen_in_this_session: set[str] = set()
        for raw in themes:
            if not isinstance(raw, str) or not raw.strip():
                continue
            norm = _normalize_theme(raw)
            if norm in seen_in_this_session:
                continue
            seen_in_this_session.add(norm)
            theme_sessions[norm] += 1
            theme_last_idx[norm] = idx
            theme_first_idx.setdefault(norm, idx)
            canonical_form.setdefault(norm, raw.strip())

    last_idx = len(digests) - 1
    recurring = []
    for norm, count in theme_sessions.most_common():
        if count >= RECURRING_MIN_SESSIONS:
            recurring.append({
                "theme": canonical_form[norm],
                "sessions": count,
                "first_seen_index": theme_first_idx[norm],
                "last_seen_index": theme_last_idx[norm],
            })

    new_themes = [
        canonical_form[n] for n, idx in theme_first_idx.items()
        if idx == last_idx and theme_sessions[n] == 1
    ]
    dropped_themes = [
        canonical_form[n] for n, idx in theme_last_idx.items()
        if idx < last_idx and theme_first_idx[n] < last_idx
    ]

    # Attribution trajectory
    series: list[Optional[float]] = [_internal_share(d) for d in digests]
    known = [(i, v) for i, v in enumerate(series) if v is not None]
    if len(known) < 2:
        trajectory = "insufficient_signal"
        assessment = (
            f"single session" if len(known) == 1
            else "no attribution signal"
        )
    else:
        early_share = known[0][1]
        late_share = known[-1][1]
        trajectory = _label_trajectory(early_share, late_share)
        assessment = _summarise(trajectory, late_share, len(digests))

    return {
        "session_count": len(digests),
        "first_ingest": digests[0].get("ingest_timestamp"),
        "last_ingest": digests[-1].get("ingest_timestamp"),
        "recurring_themes": recurring,
        "new_themes": new_themes,
        "dropped_themes": dropped_themes,
        "attribution_series": series,
        "attribution_trajectory": trajectory,
        "overall_assessment": assessment,
    }


def _summarise(trajectory: str, late_internal_share: float, n: int) -> str:
    label = {
        "shifted_internal": "shifting toward ownership",
        "shifted_external": "shifting toward external attribution",
        "stable_internal": "consistently owning",
        "stable_external": "consistently externalising",
        "stable_mixed": "mixed and stable",
        "insufficient_signal": "insufficient signal",
    }.get(trajectory, trajectory)
    return f"{n} sessions; {label}; latest internal share {late_internal_share:.2f}"
