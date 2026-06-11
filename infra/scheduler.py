"""Periodic evaluation scheduler.

One asyncio task per instance. Sleeps for `evaluation_frequency_seconds`,
then triggers the skill pipeline over the full accumulated cohort.

Lifecycle:
  - main.py lifespan: calls start_all() for every active instance on startup.
  - POST /instances: calls start_instance() for the new instance.
  - When end_date passes: a final pipeline run fires, then the task exits.

State is persisted in storage (next_run_at, last_run_at) so tasks can be
re-created cleanly after a restart without losing track of where they were.

Tests disable the scheduler entirely by setting CONCLAVE_DISABLE_SCHEDULER=1.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import storage

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}


def disabled() -> bool:
    return os.environ.get("CONCLAVE_DISABLE_SCHEDULER") == "1"


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _run_pipeline_safely(instance_id: str) -> None:
    """Trigger the pipeline for an instance, swallowing exceptions so the loop survives."""
    if storage.count_submissions(instance_id) == 0:
        logger.info("scheduler: instance %s has no submissions, skipping tick", instance_id)
        return
    # Local import to avoid a circular dependency at module load.
    from api.routes import _run_pipeline
    try:
        count = await _run_pipeline(instance_id)
        logger.info("scheduler: instance %s tick complete, %d results", instance_id, count)
    except Exception as e:
        logger.error("scheduler: pipeline failed for instance %s: %s", instance_id, e, exc_info=True)


async def _publish_final_attestation(instance_id: str) -> None:
    """Publish the final cohort report hash to Solana devnet."""
    from infra import solana
    results = storage.list_results(instance_id)
    if not results:
        logger.info("scheduler: no results to attest for instance %s", instance_id)
        return
    report_hash = solana.hash_report(results)
    loop = asyncio.get_running_loop()
    try:
        record = await loop.run_in_executor(None, solana.publish_attestation, report_hash)
    except Exception as e:
        logger.error("scheduler: solana publish errored for %s: %s", instance_id, e)
        return
    storage.record_attestation(
        instance_id=instance_id,
        report_hash=record["report_hash_hex"],
        tx_sig=record.get("tx_sig"),
        chain=record["chain"],
        extra={
            "pubkey": record.get("pubkey"),
            "explorer_url": record.get("explorer_url"),
            "status": record.get("status"),
            "error": record.get("error"),
        },
    )
    logger.info("scheduler: attestation recorded for %s status=%s", instance_id, record.get("status"))


async def _loop_for(instance_id: str) -> None:
    """Inner loop. Sleeps `evaluation_frequency_seconds`, ticks, repeats until end_date."""
    while True:
        inst = storage.get_instance(instance_id)
        if inst is None:
            logger.info("scheduler: instance %s deleted, stopping loop", instance_id)
            return
        freq = inst.get("evaluation_frequency_seconds")
        end_date_str = inst.get("end_date")
        if freq is None or end_date_str is None:
            logger.warning("scheduler: instance %s missing freq/end_date, stopping", instance_id)
            return

        end_date = _parse_iso(end_date_str)
        now = datetime.now(timezone.utc)
        if now >= end_date:
            # Final tick on the way out so the end-of-hackathon report is fresh.
            await _run_pipeline_safely(instance_id)
            await _publish_final_attestation(instance_id)
            logger.info("scheduler: instance %s reached end_date, exiting", instance_id)
            return

        # Sleep until the next tick or end_date, whichever is sooner.
        seconds_until_end = (end_date - now).total_seconds()
        delay = min(float(freq), seconds_until_end)
        try:
            await asyncio.sleep(max(delay, 0.0))
        except asyncio.CancelledError:
            logger.info("scheduler: instance %s loop cancelled", instance_id)
            return

        await _run_pipeline_safely(instance_id)


def start_instance(instance_id: str) -> None:
    """Spin up the loop for a single instance. No-op if already running or scheduler disabled."""
    if disabled():
        return
    if instance_id in _tasks and not _tasks[instance_id].done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside an event loop (e.g., during sync startup before lifespan).
        # The next start_all() during lifespan will pick it up.
        logger.warning("scheduler: no running loop, deferring start for instance %s", instance_id)
        return
    _tasks[instance_id] = loop.create_task(_loop_for(instance_id))


# --- Google Calendar auto-dispatch poller -------------------------------
# One extra asyncio task (separate from the per-instance loops) that polls
# connected users' calendars and sends the bot to soon-starting meetings.
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
    """Start tasks for every active (not-yet-ended) instance."""
    if disabled():
        logger.info("scheduler: disabled via CONCLAVE_DISABLE_SCHEDULER")
        return
    start_calendar_poll()
    now = datetime.now(timezone.utc)
    for inst in storage.list_instances():
        end_date_str = inst.get("end_date")
        if not end_date_str:
            continue  # legacy or test instance, skip
        try:
            end_date = _parse_iso(end_date_str)
        except ValueError:
            continue
        if now >= end_date:
            continue
        start_instance(inst["instance_id"])
    logger.info("scheduler: started %d instance loops", len(_tasks))


async def stop_all() -> None:
    """Cancel all running tasks. Used on app shutdown."""
    global _calendar_task
    tasks = list(_tasks.values())
    if _calendar_task is not None:
        tasks.append(_calendar_task)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _tasks.clear()
    _calendar_task = None
