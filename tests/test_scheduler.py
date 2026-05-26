"""Unit tests for the periodic evaluation scheduler.

Validates the loop wakes up at the right cadence, ticks the pipeline,
respects end_date, and survives empty cohorts.
"""
from __future__ import annotations
import os
os.environ.setdefault("CONCLAVE_DB_PATH", ":memory:")

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

import storage
from core.models import OperatorConfig
from infra import scheduler


@pytest.fixture(autouse=True)
def clear_storage(monkeypatch):
    # Other test modules may have set CONCLAVE_DISABLE_SCHEDULER=1 at import time.
    # Force-enable for this module so scheduler tasks actually run.
    monkeypatch.delenv("CONCLAVE_DISABLE_SCHEDULER", raising=False)
    storage.reset_all()
    yield


def _seed(instance_id: str, freq_seconds: int, end_offset_seconds: int) -> None:
    config = OperatorConfig(
        criteria={"a": 1.0},
        guidelines="",
        instance_id=instance_id,
    )
    end_date = (datetime.now(timezone.utc) + timedelta(seconds=end_offset_seconds)).isoformat()
    storage.create_instance(
        instance_id=instance_id,
        skill_name="hackathon_novelty",
        config=config.model_dump(),
        threshold=999_999,
        name="test",
        end_date=end_date,
        evaluation_frequency_seconds=freq_seconds,
        tracks=[{"name": "t", "description_markdown": "x"}],
    )


@pytest.mark.asyncio
async def test_scheduler_skips_when_cohort_empty():
    """No submissions → tick fires but pipeline isn't called."""
    _seed("inst-1", freq_seconds=1, end_offset_seconds=10)

    with patch("api.routes._run_pipeline", new=AsyncMock()) as mock_pipeline:
        scheduler.start_instance("inst-1")
        await asyncio.sleep(1.2)
        # Even though tick fired, no submissions → no pipeline call
        assert mock_pipeline.await_count == 0
        await scheduler.stop_all()


@pytest.mark.asyncio
async def test_scheduler_calls_pipeline_when_cohort_has_data():
    """Submission present → tick fires → pipeline called."""
    _seed("inst-2", freq_seconds=1, end_offset_seconds=10)
    storage.upsert_submission("inst-2", "sub-1", {"submission_id": "sub-1", "idea_text": "x"})

    pipeline_mock = AsyncMock(return_value=1)
    with patch("api.routes._run_pipeline", new=pipeline_mock):
        scheduler.start_instance("inst-2")
        await asyncio.sleep(1.2)
        assert pipeline_mock.await_count >= 1
        await scheduler.stop_all()


@pytest.mark.asyncio
async def test_scheduler_stops_after_end_date():
    """end_date already past → final tick + exit."""
    _seed("inst-3", freq_seconds=1, end_offset_seconds=-1)
    storage.upsert_submission("inst-3", "sub-1", {"submission_id": "sub-1", "idea_text": "x"})

    pipeline_mock = AsyncMock(return_value=1)
    with patch("api.routes._run_pipeline", new=pipeline_mock):
        scheduler.start_instance("inst-3")
        await asyncio.sleep(0.3)
        # Single final tick fires, then loop exits.
        assert pipeline_mock.await_count == 1
        # Task should be done.
        task = scheduler._tasks.get("inst-3")
        assert task is not None
        # Give it a moment to settle.
        await asyncio.sleep(0.1)
        assert task.done()
        await scheduler.stop_all()


@pytest.mark.asyncio
async def test_scheduler_disabled_via_env():
    """CONCLAVE_DISABLE_SCHEDULER=1 → start_instance is a no-op."""
    _seed("inst-4", freq_seconds=1, end_offset_seconds=10)
    with patch.dict(os.environ, {"CONCLAVE_DISABLE_SCHEDULER": "1"}):
        scheduler.start_instance("inst-4")
        assert "inst-4" not in scheduler._tasks
