"""Task #42 — derive a meeting's processing lifecycle for the dashboard.

The old dashboard rule was `is_processing = not summary`, which spins a
"Sharpening insights…" card FOREVER for any meeting that never produces a
summary (a cancelled recording, an empty transcript, or an enrich that failed /
never ran). This maps `metadata.enrichment_status` (+ a staleness cutoff on the
ingest timestamp) to a real lifecycle so a stuck meeting shows a "couldn't
generate insights" state with Retry + Delete instead of an eternal spinner.

Lifecycle values: ``processing`` · ``failed`` · ``done``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

#: A meeting still "pending"/"processing" this long after ingest, with no
#: terminal status, is treated as failed (a real enrich completes in ~1-2 min;
#: the queue backlog is far shorter than this). The Retry control re-enqueues.
STALE_ENRICH_MINUTES = 20

#: Terminal enrichment_status values that mean "we're done trying".
_DONE_STATUSES = {"ok", "skipped"}
_FAILED_STATUSES = {"failed"}
#: Non-terminal (still working) — subject to the staleness cutoff.
_PENDING_STATUSES = {"pending", "processing"}


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # Stored as "...Z"; datetime.fromisoformat wants +00:00 (py<3.11).
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def meeting_lifecycle(
    enrichment_status: Optional[str],
    has_summary: bool,
    created_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Map (enrichment_status, summary, ingest time) → ``processing``/``failed``/``done``.

    - A summary present, or a terminal ok/skipped status → ``done``.
    - An explicit ``failed`` status → ``failed``.
    - Otherwise still pending/processing: ``processing`` until the staleness
      cutoff elapses, then ``failed`` (a stuck card, no eternal spinner). With no
      timestamp we can't age it out, so it stays ``processing`` (legacy-safe).
    """
    status = (enrichment_status or "pending").strip().lower()
    if has_summary or status in _DONE_STATUSES:
        return "done"
    if status in _FAILED_STATUSES:
        return "failed"
    # pending / processing / unknown → age-out check.
    created = _parse_iso(created_at)
    if created is not None:
        now = now or datetime.now(timezone.utc)
        if now - created > timedelta(minutes=STALE_ENRICH_MINUTES):
            return "failed"
    return "processing"
