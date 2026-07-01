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

# Read-side consent cache (C4): {(workspace, voiceprint_id): (value, expiry_monotonic)}.
# A short TTL keeps the transcript read path cheap while still reflecting a confirm/revoke
# within ~a minute. Tunable via CONCLAVE_CONSENT_TTL_SEC (0 = always fresh, used by the
# two-actor demo gate). Cleared in tests via `_cache.clear()`.
_cache: dict[tuple[str, str], tuple[dict, float]] = {}
_CACHE_TTL_SEC = float(os.environ.get("CONCLAVE_CONSENT_TTL_SEC", "60"))
DIARIZE_TIMEOUT = float(os.environ.get("CONCLAVE_FPM_DIARIZE_TIMEOUT", "600"))  # batch diarize is slow (RTF~1.3)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.fpm_api_token}"} if settings.fpm_api_token else {}


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
            data={"workspace": workspace, "tag": tag},
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
                  "meeting_id": meeting_id or ""},
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
