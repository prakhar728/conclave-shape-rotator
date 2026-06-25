from __future__ import annotations
import logging
import secrets

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

import storage

router = APIRouter()


# --- Helpers ---

def _resolve_token(request: Request) -> dict:
    """Resolve an instance token from either Authorization: Bearer <token> or X-Instance-Token.

    Bearer is the canonical convention; X-Instance-Token is preserved for the web UI."""
    token: str | None = None
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth and auth.startswith("Bearer "):
        token = auth[len("Bearer "):].strip()
    if not token:
        token = request.headers.get("X-Instance-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Authorization (Bearer) or X-Instance-Token header required")
    info = storage.get_token(token)
    if info is None:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    info["_raw_token"] = token
    return info


# --- Endpoints ---

@router.post("/register")
def register_user(body: dict):
    """
    Issue a unique user token for a specific instance (legacy shape used by the web UI).
    Returns {user_token}. New integrations should use POST /generate-token.
    """
    instance_id = body.get("instance_id", "").strip()
    if not instance_id or not storage.has_instance(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    token = secrets.token_urlsafe(16)
    storage.create_token(token, instance_id, role="user")
    return {"user_token": token}


@router.post("/generate-token")
def generate_token(body: dict):
    """
    Issue a participant token for an instance.
    URL-as-access-control: anyone with the unique enclave URL can mint a token.
    """
    instance_id = body.get("instance_id", "").strip()
    if not instance_id or not storage.has_instance(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    token = secrets.token_urlsafe(16)
    storage.create_token(token, instance_id, role="user")
    return {"token": token, "expires_at": None}


@router.post("/auth/send-otp")
def auth_send_otp(body: dict):
    """
    Step 1 of Supabase OTP login.
    Send a one-time password to the participant's email address.
    Requires CONCLAVE_SUPABASE_* env vars to be configured.
    """
    from infra.supabase_auth import send_otp, supabase_enabled
    if not supabase_enabled():
        raise HTTPException(status_code=503, detail="Supabase auth is not configured on this instance")

    email = (body.get("email") or "").strip()
    instance_id = (body.get("instance_id") or "").strip()

    if not email:
        raise HTTPException(status_code=422, detail="email is required")
    if not instance_id or not storage.has_instance(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        send_otp(email)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to send OTP: {e}")

    return {"status": "otp_sent", "email": email}


@router.post("/auth/verify-token")
def auth_verify_token(body: dict):
    """
    Exchange a Supabase access_token (from any OAuth provider — GitHub, Google, etc.)
    for an internal user_token. Validates the JWT locally via JWKS (ES256).
    Idempotent: same Supabase identity returns the same token per instance.
    """
    from infra.supabase_auth import supabase_enabled, _get_public_key
    import jwt as pyjwt

    if not supabase_enabled():
        raise HTTPException(status_code=503, detail="Supabase auth is not configured on this instance")

    access_token = (body.get("access_token") or "").strip()
    instance_id = (body.get("instance_id") or "").strip()

    if not access_token:
        raise HTTPException(status_code=422, detail="access_token is required")
    if not instance_id or not storage.has_instance(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        header = pyjwt.get_unverified_header(access_token)
        kid = header.get("kid")
        if not kid:
            raise ValueError("JWT missing kid")
        public_key = _get_public_key(kid)
        payload = pyjwt.decode(access_token, public_key, algorithms=["ES256"], audience="authenticated")
        supabase_user_id = payload.get("sub")
        if not supabase_user_id:
            raise ValueError("JWT missing sub")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token validation failed: {e}")

    existing = storage.get_registration_token(instance_id, supabase_user_id)
    if existing:
        return {"user_token": existing}

    user_token = secrets.token_urlsafe(16)
    storage.create_token(user_token, instance_id, role="user", supabase_user_id=supabase_user_id)
    storage.set_registration_token(instance_id, supabase_user_id, user_token)
    return {"user_token": user_token}


@router.post("/auth/verify-otp")
def auth_verify_otp(body: dict):
    """
    Step 2 of Supabase OTP login.
    Verify the OTP, validate the returned JWT locally, and issue an internal user token.
    Idempotent: the same Supabase identity gets the same token for a given instance.
    """
    from infra.supabase_auth import verify_otp, supabase_enabled
    if not supabase_enabled():
        raise HTTPException(status_code=503, detail="Supabase auth is not configured on this instance")

    email = (body.get("email") or "").strip()
    token = (body.get("token") or "").strip()
    instance_id = (body.get("instance_id") or "").strip()

    if not email or not token:
        raise HTTPException(status_code=422, detail="email and token are required")
    if not instance_id or not storage.has_instance(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        supabase_user_id = verify_otp(email, token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"OTP verification failed: {e}")

    existing = storage.get_registration_token(instance_id, supabase_user_id)
    if existing:
        return {"user_token": existing}

    user_token = secrets.token_urlsafe(16)
    storage.create_token(user_token, instance_id, role="user", supabase_user_id=supabase_user_id)
    storage.set_registration_token(instance_id, supabase_user_id, user_token)
    return {"user_token": user_token}


@router.get("/me")
def get_me(request: Request):
    """Resolve an admin or user token to its instance_id and role."""
    token_info = _resolve_token(request)
    return {"instance_id": token_info["instance_id"], "role": token_info["role"]}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/attestation")
def attestation(nonce: str = ""):
    """Return the TDX attestation quote for this enclave instance."""
    from infra.enclave import get_attestation_quote
    quote = get_attestation_quote(nonce=nonce)
    return {
        "quote": quote,
        "verify_url": "https://cloud-api.phala.network/api/v1/attestations/verify",
    }
