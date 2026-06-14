"""FPM consent client — Conclave's side of the P4 trust-handshake seam (contract C4).

Thin async wrappers over FPM's M2M consent endpoints, reusing the same server-side
`fpm_base_url` / `fpm_api_token` the record path uses for `/v1/diarize`. The token must
carry the `knowledge` scope (in addition to `diarize`).

Confirm/deny are intentionally NOT here: those are session-authed on the FPM consent
dashboard (the data subject signing in with Google), never proxied through Conclave.
"""
from __future__ import annotations

import os
import time

import httpx
from fastapi import HTTPException

from config import settings

# Read-side consent cache (C4): {(workspace, voiceprint_id): (value, expiry_monotonic)}.
# A short TTL keeps the transcript read path cheap while still reflecting a confirm/revoke
# within ~a minute. Tunable via CONCLAVE_CONSENT_TTL_SEC (0 = always fresh, used by the
# two-actor demo gate). Cleared in tests via `_cache.clear()`.
_cache: dict[tuple[str, str], tuple[dict, float]] = {}
_CACHE_TTL_SEC = float(os.environ.get("CONCLAVE_CONSENT_TTL_SEC", "60"))


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.fpm_api_token}"} if settings.fpm_api_token else {}


def _base() -> str:
    return settings.fpm_base_url.rstrip("/")


async def propose_binding(
    workspace: str, voiceprint_id: str, *,
    proposed_email: str, proposed_by: str, proposed_name: str,
) -> dict:
    """POST /v1/propose — host tags a voiceprint (name+email).

    Returns the C4 propose response `{proposal_id, status, auto_confirmed,
    voiceprint_id, name, owner_email}`. FPM auto-confirms a self-tag (proposed_by ==
    proposed_email) or when its dev flag is on.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_base()}/v1/propose", headers=_headers(),
            json={"workspace": workspace, "voiceprint_id": voiceprint_id,
                  "proposed_email": proposed_email, "proposed_by": proposed_by,
                  "proposed_name": proposed_name},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM propose failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def consent_resolve_batch(workspace: str, voiceprint_ids: list[str]) -> dict:
    """POST /v1/consent/resolve/{workspace} — read-side name/visibility for a set of
    voiceprints. Returns the `resolved` map `{vid: {name, owner_email, visibility}}`."""
    if not voiceprint_ids:
        return {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_base()}/v1/consent/resolve/{workspace}", headers=_headers(),
            json={"voiceprint_ids": voiceprint_ids},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM consent-resolve failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("resolved", {})


def _http_resolve(workspace: str, voiceprint_ids: list[str]) -> dict:
    """Blocking POST /v1/consent/resolve/{workspace} → `resolved` map (read-path use)."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{_base()}/v1/consent/resolve/{workspace}", headers=_headers(),
            json={"voiceprint_ids": voiceprint_ids},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM consent-resolve failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("resolved", {})


def consent_resolve_batch_sync(workspace: str, voiceprint_ids: list[str]) -> dict:
    """Cached, synchronous consent-resolve for the transcript read path (C4 ~60s TTL).

    Serves cached entries within the TTL and only hits FPM for the missing voiceprints.
    Returns `{vid: {name, owner_email, visibility}}` for the requested ids it could resolve.
    """
    now = time.monotonic()
    out: dict[str, dict] = {}
    missing: list[str] = []
    for vid in voiceprint_ids:
        hit = _cache.get((workspace, vid))
        if hit and hit[1] > now:
            out[vid] = hit[0]
        else:
            missing.append(vid)
    if missing:
        fresh = _http_resolve(workspace, missing)
        for vid, val in fresh.items():
            _cache[(workspace, vid)] = (val, now + _CACHE_TTL_SEC)
            out[vid] = val
    return out
