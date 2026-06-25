"""Background scheduler.

Runs the Google Calendar auto-dispatch poller: one asyncio task that polls
connected users' calendars and sends the bot to soon-starting meetings.

Lifecycle:
  - main.py lifespan calls start_all() on startup and stop_all() on shutdown.

Tests disable the scheduler entirely by setting CONCLAVE_DISABLE_SCHEDULER=1.
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def disabled() -> bool:
    return os.environ.get("CONCLAVE_DISABLE_SCHEDULER") == "1"


# --- Google Calendar auto-dispatch poller -------------------------------
_calendar_task: "asyncio.Task | None" = None


async def _calendar_poll_loop() -> None:
    """Tick every CONCLAVE_CALENDAR_POLL_SECONDS (default 60). Each tick is a
    no-op when the integration is unconfigured, so this loop is safe to run
    unconditionally once the scheduler is enabled."""
    from config import settings

    interval = float(os.environ.get("CONCLAVE_CALENDAR_POLL_SECONDS", "60"))
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("scheduler: calendar poll loop cancelled")
            return
        if not settings.google_calendar_enabled():
            continue
        try:
            from infra.calendar_dispatch import dispatch_due_meetings
            count = await asyncio.to_thread(dispatch_due_meetings)
            if count:
                logger.info("calendar poll: dispatched %d bot(s)", count)
        except Exception:  # noqa: BLE001 — keep the loop alive across failures
            logger.exception("calendar poll: tick failed")


def start_calendar_poll() -> None:
    """Start the calendar poll loop if not already running. No-op when the
    scheduler is disabled (tests) or no event loop is running yet."""
    global _calendar_task
    if disabled():
        return
    if _calendar_task is not None and not _calendar_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _calendar_task = loop.create_task(_calendar_poll_loop())


async def start_all() -> None:
    """Start background tasks on startup."""
    if disabled():
        logger.info("scheduler: disabled via CONCLAVE_DISABLE_SCHEDULER")
        return
    start_calendar_poll()
    logger.info("scheduler: started calendar poll loop")


async def stop_all() -> None:
    """Cancel running tasks. Used on app shutdown."""
    global _calendar_task
    if _calendar_task is not None:
        _calendar_task.cancel()
        await asyncio.gather(_calendar_task, return_exceptions=True)
    _calendar_task = None
