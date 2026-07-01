"""FPM consent client — Conclave's side of the P4 trust-handshake seam (contract C4).

Thin async wrappers over FPM's M2M consent endpoints, reusing the same server-side
`fpm_base_url` / `fpm_api_token` the record path uses for `/v1/diarize`. The token must
carry the `knowledge` scope (in addition to `diarize`).

Confirm/deny are intentionally NOT here: those are session-authed on the FPM consent
dashboard (the data subject signing in with Google), never proxied through Conclave.
"""
from __future__ import annotations

import json
import logging
import os
import time

import httpx
from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

# Read-side consent cache (C4): {(workspace, host_user, voiceprint_id): (value, expiry)}.
# host_user is part of the key because the resolved name is host-dependent for adder-only
# edges (Task #2). A short TTL keeps the transcript read path cheap while still reflecting a
# confirm/revoke within ~a minute. Tunable via CONCLAVE_CONSENT_TTL_SEC (0 = always fresh,
# used by the two-actor demo gate). Cleared in tests via `_cache.clear()`.
_cache: dict[tuple[str, str, str], tuple[dict, float]] = {}
_CACHE_TTL_SEC = float(os.environ.get("CONCLAVE_CONSENT_TTL_SEC", "60"))
DIARIZE_TIMEOUT = float(os.environ.get("CONCLAVE_FPM_DIARIZE_TIMEOUT", "600"))  # batch diarize is slow (RTF~1.3)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.fpm_api_token}"} if settings.fpm_api_token else {}


def workspace_host_email(workspace_id: str | None) -> str | None:
    """The host identity to send to VFTE for a workspace — its owner's email (Task #2).

    VFTE computes the host-dependent candidate set from this. Until multi-member workspaces
    (#32) land, the owner IS the host of their meetings. Best-effort: any lookup miss returns
    None, and VFTE then falls back to the scope-wide floor (back-compat). Conclave gates that
    the host is a workspace member on its own side; VFTE gates the voiceprint↔scope edge.
    """
    if not workspace_id:
        return None
    try:
        from infra import identity, workspaces
        ws = workspaces.get_workspace(workspace_id)
        if not ws or not ws.get("created_by"):
            return None
        user = identity.get_user(ws["created_by"])
        return (user or {}).get("email") or None
    except Exception:  # noqa: BLE001 — never block identify on a host lookup
        logger.debug("workspace_host_email lookup failed for %s", workspace_id, exc_info=True)
        return None


def _base() -> str:
    return settings.fpm_base_url.rstrip("/")


async def propose_binding(
    workspace: str, voiceprint_id: str, *,
    proposed_email: str, proposed_by: str, proposed_name: str,
    clip_ref: dict | None = None, source: str = "tag",
    confidence: float | None = None,
) -> dict:
    """POST /v1/propose — host tags a voiceprint (name+email).

    Returns the C4 propose response `{proposal_id, status, auto_confirmed,
    voiceprint_id, name, owner_email}`. FPM auto-confirms a self-tag (proposed_by ==
    proposed_email) or when its dev flag is on.

    Task #3: `clip_ref` = {conclave_session_id, native_meeting_id, start, end} — the
    representative segment the subject can play before consenting. FPM stores the ref only.
    """
    body = {"workspace": workspace, "voiceprint_id": voiceprint_id,
            "proposed_email": proposed_email, "proposed_by": proposed_by,
            "proposed_name": proposed_name, "source": source}
    if clip_ref is not None:
        body["clip_ref"] = clip_ref
    if confidence is not None:
        body["confidence"] = confidence
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{_base()}/v1/propose", headers=_headers(), json=body)
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM propose failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def record_recognition(
    workspace: str, voiceprint_id: str, *,
    native_meeting_id: str | None = None, app: str | None = None,
    meeting_title: str | None = None,
) -> dict:
    """POST /v1/recognitions — Task #3 Part (c): tell FPM a *consented* voiceprint was
    auto-recognized so it records the event and emails the subject a transparency notice.

    We hand FPM the voiceprint_id + meeting context ONLY — never the subject's email (FPM
    owns that) and never transcript content. FPM no-ops for unclaimed / opted-out subjects.
    Best-effort: the caller swallows failures so a notify hiccup never breaks finalize.
    """
    body = {"workspace": workspace, "voiceprint_id": voiceprint_id}
    if native_meeting_id:
        body["native_meeting_id"] = native_meeting_id
    if app:
        body["app"] = app
    if meeting_title:
        body["meeting_title"] = meeting_title
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{_base()}/v1/recognitions", headers=_headers(), json=body)
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM recognitions failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def push_knowledge(
    workspace: str,
    bindings: list[dict],
    *,
    vocab_terms: list[str] | None = None,
) -> dict:
    """POST /v1/knowledge — the manual-tag feedback loop (P4).

    When a user names a speaker in a Conclave transcript, we push that name to the
    voiceprint so FUTURE meetings auto-recognize them (FPM `store.set_name`, or an
    email-binding when `email` is present). `bindings`: `[{voiceprint_id, name,
    email?}]`. Returns `{bound, not_found, vocab_terms}`. Token needs `knowledge` scope.
    """
    if not bindings and not vocab_terms:
        return {"bound": [], "not_found": [], "vocab_terms": 0}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_base()}/v1/knowledge", headers=_headers(),
            json={"workspace": workspace, "bindings": bindings,
                  "vocab_terms": vocab_terms or []},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM knowledge failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def diarize_audio(
    workspace: str,
    audio: bytes,
    *,
    tag: str = "offline",
    filename: str = "audio.wav",
    host_user: str | None = None,
) -> list[dict]:
    """POST /v1/diarize — acoustic diarization + identity on a mixed recording (P4).

    `tag="offline"` = authoritative write (post-meeting); `tag="live"` = read-only
    (mints nothing). FPM streams NDJSON: per-segment lines then a final
    `{type:"transcript", segments:[...]}` carrying the retro-relabeled authoritative
    view — we prefer that when present. Each segment:
    `{start, end, voiceprint_id, name, local_speaker, decision, confidence}`.
    Identity stays in FPM; only anonymous diarization + matched ids come back.
    """
    segments: list[dict] = []
    async with httpx.AsyncClient(timeout=DIARIZE_TIMEOUT) as client:
        async with client.stream(
            "POST", f"{_base()}/v1/diarize", headers=_headers(),
            files={"file": (filename, audio, "audio/wav")},
            # Task #2: host identity → FPM computes the host-dependent candidate set. Empty →
            # the scope-wide floor only (back-compat).
            data={"workspace": workspace, "tag": tag, "host_user": host_user or ""},
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise HTTPException(
                    502, f"FPM diarize failed ({resp.status_code}): {body[:200]!r}"
                )
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue  # heartbeat
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") == "transcript":
                    segments = obj.get("segments", segments)  # final authoritative
                elif "start" in obj:
                    segments.append(obj)  # provisional fallback if no final line
    return segments


async def notify_recognitions(
    workspace: str, fpm_segs: list[dict], *,
    native_meeting_id: str | None = None, app: str = "conclave",
    meeting_title: str | None = None,
) -> int:
    """Task #3 Part (c): after finalize, tell FPM about each recognized voiceprint so it can
    record + email the *consented* subjects (FPM no-ops unclaimed / opted-out ones).

    One notice per distinct MATCHed voiceprint (name present). Best-effort — a notify failure
    for one subject never blocks finalize or the others. Returns how many FPM actually recorded.
    """
    recorded = 0
    seen: set[str] = set()
    for s in fpm_segs or []:
        vid = s.get("voiceprint_id")
        if not vid or not s.get("name") or vid in seen:
            continue          # skip anonymous / already-notified this meeting
        seen.add(vid)
        try:
            r = await record_recognition(
                workspace, vid, native_meeting_id=native_meeting_id, app=app,
                meeting_title=meeting_title,
            )
            recorded += 1 if r.get("recorded") else 0
        except Exception:  # noqa: BLE001 — one subject's notify must not break the rest
            logger.warning("recognition notice failed for %s (finalize continues)", vid,
                           exc_info=True)
    return recorded


async def identify_spans(
    workspace: str,
    audio: bytes,
    spans: list[dict],
    *,
    tag: str = "offline",
    filename: str = "audio.wav",
    meeting_id: str | None = None,
    host_user: str | None = None,
) -> list[dict]:
    """POST /v1/identify-spans — identity ONLY, on spans capture already diarized (migration P5).

    The boundary-correct replacement for `diarize_audio`: capture diarized the recording into
    `spans` (`[{start, end, local_speaker}]`); VFTE just puts identity on them — no re-diarization.
    Same NDJSON response shape as `/v1/diarize` (per-segment lines + a final `transcript`), so the
    overlap-vote downstream is unchanged. `tag="offline"` writes, `tag="live"` is read-only.
    """
    payload_spans = [
        {"start": float(s.get("start") or 0), "end": float(s.get("end") or 0),
         "local_speaker": str(s.get("local_speaker") or s.get("speaker") or "")}
        for s in spans
    ]
    segments: list[dict] = []
    async with httpx.AsyncClient(timeout=DIARIZE_TIMEOUT) as client:
        async with client.stream(
            "POST", f"{_base()}/v1/identify-spans", headers=_headers(),
            files={"file": (filename, audio, "audio/wav")},
            data={"workspace": workspace, "tag": tag, "spans": json.dumps(payload_spans),
                  "meeting_id": meeting_id or "", "host_user": host_user or ""},
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise HTTPException(
                    502, f"FPM identify-spans failed ({resp.status_code}): {body[:200]!r}"
                )
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") == "transcript":
                    segments = obj.get("segments", segments)
                elif "start" in obj:
                    segments.append(obj)
    return segments


async def consent_resolve_batch(
    workspace: str, voiceprint_ids: list[str], *, host_user: str | None = None,
) -> dict:
    """POST /v1/consent/resolve/{workspace} — read-side name/visibility for a set of
    voiceprints. `host_user` (Task #2) applies the adder-only overlay for that host (Case 2).
    Returns the `resolved` map `{vid: {name, owner_email, visibility}}`."""
    if not voiceprint_ids:
        return {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_base()}/v1/consent/resolve/{workspace}", headers=_headers(),
            json={"voiceprint_ids": voiceprint_ids, "host_user": host_user or None},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM consent-resolve failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("resolved", {})


def _http_resolve(workspace: str, voiceprint_ids: list[str], host_user: str | None = None) -> dict:
    """Blocking POST /v1/consent/resolve/{workspace} → `resolved` map (read-path use)."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{_base()}/v1/consent/resolve/{workspace}", headers=_headers(),
            json={"voiceprint_ids": voiceprint_ids, "host_user": host_user or None},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM consent-resolve failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("resolved", {})


def consent_resolve_batch_sync(
    workspace: str, voiceprint_ids: list[str], *, host_user: str | None = None,
) -> dict:
    """Cached, synchronous consent-resolve for the transcript read path (C4 ~60s TTL).

    Serves cached entries within the TTL and only hits FPM for the missing voiceprints.
    `host_user` (Task #2) is part of the cache key — the resolved name is host-dependent for
    adder-only edges. Returns `{vid: {name, owner_email, visibility}}` for the requested ids.
    """
    now = time.monotonic()
    host = host_user or ""
    out: dict[str, dict] = {}
    missing: list[str] = []
    for vid in voiceprint_ids:
        hit = _cache.get((workspace, host, vid))
        if hit and hit[1] > now:
            out[vid] = hit[0]
        else:
            missing.append(vid)
    if missing:
        fresh = _http_resolve(workspace, missing, host_user)
        for vid, val in fresh.items():
            _cache[(workspace, host, vid)] = (val, now + _CACHE_TTL_SEC)
            out[vid] = val
    return out
