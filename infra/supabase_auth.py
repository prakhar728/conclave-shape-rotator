"""
Supabase OTP authentication helpers.

Flow:
  1. send_otp(email)          — triggers Supabase to email a 6-digit OTP to the user
  2. verify_otp(email, token) — verifies the OTP, returns the Supabase user_id on success

JWT validation uses Supabase's JWKS endpoint (ES256 / ECC P-256).
The JWKS public keys are fetched once on first use and cached in memory —
no shared secret needed, no extra network call per auth event after the first.
"""
from __future__ import annotations

import json

import httpx
import jwt
from supabase import Client, create_client

from config import settings

# Module-level JWKS cache: kid -> public key object
_jwks_cache: dict[str, object] = {}


def _client() -> Client:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise RuntimeError("Supabase is not configured (CONCLAVE_SUPABASE_URL / CONCLAVE_SUPABASE_ANON_KEY missing)")
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def supabase_enabled() -> bool:
    return bool(settings.supabase_url and settings.supabase_anon_key)


def _get_public_key(kid: str) -> object:
    """Return the cached public key for the given key ID, fetching JWKS if needed."""
    if kid not in _jwks_cache:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        resp = httpx.get(jwks_url, timeout=10)
        resp.raise_for_status()
        for jwk in resp.json().get("keys", []):
            _jwks_cache[jwk["kid"]] = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(jwk))

    if kid not in _jwks_cache:
        raise ValueError(f"No public key found for kid '{kid}' in Supabase JWKS")

    return _jwks_cache[kid]


def send_otp(email: str) -> None:
    """
    Send a 6-digit OTP email via Supabase.
    Omitting email_redirect_to signals OTP mode (not magic link).
    Also requires Email OTP to be enabled in the Supabase Auth dashboard.
    """
    _client().auth.sign_in_with_otp({
        "email": email,
        "options": {"should_create_user": True},
    })


def verify_otp(email: str, token: str) -> str:
    """
    Verify the OTP and return the Supabase user_id.

    Exchanges the OTP for a Supabase session, then validates the returned
    JWT locally using the project's ECC public key (ES256) fetched from
    the JWKS endpoint. Raises on invalid OTP, expired token, or bad signature.
    """
    response = _client().auth.verify_otp({"email": email, "token": token, "type": "email"})

    if not response.session or not response.session.access_token:
        raise ValueError("OTP verification did not return a session")

    access_token = response.session.access_token

    # Determine which key signed this JWT
    header = jwt.get_unverified_header(access_token)
    kid = header.get("kid")
    if not kid:
        raise ValueError("JWT header missing kid claim")

    public_key = _get_public_key(kid)

    payload = jwt.decode(
        access_token,
        public_key,
        algorithms=["ES256"],
        audience="authenticated",
    )

    user_id: str = payload.get("sub")
    if not user_id:
        raise ValueError("JWT missing sub claim")

    return user_id
