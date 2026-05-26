"""Process-isolated pipeline executor.

Native crashes in the embedding stack (libtorch on macOS arm64, occasional
sentence-transformers issues) used to take the whole API down because the
pipeline ran in the same process as uvicorn. Running the pipeline in a child
process means a crash kills only the worker; the API stays up and the next
trigger transparently restarts the worker.

Gated behind CONCLAVE_PIPELINE_POOL=1 so unit tests (which patch
skill_card.run in-process) keep working unchanged.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

_pool: concurrent.futures.ProcessPoolExecutor | None = None


def enabled() -> bool:
    return os.environ.get("CONCLAVE_PIPELINE_POOL") == "1"


def _worker_init() -> None:
    """Run inside each pool worker on startup. Pre-loads the embedding model
    so the first /trigger doesn't pay the cold-start cost."""
    # Pin BLAS/tokenizer threads early — must precede any torch import.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    try:
        from skills.hackathon_novelty.deterministic import _get_model
        _get_model()
    except Exception as e:
        # Don't crash worker init — pipeline call will surface the error.
        print(f"pipeline_pool worker init: model preload failed: {e}", file=sys.stderr)


def _worker_run_pipeline(skill_name: str, inputs: list, config: Any) -> dict:
    """Top-level so it pickles cleanly across the process boundary.
    Reconstructs the skill in the worker and returns a plain dict."""
    from skills.hackathon_novelty import skill_card as hackathon_card
    cards = {"hackathon_novelty": hackathon_card}
    card = cards.get(skill_name)
    if card is None:
        raise ValueError(f"Unknown skill in worker: {skill_name}")
    response = card.run(inputs=inputs, params=config)
    return response.model_dump() if hasattr(response, "model_dump") else dict(response)


def start() -> None:
    """Spin up the pool with one worker. Idempotent. No-op if disabled."""
    global _pool
    if not enabled() or _pool is not None:
        return
    _pool = concurrent.futures.ProcessPoolExecutor(
        max_workers=1,
        initializer=_worker_init,
    )
    logger.info("pipeline_pool: started")


def stop() -> None:
    global _pool
    if _pool is None:
        return
    _pool.shutdown(wait=False, cancel_futures=True)
    _pool = None
    logger.info("pipeline_pool: stopped")


async def run(skill_name: str, inputs: list, config: Any) -> dict:
    """Submit a pipeline run. If the worker died (segfault), restart and retry once."""
    global _pool
    if _pool is None:
        start()
    assert _pool is not None
    loop = asyncio.get_running_loop()
    try:
        fut = _pool.submit(_worker_run_pipeline, skill_name, inputs, config)
        return await asyncio.wrap_future(fut, loop=loop)
    except concurrent.futures.process.BrokenProcessPool:
        logger.error("pipeline_pool: worker died (segfault?); restarting and retrying once")
        stop()
        start()
        assert _pool is not None
        fut = _pool.submit(_worker_run_pipeline, skill_name, inputs, config)
        return await asyncio.wrap_future(fut, loop=loop)
