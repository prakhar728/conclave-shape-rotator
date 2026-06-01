"""Webhook-driven consumer: Recato `meeting.completed` → Conclave ingest.

Runs as a separate FastAPI service on its own port (default 9000). Configure
Recato to POST `meeting.completed` events to this service (Recato exposes
the `POST_MEETING_HOOKS` env var for outbound webhook URLs), and the
consumer will automatically fetch the full transcript, translate, and
forward to Conclave's canonical ingest endpoint.

For development / ad-hoc re-fetch, prefer the CLI:
    ``python -m connectors.recato fetch <platform> <meeting_id>``
which uses the same translator + same env vars but is triggered manually.

Why a separate service (not a route inside Conclave)?
- Conclave's webhook is the canonical contract; everyone speaks it.
- Recato emits a `meeting.completed` event with a *different* shape (its
  own native envelope) which would couple Conclave to Recato if we accepted
  it directly. Keeping the Recato-specific translation here preserves the
  "Conclave knows nothing about producers" property — anyone can write
  their own consumer for Otter / Granola / etc. the same way.

Auth posture:
- Recato signs its outbound webhook with HMAC-SHA256 (Vexa convention,
  inherited from upstream). We verify with `RECATO_WEBHOOK_SECRET`.
- This consumer in turn signs its outbound POST to Conclave with
  `CONCLAVE_INGEST_SECRET` (same value Conclave reads as
  `CONCLAVE_INGEST_SECRET_RECATO`).
- Two distinct secrets — one for each leg of the two-hop path.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel

from .cli import fetch_and_post  # reuse the fetch+translate+POST flow

logger = logging.getLogger(__name__)

app = FastAPI(title="connectors.recato — Recato → Conclave bridge")


class _RecatoMeetingCompleted(BaseModel):
    """Subset of Recato's webhook envelope we care about.

    Full schema lives in
    ``Recato/services/meeting-api/meeting_api/webhooks.py:_build_meeting_event_data``.
    We only need `id`, `platform`, `native_meeting_id`, `status` to fetch the
    transcript; the rest passes through to Recato's own GET endpoint.
    """
    event_id: str
    event_type: str
    api_version: str
    created_at: str
    data: dict[str, Any]


def _verify_recato_signature(body: bytes, header_value: Optional[str], secret: str) -> bool:
    """Recato signs outbound webhooks with HMAC-SHA256 (`sha256=<hex>`)."""
    if not header_value or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header_value)


@app.post("/recato/meeting-completed", status_code=status.HTTP_202_ACCEPTED)
async def on_meeting_completed(
    request: Request,
    payload: _RecatoMeetingCompleted,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
) -> dict:
    """Recato hits this when a meeting wraps up. We fetch + forward."""
    # ── 1. Verify Recato's outbound signature (if configured) ─────────────
    # The secret is optional for dev: with no RECATO_WEBHOOK_SECRET set we
    # accept unsigned webhooks. Production sets it.
    secret = os.environ.get("RECATO_WEBHOOK_SECRET")
    if secret:
        raw_body = await request.body()
        if not _verify_recato_signature(raw_body, x_signature, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="recato webhook signature mismatch",
            )

    # ── 2. Sanity: only act on completed meetings ────────────────────────
    if payload.event_type != "meeting.completed":
        logger.info("ignoring event_type=%s", payload.event_type)
        return {"status": "ignored", "reason": f"event_type {payload.event_type!r}"}

    meeting = payload.data.get("meeting") or {}
    status_str = meeting.get("status")
    if status_str and status_str != "completed":
        return {"status": "ignored", "reason": f"meeting.status {status_str!r}"}

    platform = meeting.get("platform")
    native_id = meeting.get("native_meeting_id")
    if not platform or not native_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="meeting.platform and meeting.native_meeting_id required",
        )

    # ── 3. Reuse the CLI's fetch+translate+POST flow ─────────────────────
    # fetch_and_post is synchronous (uses httpx, not httpx.AsyncClient). For
    # the demo / single-stream workloads this is fine; if Recato fires many
    # webhooks concurrently, swap to AsyncClient + asyncio.create_task.
    try:
        out = fetch_and_post(str(platform), str(native_id))
    except Exception:
        logger.exception("forward to Conclave failed for %s/%s", platform, native_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="forward to Conclave failed; see consumer logs",
        )

    return {"status": "forwarded", "conclave": out}


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe so Recato (or anything else) can verify the bridge is up."""
    return {"status": "ok", "service": "connectors.recato"}
