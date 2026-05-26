import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response

import storage
from api.routes import router, register_skills
from infra import pipeline_pool, scheduler

logger = logging.getLogger(__name__)

# Synchronous setup runs at import — tests rely on this without needing to
# enter the lifespan context.
storage.init_db()
register_skills()


async def _prewarm_models() -> None:
    """Load the embedding model weights into memory so the first /trigger
    isn't paying the disk-load cost. We deliberately do NOT call .encode()
    here — on macOS, calling encode from one thread and then re-entering it
    from a different executor thread later has caused PyTorch segfaults.

    Skipped when the pipeline pool is enabled — the worker process loads
    the model in its own initializer, isolated from the API process."""
    if pipeline_pool.enabled():
        return
    from skills.hackathon_novelty.deterministic import _get_model
    try:
        await asyncio.to_thread(_get_model)
        logger.info("startup: embedding model loaded")
    except Exception as e:
        logger.warning("startup: model pre-load failed (%s) — first /trigger will pay the cost", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pipeline_pool.start()
    await _prewarm_models()
    await scheduler.start_all()
    try:
        yield
    finally:
        await scheduler.stop_all()
        pipeline_pool.stop()


app = FastAPI(title="Conclave — NDAI Skills Service", lifespan=lifespan)


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


app.include_router(router)

# Mount the interview_reflection MCP plugin surface at /mcp (Step 9).
# The MCP sub-app speaks Streamable HTTP — the same transport Claude Code /
# Desktop / Cursor use in production. Auth is handled by middleware inside the
# sub-app (X-Instance-Token or Authorization: Bearer <token>).
from skills.interview_reflection.mcp_server import build_mcp_app

app.mount("/mcp", build_mcp_app())
