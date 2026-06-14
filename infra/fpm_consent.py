"""FPM consent client — Conclave's side of the P4 trust-handshake seam (contract C4).

Thin async wrappers over FPM's M2M consent endpoints, reusing the same server-side
`fpm_base_url` / `fpm_api_token` the record path uses for `/v1/diarize`. The token must
carry the `knowledge` scope (in addition to `diarize`).

Confirm/deny are intentionally NOT here: those are session-authed on the FPM consent
dashboard (the data subject signing in with Google), never proxied through Conclave.
"""
from __future__ import annotations

import httpx
from fastapi import HTTPException

from config import settings


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
