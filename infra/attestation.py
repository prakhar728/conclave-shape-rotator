"""Verify a capture/diarization CVM's TDX attestation before trusting it (P5).

The capture `runtime-api` and the diarization service each expose `GET /attestation`
(see their `enclave.py`). Before Conclave routes a meeting's audio to a CVM it can
fetch + check the quote here. Off-TEE those services return a tagged stub, which we
reject only when `CONCLAVE_REQUIRE_ATTESTATION=true` (prod) and accept in dev so the
local stack runs.

⚠️ FULL measurement verification (checking the quote's MRTD/RTMRs against the
   expected pinned-image measurements) is environment-specific and NOT done here —
   it needs the dstack verifier + known-good measurements per CVM image. This is the
   gate's SHELL with an honest cutline; wire real measurement verification at deploy.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_REQUIRE = os.environ.get("CONCLAVE_REQUIRE_ATTESTATION", "false").lower() == "true"
_STUB_PREFIX = "stub_attestation_quote"


async def verify_service(base_url: str, *, nonce: str = "") -> bool:
    """Fetch `{base_url}/attestation` and decide whether to trust the CVM.

    True → acceptable. In prod (`CONCLAVE_REQUIRE_ATTESTATION=true`) a stub / missing
    quote / network error → False (don't route audio there). In dev, stubs are
    accepted so the local stack works.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/attestation", params={"nonce": nonce}
            )
        if resp.status_code != 200:
            logger.warning("attestation: %s returned %s", base_url, resp.status_code)
            return not _REQUIRE
        quote = (resp.json() or {}).get("quote", "")
    except Exception as e:  # noqa: BLE001
        logger.warning("attestation: fetch from %s failed: %s", base_url, e)
        return not _REQUIRE

    if not quote or quote.startswith(_STUB_PREFIX):
        # Not a real TDX quote — the service is off-TEE or dstack is unreachable.
        if _REQUIRE:
            logger.error(
                "attestation: %s is not in a TEE (got %r) — refusing to trust",
                base_url, quote[:40],
            )
            return False
        return True  # dev: accept the stub
    # TODO(P5): verify quote MRTD/RTMRs against the pinned-image measurements
    # (dstack verifier + known-good per-CVM measurements). Until then a real quote is
    # accepted as "present" but not measurement-checked.
    logger.info("attestation: %s presented a real TDX quote (measurement check TODO)", base_url)
    return True
