"""v1 OTP + session HTTP surface for the Conclave product.

Mounted at `/auth/v1/*`. Deliberately does NOT touch the legacy
`/auth/send-otp` routes in `api/routes.py` — those gate on `instance_id`
and serve the old skill-instance flow. Both surfaces coexist until the
old `web/` SPA is retired in Phase 1.12.

Endpoints:
- POST /auth/v1/send-otp     { email }                       → 202 { ok: true }
- POST /auth/v1/verify-otp   { email, token }                → 200 { user, workspace } + Set-Cookie
- POST /auth/v1/logout                                       → 200 { ok: true } + Set-Cookie clear
- GET  /auth/v1/me                                           → 200 { user, workspace } or 401
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr

from auth import session as auth_session
from infra import identity, workspaces
from infra.supabase_auth import send_otp as _supabase_send_otp
from infra.supabase_auth import supabase_enabled
from infra.supabase_auth import verify_otp as _supabase_verify_otp

router = APIRouter(prefix="/auth/v1", tags=["auth-v1"])


class SendOtpBody(BaseModel):
    email: EmailStr


class VerifyOtpBody(BaseModel):
    email: EmailStr
    token: str


def _require_supabase() -> None:
    if not supabase_enabled():
        raise HTTPException(
            status_code=503,
            detail="Supabase auth is not configured (CONCLAVE_SUPABASE_URL / CONCLAVE_SUPABASE_ANON_KEY missing)",
        )


def _user_to_public(u: dict) -> dict:
    """Strip Supabase-internal id from the wire shape — clients only need our id + email."""
    return {
        "id": u["id"],
        "email": u["email"],
        "display_name": u.get("display_name"),
        "created_at": u["created_at"],
    }


@router.post("/send-otp", status_code=202)
def send_otp_route(body: SendOtpBody):
    """Step 1: trigger Supabase to email a 6-digit OTP. No user row created yet."""
    _require_supabase()
    try:
        _supabase_send_otp(body.email)
    except Exception as e:  # noqa: BLE001 — surface upstream error verbatim
        raise HTTPException(status_code=502, detail=f"Failed to send OTP: {e}")
    return {"ok": True}


@router.post("/verify-otp")
def verify_otp_route(body: VerifyOtpBody, response: Response, request: Request):
    """Step 2: verify OTP, upsert User, ensure Personal workspace, set session cookie."""
    _require_supabase()

    try:
        supabase_user_id = _supabase_verify_otp(body.email, body.token.strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"OTP verification failed: {e}")

    user = identity.upsert_user_by_supabase(
        supabase_id=supabase_user_id,
        email=body.email,
    )
    workspace = workspaces.ensure_personal_workspace(user["id"])
    token = auth_session.issue_session(user["id"])
    auth_session.set_session_cookie(response, token, request=request)

    return {"user": _user_to_public(user), "workspace": workspace}


@router.post("/logout")
def logout_route(request: Request, response: Response):
    """Revoke the session in DB and clear the cookie. Idempotent."""
    token = request.cookies.get(auth_session.COOKIE_NAME)
    if not token:
        # Allow Authorization-Bearer logouts too (CLI clients).
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if token:
        auth_session.revoke_session(token)
    auth_session.clear_session_cookie(response, request=request)
    return {"ok": True}


@router.get("/me")
def me_route(user: dict = Depends(auth_session.require_current_user)):
    """Resolve cookie/bearer → user + their default workspace."""
    user_workspaces = workspaces.list_user_workspaces(user["id"])
    default_ws = user_workspaces[0] if user_workspaces else None
    return {"user": _user_to_public(user), "workspace": default_ws}
