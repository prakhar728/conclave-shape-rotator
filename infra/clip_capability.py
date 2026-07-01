"""Verify FPM-signed "hear the clip" capabilities (Task #3 Part b, Conclave side).

The data subject's FPM dashboard mints a short-lived capability signed with FPM's Ed25519
key (Task #1's receipt key). Their browser then fetches the clip straight from Conclave —
which HOLDS the audio — presenting the capability as a second auth path on the #30 audio
endpoint (so a non-member subject can hear ONLY their own segment, nothing else).

We verify the capability OFFLINE against FPM's published raw public key, reproducing FPM's
exact canonicalization (UTF-8 JSON, sorted keys, separators (",", ":")). FPM never streams
any audio bytes — it only points; Conclave verifies + serves the [start,end] slice.
"""
from __future__ import annotations

import base64
import json
import time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from config import settings

CAP_PURPOSE = "clip-cap"

# Cache of FPM's raw public key: (raw_bytes, expiry_monotonic). Short TTL so a key rotation
# is picked up within minutes without a fetch per request.
_pubkey_cache: tuple[bytes, float] | None = None
_PUBKEY_TTL_SEC = 300.0


def _canonical_bytes(payload: dict) -> bytes:
    """Byte-exact reproduction of FPM's `receipts.canonical_bytes` (the signed bytes)."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _fpm_pubkey() -> bytes | None:
    """FPM's raw Ed25519 public key — from config override, else fetched from FPM (cached).

    A `fpm_receipt_pubkey_hex` config pin avoids a network hop (and works offline/in tests);
    otherwise we GET FPM's `/v1/deletion-receipt-key` (`public_key_raw_hex`)."""
    global _pubkey_cache
    if settings.fpm_receipt_pubkey_hex:
        try:
            return bytes.fromhex(settings.fpm_receipt_pubkey_hex)
        except ValueError:
            return None
    now = time.monotonic()
    if _pubkey_cache and _pubkey_cache[1] > now:
        return _pubkey_cache[0]
    base = (settings.fpm_base_url or "").rstrip("/")
    if not base:
        return None
    try:
        headers = {"Authorization": f"Bearer {settings.fpm_api_token}"} if settings.fpm_api_token else {}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{base}/v1/deletion-receipt-key", headers=headers)
        if resp.status_code != 200:
            return None
        raw = bytes.fromhex(resp.json()["public_key_raw_hex"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    _pubkey_cache = (raw, now + _PUBKEY_TTL_SEC)
    return raw


def _unpack(cap: str) -> dict | None:
    try:
        pad = "=" * (-len(cap) % 4)
        return json.loads(base64.urlsafe_b64decode(cap + pad))
    except (ValueError, TypeError):
        return None


def verify_capability(cap: str) -> dict | None:
    """Verify a clip capability token → its payload `{purpose, clip_ref, sub, exp, ...}`, or
    None on any failure (bad signature, wrong purpose, expired, malformed, no pubkey).

    Never raises — an invalid capability is simply "no access", handled as a 403 by the caller.
    """
    if not cap:
        return None
    env = _unpack(cap)
    if not isinstance(env, dict) or "payload" not in env or "signature" not in env:
        return None
    pub = _fpm_pubkey()
    if pub is None:
        return None
    payload = env["payload"]
    try:
        sig = base64.b64decode(env["signature"])
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, _canonical_bytes(payload))
    except (InvalidSignature, ValueError, TypeError):
        return None
    if payload.get("purpose") != CAP_PURPOSE:
        return None
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        return None
    if not isinstance(payload.get("clip_ref"), dict):
        return None
    return payload
