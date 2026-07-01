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

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from auth import session as auth_session
from config import settings
from infra import identity, workspaces
from infra.supabase_auth import send_otp as _supabase_send_otp
from infra.supabase_auth import supabase_enabled
from infra.supabase_auth import validate_access_token as _supabase_validate
from infra.supabase_auth import verify_otp as _supabase_verify_otp

router = APIRouter(prefix="/auth/v1", tags=["auth-v1"])


class SendOtpBody(BaseModel):
    email: EmailStr


class VerifyOtpBody(BaseModel):
    email: EmailStr
    token: str


class ExchangeTokenBody(BaseModel):
    access_token: str


def _require_supabase() -> None:
    if not supabase_enabled():
        raise HTTPException(
            status_code=503,
            detail="Supabase auth is not configured (CONCLAVE_SUPABASE_URL / CONCLAVE_SUPABASE_ANON_KEY missing)",
        )


def _user_to_public(u: dict) -> dict:
    """Strip Supabase-internal id from the wire shape — clients only need our id + email."""
    from infra import tnc as _tnc

    accepted_version = u.get("tnc_version")
    return {
        "id": u["id"],
        "email": u["email"],
        "display_name": u.get("display_name"),
        "created_at": u["created_at"],
        # Config-pinned admin allowlist (CONCLAVE_ADMIN_EMAILS) — lets the client
        # reveal admin surfaces (e.g. the feedback inbox). The server re-checks on
        # every admin route; this flag is UI-only, not an authorization boundary.
        "is_admin": settings.is_admin(u["email"]),
        # Task #18: T&C acceptance state drives the blocking first-login gate.
        # `tnc_needs_acceptance` is True until the user accepts the CURRENT
        # version (a version bump re-fires the gate). UI-only: no route is
        # actually blocked server-side, but the client won't render the app
        # until this clears.
        "tnc_accepted_at": u.get("tnc_accepted_at"),
        "tnc_version": accepted_version,
        "tnc_current_version": _tnc.TNC_VERSION,
        "tnc_needs_acceptance": accepted_version != _tnc.TNC_VERSION,
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

    # Phase 2.11 — auto-grant: any meeting_shares row that was issued to
    # this user's email (before they ever signed up) gets its user_id
    # column backfilled. Permission checks key off email already, so this
    # is denormalization for analytics + future workspace-by-user queries,
    # not a fresh access grant.
    from storage.sqlite import _get_conn
    _get_conn().execute(
        "UPDATE meeting_shares SET user_id = ? "
        "WHERE user_email = ? AND user_id IS NULL",
        (user["id"], body.email),
    )
    # Task #32 — accept-on-signup: any workspace invite issued to this email before
    # they had an account becomes a membership now.
    workspaces.accept_pending_invites_for_email(body.email, user["id"])

    return {"user": _user_to_public(user), "workspace": workspace}


@router.post("/exchange-token")
def exchange_token_route(
    body: ExchangeTokenBody, response: Response, request: Request
):
    """Exchange a Supabase JWT (OAuth callback OR magic-link redirect) for
    an internal session cookie.

    Same downstream effect as `/verify-otp` — upsert User, ensure Personal
    workspace, issue session, set httpOnly cookie, backfill meeting_shares
    by email. Only differs in how the JWT was obtained: here it arrives
    pre-validated by Supabase as the result of OAuth or magic-link flow,
    whereas verify-otp obtains the JWT internally by submitting an OTP code.

    Public — the JWT signature is its own proof of authenticity (verified
    via JWKS), no other auth required.
    """
    _require_supabase()

    try:
        payload = _supabase_validate(body.access_token.strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Token validation failed: {e}")

    supabase_user_id = payload["sub"]
    email = payload.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing email claim — provider didn't share it"
        )

    user = identity.upsert_user_by_supabase(
        supabase_id=supabase_user_id, email=email
    )
    workspace = workspaces.ensure_personal_workspace(user["id"])
    token = auth_session.issue_session(user["id"])
    auth_session.set_session_cookie(response, token, request=request)

    # Mirror /verify-otp's meeting_shares.user_id backfill (Phase 2.11) so the
    # OAuth path doesn't bypass the auto-grant.
    from storage.sqlite import _get_conn
    _get_conn().execute(
        "UPDATE meeting_shares SET user_id = ? "
        "WHERE user_email = ? AND user_id IS NULL",
        (user["id"], email),
    )
    # Task #32 — accept-on-signup (OAuth/magic-link path mirrors verify-otp).
    workspaces.accept_pending_invites_for_email(email, user["id"])

    return {"user": _user_to_public(user), "workspace": workspace}


@router.get("/dev-login")
def dev_login_route(
    email: str, response: Response, request: Request, next: str | None = None,
):
    """Local-demo bypass — sign in as `email` without Supabase. Gated on CONCLAVE_DEV_LOGIN.

    Mirrors FPM's `/auth/dev-login`: upsert the user, ensure a workspace, issue a session,
    set the httpOnly cookie. With `?next=/some/path` it 303-redirects there already signed in
    (so one click lands you in the meeting); otherwise it returns JSON. NEVER enable in prod.
    """
    if os.environ.get("CONCLAVE_DEV_LOGIN", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404, detail="dev login disabled")
    e = email.strip().lower()
    user = identity.upsert_user_by_supabase(supabase_id=f"sb-{e}", email=e)
    workspace = workspaces.ensure_personal_workspace(user["id"])
    token = auth_session.issue_session(user["id"])
    if next and next.startswith("/"):  # relative paths only (no open redirect)
        resp = RedirectResponse(next, status_code=303)
        auth_session.set_session_cookie(resp, token, request=request)
        return resp
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
