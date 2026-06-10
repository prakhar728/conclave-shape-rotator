"""Transcript retention / auto-delete (Transcript Saving, Phase 2).

Auto-delete removes ONLY the raw transcript and keeps the summary + derived
KB (see `store.purge_raw`). This module owns two pure decisions and one sweep:

- `effective_retention_days` — resolve a session's lifetime from its
  per-meeting override and the owner's account default.
- `is_expired` — has a session passed its lifetime?
- `run_retention_sweep` — purge the raw transcript of every expired,
  not-yet-purged session. Idempotent; safe to run on a schedule.

The sweep has no scheduler of its own — an external trigger (cron, the app's
own loop, or a manual call) invokes `run_retention_sweep`. That keeps the
deletion policy testable and the trigger a deployment choice.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

#: Per-meeting override sentinel: never auto-delete this session.
KEEP_FOREVER = "keep_forever"


def effective_retention_days(
    retention_override: Optional[str],
    account_default_days: Optional[int],
) -> Optional[int]:
    """Resolve a session's retention to a number of days, or None = keep forever.

    Precedence (most specific wins):
      - override == 'keep_forever'        → None (never delete this one)
      - override is a positive int string → that many days
      - override is None (inherit)        → the account default (may be None)

    A malformed override falls back to the account default rather than
    deleting aggressively — retention errs toward keeping data.
    """
    if retention_override == KEEP_FOREVER:
        return None
    if retention_override is not None:
        try:
            days = int(retention_override)
        except (ValueError, TypeError):
            return account_default_days
        return days if days > 0 else None
    return account_default_days


def _parse_ts(ts: str) -> datetime:
    """Parse a `storage.sqlite._now()` timestamp (ISO + trailing 'Z') as naive
    UTC, matching how the sweep's `now` is produced."""
    return datetime.fromisoformat(ts.replace("Z", ""))


def is_expired(created_at: str, days: Optional[int], now: datetime) -> bool:
    """True if `created_at + days` is in the past. `days is None` → never."""
    if days is None:
        return False
    return now >= _parse_ts(created_at) + timedelta(days=days)


def run_retention_sweep(now: Optional[datetime] = None) -> list[str]:
    """Purge the raw transcript of every expired, not-yet-purged session.

    Returns the list of purged session_ids. `now` is injectable for tests;
    defaults to UTC now. Account defaults are resolved once per owner.
    """
    from infra import identity
    from transcripts import store

    if now is None:
        now = datetime.utcnow()

    account_cache: dict[Optional[str], Optional[int]] = {}
    purged: list[str] = []

    for row in store.list_retention_rows():
        if row.get("raw_transcript_deleted_at"):
            continue  # already purged — idempotent
        owner = row.get("owner_user_id")
        if owner not in account_cache:
            account_cache[owner] = (
                identity.get_account_retention_days(owner) if owner else None
            )
        days = effective_retention_days(row.get("retention_override"), account_cache[owner])
        if is_expired(row["created_at"], days, now):
            store.purge_raw(row["session_id"])
            purged.append(row["session_id"])

    return purged
