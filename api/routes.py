from __future__ import annotations
import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from functools import partial

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

import storage
from core.models import (
    CreateInstanceRequest,
    CreateInstanceResponse,
    CreateInterviewInstanceRequest,
    OperatorConfig,
    SkillResponse,
)
from skills.router import SkillRouter

router = APIRouter()


_DURATION_UNITS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def _parse_duration(spec: str) -> int:
    """Parse a duration string like '1w', '3d', '12h', '30m' into seconds."""
    if not spec or len(spec) < 2:
        raise ValueError(f"invalid duration: {spec!r}")
    unit = spec[-1].lower()
    if unit not in _DURATION_UNITS:
        raise ValueError(f"unknown duration unit {unit!r}; use one of w/d/h/m/s")
    try:
        n = int(spec[:-1])
    except ValueError as e:
        raise ValueError(f"invalid duration number: {spec!r}") from e
    if n <= 0:
        raise ValueError(f"duration must be positive: {spec!r}")
    return n * _DURATION_UNITS[unit]

_skill_router = SkillRouter()


def register_skills():
    """Register all skills. Called at startup."""
    from skills.hackathon_novelty import skill_card as hackathon_card
    _skill_router.register(hackathon_card)
    from skills.interview_reflection import skill_card as interview_reflection_card
    _skill_router.register(interview_reflection_card)


# --- Helpers ---

def _resolve_token(request: Request) -> dict:
    """Resolve an instance token from either Authorization: Bearer <token> or X-Instance-Token.

    Bearer is the canonical convention used by the agent skill. X-Instance-Token is preserved
    for the web UI."""
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


async def _run_pipeline(instance_id: str) -> int:
    """Validate submissions, invoke skill pipeline, store results. Returns result count."""
    inst = storage.get_instance(instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    card = _skill_router.get_card(inst["skill_name"])
    subs = storage.list_submissions(instance_id)

    try:
        inputs = [card.input_model(**s) for s in subs.values()]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Submission validation failed: {e}")

    config = OperatorConfig(**inst["config"]) if isinstance(inst["config"], dict) else inst["config"]

    from infra import pipeline_pool
    if pipeline_pool.enabled():
        # Process-isolated execution — survives native crashes (libtorch on macOS).
        response_dict = await pipeline_pool.run(inst["skill_name"], inputs, config)
        response: SkillResponse = SkillResponse(**response_dict)
    else:
        # In-process executor — required by tests that monkeypatch skill_card.run,
        # and used by default in environments where libtorch is stable (Linux).
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            partial(_skill_router.invoke, inst["skill_name"], inputs=inputs, params=config),
        )

    for r in response.results:
        storage.upsert_result(instance_id, r["submission_id"], r)

    storage.set_instance_triggered(instance_id, True)

    snapshot = _build_snapshot(response.results)
    storage.record_evaluation_run(
        instance_id=instance_id,
        submission_count=len(response.results),
        snapshot=snapshot,
    )
    return len(response.results)


def _build_snapshot(results: list[dict]) -> dict:
    """Aggregate stats captured per evaluation tick for the dashboard timeline."""
    cluster_counts: dict[str, int] = {}
    track_counts: dict[str, int] = {}
    collisions = 0
    for r in results:
        c = r.get("cluster_label")
        if c:
            cluster_counts[c] = cluster_counts.get(c, 0) + 1
        t = r.get("best_fit_track")
        if t:
            track_counts[t] = track_counts.get(t, 0) + 1
        collisions += len(r.get("name_collisions") or [])
    # Top-3 clusters and tracks for compactness
    top_clusters = sorted(cluster_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_tracks = sorted(track_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return {
        "top_clusters": [{"label": k, "count": v} for k, v in top_clusters],
        "top_tracks": [{"track": k, "count": v} for k, v in top_tracks],
        "name_collision_pairs": collisions // 2,  # each collision counted twice (once per side)
    }


# --- Endpoints ---

@router.post("/instances")
async def create_instance_endpoint(body: CreateInstanceRequest, request: Request) -> CreateInstanceResponse:
    """
    Create a new hackathon novelty instance.
    Returns the unique enclave URL the operator shares with participants and an
    admin token for the operator dashboard.
    """
    now = datetime.now(timezone.utc)
    end = body.end_date if body.end_date.tzinfo else body.end_date.replace(tzinfo=timezone.utc)
    if end <= now:
        raise HTTPException(status_code=422, detail="end_date must be in the future")

    try:
        freq_seconds = _parse_duration(body.evaluation_frequency)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    instance_id = str(uuid.uuid4())
    tracks_dump = [t.model_dump() for t in body.tracks]
    config = OperatorConfig(
        criteria={"originality": 0.5, "feasibility": 0.5},
        guidelines="",
        instance_id=instance_id,
        tracks=tracks_dump,
    )
    storage.create_instance(
        instance_id=instance_id,
        skill_name="hackathon_novelty",
        config=config.model_dump(),
        threshold=999_999,  # threshold-trigger disabled; phase 5 scheduler drives evaluation
        name=body.name,
        end_date=end.isoformat(),
        evaluation_frequency_seconds=freq_seconds,
        tracks=tracks_dump,
    )

    admin_token = secrets.token_urlsafe(16)
    storage.create_token(admin_token, instance_id, role="admin")

    # Spin up the scheduler loop for this instance immediately.
    from infra import scheduler
    scheduler.start_instance(instance_id)

    # Treat unset OR empty (compose substitution of an unset var → "") the same way:
    # fall back to the request's own base URL so /instances always returns something usable.
    base = os.environ.get("CONCLAVE_PUBLIC_URL") or str(request.base_url).rstrip("/")
    return CreateInstanceResponse(
        instance_id=instance_id,
        admin_token=admin_token,
        enclave_url=base,
    )


@router.post("/instances/interview")
async def create_interview_instance_endpoint(
    body: CreateInterviewInstanceRequest, request: Request,
) -> CreateInstanceResponse:
    """
    Create a new interview_reflection instance (V3 Track A).

    Returns the enclave URL the operator (Novel) shares with interviewees and an
    admin token for the operator surface. Unlike POST /instances (hackathon-bound),
    this endpoint has no tracks and no criteria — the skill emits themes +
    ownership prompts, not weighted scores.
    """
    now = datetime.now(timezone.utc)
    if body.end_date is None:
        end = now.replace(year=now.year + 1)
    else:
        end = body.end_date if body.end_date.tzinfo else body.end_date.replace(tzinfo=timezone.utc)
        if end <= now:
            raise HTTPException(status_code=422, detail="end_date must be in the future")

    try:
        freq_seconds = _parse_duration(body.evaluation_frequency)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    instance_id = str(uuid.uuid4())
    # interview_reflection has no criteria; pass an empty dict to satisfy
    # OperatorConfig's contract without affecting skill behaviour.
    config = OperatorConfig(
        criteria={},
        guidelines="",
        instance_id=instance_id,
    )
    storage.create_instance(
        instance_id=instance_id,
        skill_name="interview_reflection",
        config=config.model_dump(),
        threshold=999_999,            # threshold-trigger disabled; admin triggers manually
        name=body.name,
        end_date=end.isoformat(),
        evaluation_frequency_seconds=freq_seconds,
        tracks=[],
    )

    admin_token = secrets.token_urlsafe(16)
    storage.create_token(admin_token, instance_id, role="admin")

    from infra import scheduler
    scheduler.start_instance(instance_id)

    base = os.environ.get("CONCLAVE_PUBLIC_URL") or str(request.base_url).rstrip("/")
    return CreateInstanceResponse(
        instance_id=instance_id,
        admin_token=admin_token,
        enclave_url=base,
    )


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
    Canonical endpoint for the agent skill — mirrors Colosseum Copilot's PAT issuance.
    URL-as-access-control: anyone with the unique enclave URL can mint a token.
    Sybil prevention is intentionally deferred (see plans/conclave_skill_plan.md).
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


@router.get("/instances/{instance_id}")
def get_instance(instance_id: str):
    """Check if an instance exists. Used by the frontend to validate a participant URL."""
    inst = storage.get_instance(instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found or expired")
    return {
        "instance_id": instance_id,
        "skill_name": inst["skill_name"],
        "triggered": inst["triggered"],
        "submissions": storage.count_submissions(instance_id),
        "threshold": inst["threshold"],
    }


@router.get("/health")
def health():
    return {
        "status": "ok",
        "instances": storage.count_instances(),
        "submissions": storage.count_submissions(),
        "skills": _skill_router.list_skills(),
    }


@router.post("/submit")
async def submit(submission: dict, request: Request):
    """
    Accept a submission for an instance.
    Auto-triggers the pipeline when submission count reaches the threshold.
    Re-triggers on every subsequent submission so all scores stay current.
    """
    token_info = _resolve_token(request)
    instance_id = token_info["instance_id"]
    inst = storage.get_instance(instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    skill_name = inst["skill_name"]
    card = _skill_router.get_card(skill_name)

    try:
        validated = card.input_model(**submission)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Submission validation failed: {e}")

    sid = validated.submission_id
    submission = validated.model_dump()  # ensure stored dict is normalized
    submission["_submitted_at"] = datetime.utcnow().isoformat() + "Z"

    storage.upsert_submission(instance_id, sid, submission)
    storage.add_submission_to_token(token_info["_raw_token"], sid)
    count = storage.count_submissions(instance_id)

    # Pipeline triggering moved to the scheduler (phase 5). /submit is now
    # purely an ingest endpoint. Operators can still call POST /trigger to
    # force an evaluation.
    return {
        "submission_id": sid,
        "status": "received",
        "submissions_count": count,
    }


@router.get("/my-submissions")
def get_my_submissions(request: Request):
    """Return the submission IDs owned by the calling token."""
    token_info = _resolve_token(request)
    return {"submission_ids": list(token_info["submission_ids"])}


@router.get("/submissions")
def get_submissions(request: Request):
    """Return per-submission metadata for the instance. Admin only. No raw content."""
    token_info = _resolve_token(request)
    if token_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view submission metadata")

    instance_id = token_info["instance_id"]
    subs = storage.list_submissions(instance_id)

    meta = []
    for sub in subs.values():
        idea_text = sub.get("idea_text") or ""
        first_line = idea_text.split("\n", 1)[0].strip()
        title = first_line[:80] if first_line else ""
        meta.append({
            "submission_id": sub.get("submission_id", ""),
            "submitted_at": sub.get("_submitted_at"),
            "has_text": bool(idea_text),
            "has_file": bool(sub.get("idea_file")),
            "has_repo": bool(sub.get("repo_summary")),
            "idea_title_or_summary": title,
        })

    return {"submissions": meta}


@router.post("/trigger")
async def trigger(request: Request):
    """Manual pipeline trigger. Admin only. Uses stored instance config."""
    token_info = _resolve_token(request)
    if token_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can trigger manually")

    instance_id = token_info["instance_id"]
    if storage.count_submissions(instance_id) == 0:
        raise HTTPException(status_code=400, detail="No submissions to analyze")

    count = await _run_pipeline(instance_id)
    return {"status": "complete", "results_count": count}


@router.get("/results")
def get_all_results(request: Request):
    """Return all results for the instance. Admin only."""
    token_info = _resolve_token(request)
    if token_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view all results")

    instance_id = token_info["instance_id"]
    return {"results": storage.list_results(instance_id)}


@router.get("/cohort/aggregates")
def cohort_aggregates(request: Request):
    """Operator-only cohort summary: cluster + track distribution, collision count,
    cohort size, last-evaluation timestamp."""
    token_info = _resolve_token(request)
    if token_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view cohort aggregates")

    instance_id = token_info["instance_id"]
    results = storage.list_results(instance_id)

    cluster_counts: dict[str, int] = {}
    track_counts: dict[str, int] = {}
    collisions = 0
    last_at = None
    for r in results:
        c = r.get("cluster_label")
        if c:
            cluster_counts[c] = cluster_counts.get(c, 0) + 1
        t = r.get("best_fit_track")
        if t:
            track_counts[t] = track_counts.get(t, 0) + 1
        collisions += len(r.get("name_collisions") or [])

    runs = storage.list_evaluation_runs(instance_id)
    if runs:
        last_at = runs[-1]["ran_at"]

    return {
        "cohort_size": storage.count_submissions(instance_id),
        "last_evaluation_at": last_at,
        "cluster_distribution": [
            {"label": k, "count": v}
            for k, v in sorted(cluster_counts.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "track_distribution": [
            {"track": k, "count": v}
            for k, v in sorted(track_counts.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "name_collision_pairs": collisions // 2,
    }


@router.get("/cohort/timeline")
def cohort_timeline(request: Request):
    """Operator-only history of evaluation ticks for this instance."""
    token_info = _resolve_token(request)
    if token_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view cohort timeline")
    return {"runs": storage.list_evaluation_runs(token_info["instance_id"])}


@router.get("/attestations")
def list_attestations(request: Request):
    """Public-readable list of on-chain attestations for this instance.

    Anyone with a valid token (admin or user) can read so participants can
    verify the enclave published the final report they received."""
    token_info = _resolve_token(request)
    return {"attestations": storage.list_attestations(token_info["instance_id"])}


@router.post("/attestations/publish")
async def publish_attestation_now(request: Request):
    """Admin-only: force an immediate attestation publish over the current cohort.
    Useful for the demo path when waiting for end_date isn't practical."""
    token_info = _resolve_token(request)
    if token_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can publish attestations")
    instance_id = token_info["instance_id"]
    from infra.scheduler import _publish_final_attestation
    await _publish_final_attestation(instance_id)
    runs = storage.list_attestations(instance_id)
    return {"latest": runs[-1] if runs else None}


@router.get("/results/{submission_id}")
def get_results(submission_id: str, request: Request):
    """
    Return result for a single submission.
    User: only sees their own result (submission_id must match).
    Admin: can see any submission's result.
    """
    token_info = _resolve_token(request)
    instance_id = token_info["instance_id"]
    role = token_info["role"]

    result = storage.get_result(instance_id, submission_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found or not yet available")

    if role == "user":
        if submission_id not in token_info["submission_ids"]:
            raise HTTPException(status_code=403, detail="Access denied: submission not owned by this token")
        # Participant view: filtered to skill-declared user_output_keys
        inst = storage.get_instance(instance_id)
        card = _skill_router.get_card(inst["skill_name"])
        return {k: result[k] for k in card.user_output_keys if k in result}

    # admin: unrestricted access within the instance
    return result


@router.get("/skills")
def list_skills():
    """Return rich metadata for all registered skills."""
    return {"skills": _skill_router.list_cards()}


@router.get("/skills/{skill_name}")
def get_skill(skill_name: str):
    """Return metadata for a single skill."""
    try:
        return _skill_router.get_card(skill_name).metadata()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")


@router.get("/attestation")
def attestation(nonce: str = ""):
    """Return the TDX attestation quote for this enclave instance."""
    from infra.enclave import get_attestation_quote
    quote = get_attestation_quote(nonce=nonce)
    return {
        "quote": quote,
        "verify_url": "https://cloud-api.phala.network/api/v1/attestations/verify",
    }


@router.post("/fetch-repo")
async def fetch_repo(body: dict, request: Request):
    """
    Fetch a GitHub repo summary inside the TEE.
    Accepts a public repo URL (no auth) or triggers GitHub App flow for private repos.
    Input:  {"repo_url": "https://github.com/owner/repo"}
    Output: {"repo_summary": "..."}
    """
    _resolve_token(request)

    repo_url = body.get("repo_url", "").strip()
    if not repo_url:
        raise HTTPException(status_code=422, detail="repo_url is required")

    import os
    from infra.github_app import fetch_public_repo_summary, fetch_repo_summary

    app_id = os.environ.get("GITHUB_APP_ID")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

    loop = asyncio.get_event_loop()
    try:
        if app_id and installation_id:
            summary = await loop.run_in_executor(
                None, fetch_repo_summary, repo_url, app_id, installation_id
            )
        else:
            # GitHub App not configured — fall back to public repo fetch
            summary = await loop.run_in_executor(
                None, fetch_public_repo_summary, repo_url
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub fetch failed: {e}")

    return {"repo_summary": summary}
