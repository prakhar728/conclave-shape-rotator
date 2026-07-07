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
from api.routes import router
from infra import scheduler
from connectors.capture import consumer as capture_consumer
from connectors.jobs import worker as jobs_worker

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


def _seed_workspace_from_env() -> None:
    """Task #9 — idempotent boot seeder for strict link-only auth.

    Under link-only ``/auth/v1/exchange-token`` a user can only connect if they
    already have a workspace membership. This seeds the first one: if
    ``CONCLAVE_SEED_OWNER_EMAIL`` is set, ensure a workspace named
    ``CONCLAVE_SEED_WORKSPACE`` (default ``demo-ws``) exists and that the email
    holds a standing *owner* invite — so the admin's first "Connect to Conclave"
    lands them in a real workspace. Idempotent: guarded on the workspace already
    existing, so reboots don't re-seed. Never blocks boot (can't reach the DB from
    outside the sealed CVM, so seeding must happen here at startup).
    """
    import os as _os

    email = _os.environ.get("CONCLAVE_SEED_OWNER_EMAIL", "").strip().lower()
    if not email:
        return
    ws_name = _os.environ.get("CONCLAVE_SEED_WORKSPACE", "").strip() or "demo-ws"
    try:
        from infra import identity, workspaces

        # A synthetic seed-admin owns the workspace; the real admin joins via the
        # email-matched invite (works regardless of their Google `sub`).
        seed_admin = identity.upsert_user_by_supabase(
            supabase_id="seed-admin", email="seed-admin@conclave.local"
        )
        already = [
            w for w in workspaces.list_user_workspaces(seed_admin["id"])
            if w["name"] == ws_name
        ]
        if already:
            return  # already seeded — don't re-invite on every reboot
        ws = workspaces.create_workspace(ws_name, seed_admin["id"])
        workspaces.create_invite(
            ws["id"], email, role="owner", invited_by=seed_admin["id"]
        )
    except Exception as exc:  # noqa: BLE001 — seeding must never block boot
        import sys as _sys

        _sys.stderr.write(f"[seed] workspace seed skipped: {exc}\n")


# Task #25 — the demo-ws boot seeder is RETIRED: every user now auto-gets a `Personal`
# workspace on first login (auth/routes.py exchange gate), so no seed workspace/invite is
# needed. Function left defined (unused) for one release in case a rollback wants it back.
# _seed_workspace_from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await scheduler.start_all()
    capture_consumer.start()   # P1: consume the capture segment stream (no-op if REDIS_URL unset)
    jobs_worker.start()        # Task #16: drain the conclave_jobs queue (no-op if REDIS_URL unset)
    try:
        yield
    finally:
        await jobs_worker.stop()
        await capture_consumer.stop()
        await scheduler.stop_all()


app = FastAPI(title="Conclave — Confidential Team Memory", lifespan=lifespan)


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

# Live transcription view (SSE) — watch diart's live segments arrive during a meeting.
from api.live_routes import router as live_router
app.include_router(live_router)

# Transcript Saving (Phase 2): account settings — transcript retention default.
from api.users_routes import router as users_router
app.include_router(users_router)

# Phase 2.4: capture webhook receiver — finalizes a meeting (live buffer →
# translate → bind → enrich). The bot POSTs `meeting-completed` here.
from api.webhooks_capture import router as capture_webhook_router
app.include_router(capture_webhook_router)

# Task #16: diarization job-queue surface — worker audio fetch + result callback + job status.
from api.diarize_result_routes import router as diarize_result_router
app.include_router(diarize_result_router)

# Phase 2.10: magic-link lookup + consume (public; no auth required to
# resolve the token, but the meeting itself is still permission-gated).
from api.magic_link_routes import router as magic_link_router
app.include_router(magic_link_router)

# Google Calendar integration — dedicated OAuth connect + events +
# auto-dispatch. All routes 503 when unconfigured.
from api.calendar_routes import router as calendar_router
app.include_router(calendar_router)

# Task #20: host-triggered contribution of a meeting to Shape Rotator OS
# (Arm 1: approved v2 transcript → their anon context_submissions inbox).
from api.shape_contrib_routes import router as shape_contrib_router
app.include_router(shape_contrib_router)

# Task #19: in-app user feedback page → feedback table + best-effort team email.
from api.feedback_routes import router as feedback_router
app.include_router(feedback_router)

# Task #18: "download my data" export (owned-only ZIP; audio opt-in via #16 queue).
from api.export_routes import router as export_router
app.include_router(export_router)

# C11: stylized cohort-context dashboard. Static page served at /dashboard;
# the page calls /transcripts/sessions for its data. Vendored shape-ui (MIT).
from fastapi.staticfiles import StaticFiles
import os as _os
_web_dir = _os.path.join(_os.path.dirname(__file__), "web")
if _os.path.isdir(_web_dir):
    app.mount("/dashboard", StaticFiles(directory=_web_dir, html=True), name="dashboard")
