import asyncio
import logging
from contextlib import asynccontextmanager

# Load .env into os.environ BEFORE any module reads it. The route handlers
# (e.g. api/transcripts_routes.py `_load_producer_secrets`) read env vars
# directly via os.environ; pydantic-settings in config.py only populates the
# typed Settings object, not the process env. Without this, the canonical
# ingest webhook can't find producer secrets.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; works if env is set by the shell instead

from fastapi import FastAPI, Request
from fastapi.responses import Response

import storage
from api.routes import router, register_skills
from infra import pipeline_pool, scheduler
from connectors.capture import consumer as capture_consumer

logger = logging.getLogger(__name__)

# Synchronous setup runs at import — tests rely on this without needing to
# enter the lifespan context.
storage.init_db()


def _apply_migrations() -> None:
    """Apply Alembic migrations after init_db().

    Per alembic/versions/0001_baseline: `_init_schema` (init_db) owns the 8
    legacy tables; Alembic owns everything from 1.3 on (users, workspaces,
    google_oauth_tokens, …). The intended fresh-DB flow is init_db → upgrade
    head. Without this a fresh CVM DB is missing `users` etc. → 500 on login.
    Idempotent: 0001 is a no-op and later migrations are version-tracked.
    """
    import os as _os

    from alembic import command as _cmd
    from alembic.config import Config as _Cfg

    _here = _os.path.dirname(_os.path.abspath(__file__))
    _cfg = _Cfg(_os.path.join(_here, "alembic.ini"))
    _cfg.set_main_option("script_location", _os.path.join(_here, "alembic"))
    _cmd.upgrade(_cfg, "head")


_apply_migrations()
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
    capture_consumer.start()   # P1: consume the capture segment stream (no-op if REDIS_URL unset)
    try:
        yield
    finally:
        await capture_consumer.stop()
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
    # Dashboard iteration: we're actively editing JS/CSS during the demo
    # build, and stale browser caches on remote laptops have bitten us
    # (reverts not visible after server-side change). Disable HTTP caching
    # for anything under /dashboard so every reload revalidates. Cheap —
    # everything served there is small static text.
    if request.url.path.startswith("/dashboard"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(router)

# C10: transcripts read API (derived-only projection; raw never serialized).
from api.transcripts_routes import router as transcripts_router
app.include_router(transcripts_router)

# Phase 1.4: cookie-backed v1 auth surface. Coexists with the legacy
# /auth/send-otp routes in api/routes.py until the old web/ SPA is retired.
from auth.routes import router as auth_v1_router
app.include_router(auth_v1_router)

# Phase 1.5: workspace HTTP surface (list / create / details / meetings).
from api.workspaces_routes import router as workspaces_router
app.include_router(workspaces_router)

# Phase 3.5b: KB surface — entities + obligations (read-only).
from api.kb_routes import router as kb_router
app.include_router(kb_router)

# Transcript upload — paste/file into a workspace (same enrich chain as
# the Recato webhook; see api/upload_routes.py docstring).
from api.upload_routes import router as upload_router
app.include_router(upload_router)

# In-person Record ingress — capture → FPM diarize/identify + ASR → merge → ingest
# (consent plane; see api/record_routes.py docstring).
from api.record_routes import router as record_router
app.include_router(record_router)

# Phase 2.1: bot invitation + status polling.
from api.bot_routes import router as bot_router
app.include_router(bot_router)

# P1: capture microservice audio-chunk ingest (audio → Conclave TEE).
from api.capture_routes import router as capture_router
app.include_router(capture_router)

# Transcript Saving (Phase 2): account settings — transcript retention default.
from api.users_routes import router as users_router
app.include_router(users_router)

# Phase 2.4: Recato webhook receiver (replaces the standalone consumer.py
# bridge for the hosted-product path).
from api.webhooks_recato import router as recato_webhook_router
app.include_router(recato_webhook_router)

# Phase 2.10: magic-link lookup + consume (public; no auth required to
# resolve the token, but the meeting itself is still permission-gated).
from api.magic_link_routes import router as magic_link_router
app.include_router(magic_link_router)

# Google Calendar integration — dedicated OAuth connect + events +
# auto-dispatch. All routes 503 when unconfigured.
from api.calendar_routes import router as calendar_router
app.include_router(calendar_router)

# C11: stylized cohort-context dashboard. Static page served at /dashboard;
# the page calls /transcripts/sessions for its data. Vendored shape-ui (MIT).
from fastapi.staticfiles import StaticFiles
import os as _os
_web_dir = _os.path.join(_os.path.dirname(__file__), "web")
if _os.path.isdir(_web_dir):
    app.mount("/dashboard", StaticFiles(directory=_web_dir, html=True), name="dashboard")

# Mount the interview_reflection MCP plugin surface at /mcp (Step 9).
# The MCP sub-app speaks Streamable HTTP — the same transport Claude Code /
# Desktop / Cursor use in production. Auth is handled by middleware inside the
# sub-app (X-Instance-Token or Authorization: Bearer <token>).
#
# Optional: the `mcp` Python package isn't always present in dev envs (the
# transcripts dashboard, for instance, doesn't need it). Degrade gracefully
# so `transcripts.cli serve` boots without the MCP package installed.
try:
    from skills.interview_reflection.mcp_server import build_mcp_app
    app.mount("/mcp", build_mcp_app())
except ImportError as _mcp_exc:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "main: skipping /mcp mount — %s (install the `mcp` package to enable it)",
        _mcp_exc,
    )
