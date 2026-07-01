"""In-person Record ingress — Conclave ingress mode 3 (bot · upload · record).

POST /api/workspaces/{workspace_id}/record   (multipart: file=<audio>, intent?)

A clip recorded in the browser is orchestrated server-side: sent to FPM
(`/v1/diarize`, which diarizes AND identifies against the workspace's consented
voiceprints) and, in parallel, to the NEAR Whisper transcription-service for the
words. The two are merged by timestamp into `[speaker] text` segments and handed
to the SAME ingest path the paste/upload endpoint uses — so a recorded meeting
becomes an ordinary Conclave session (reusing meeting/[id]) for free.

The FPM and transcription tokens live in server config, never in the browser, and
FPM is the only place consent is enforced (a "stay anonymous" speaker comes back
unnamed; a forgotten one comes back as an unknown speaker). Audio is processed and
discarded here — only the derived transcript is stored.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from api.workspaces_routes import _require_member
from auth.session import require_current_user
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["record"])

#: cap on an uploaded recording (~25 MB ≈ several minutes of opus/webm).
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _best_overlap(start: float, end: float, idsegs: list[dict]) -> Optional[dict]:
    """The identity segment with the most time-overlap with [start, end]."""
    best, best_ov = None, 0.0
    for d in idsegs:
        ds, de = float(d.get("start") or 0.0), float(d.get("end") or 0.0)
        ov = min(end, de) - max(start, ds)
        if ov > best_ov:
            best, best_ov = d, ov
    if best is not None:
        return best
    mid = (start + end) / 2.0
    for d in idsegs:  # fallback: the segment whose span contains the ASR midpoint
        if float(d.get("start") or 0.0) <= mid <= float(d.get("end") or 0.0):
            return d
    return idsegs[0] if idsegs else None


def _speaker_key(d: dict) -> str:
    """Stable cross-pass identity key for one identity segment.

    Prefers ``voiceprint_id`` (the only key that survives an engine swap and
    agrees between the live and post passes — architecture C1/C2). Falls back
    to ``local_speaker`` when no voiceprint is present: the live read-only pass
    (P1) mints nothing, and the post confidence gate (P3) leaves
    permanently-unnameable speakers at ``voiceprint_id=None`` — in both cases
    two distinct speakers must stay distinct, so the engine-private cluster id
    is the fallback. ``"spk"`` is the last resort for malformed segments.
    """
    return d.get("voiceprint_id") or d.get("local_speaker") or "spk"


def _label_index(identity_segments: list[dict]) -> dict[str, int]:
    """``{speaker_key: N}`` numbered 1..k by **sorted** key.

    Deterministic by construction: the same set of voiceprints yields the same
    ``Speaker N`` regardless of who spoke first or which engine ran. This is
    what makes the live→post replace safe — re-running the post pass on the
    same audio reproduces identical labels, so already-enriched ``said_by``
    labels keep joining (architecture C3). The order across live (keyed by
    ``local_speaker``) and post (keyed by minted ``voiceprint_id``) may differ
    for *unknowns*, which is fine: the post pass replaces the live transcript
    wholesale (architecture §10).
    """
    keys = sorted({_speaker_key(d) for d in identity_segments})
    return {k: i + 1 for i, k in enumerate(keys)}


def merge_by_timestamp(asr_segments: list[dict], identity_segments: list[dict]) -> list[dict]:
    """ASR words ∥ FPM identity → `[{speaker, text, start, end}]` (the batch merge).

    A named voiceprint shows its name; an anonymous/suppressed one shows
    `Speaker N`, numbered **deterministically by sorted speaker key** (see
    `_label_index`), not by first appearance. So 2 known + 1 unknown reads as
    `[Alice] … [Bob] … [Speaker 3] …`, and the same identities always map to
    the same labels across re-runs and the live→post swap.

    `voiceprint_id` is intentionally **not** carried onto the returned segments:
    it cannot survive the upload re-parse (`sources._normalize_json_segment`
    strips to `{speaker,text,start,end}`) and must not ride on the immutable
    `RawSegment`. It is persisted separately via `build_resolved_speakers`.
    """
    idsegs = sorted(identity_segments, key=lambda s: float(s.get("start") or 0.0))
    index = _label_index(identity_segments)

    def label_for(d: Optional[dict]) -> str:
        if d is None:
            return "Speaker 1"
        return d.get("name") or f"Speaker {index.get(_speaker_key(d), '?')}"

    out: list[dict] = []
    for a in asr_segments:
        text = (a.get("text") or "").strip()
        if not text:
            continue
        start = float(a.get("start") or 0.0)
        end = float(a.get("end") or start)
        out.append({
            "speaker": label_for(_best_overlap(start, end, idsegs)),
            "text": text,
            "start": round(start, 3),
            "end": round(end, 3),
        })
    return out


def build_resolved_speakers(identity_segments: list[dict]) -> dict[str, dict]:
    """FPM identity segments → C3 `resolved_speakers` (the P2 persistence).

    `{display_label: {voiceprint_id, name, confidence}}`, keyed by the **same**
    display label `merge_by_timestamp` assigns, so it joins the persisted
    `RawSegment.speaker` (the immutable join key — architecture C3). One entry
    per distinct speaker key; the representative `name`/`confidence` come from
    the highest-confidence segment for that speaker.

    `voiceprint_id` is carried here — not on the segments — precisely because it
    can't survive the upload re-parse and must not live on the immutable raw
    segment. The value shape is frozen to exactly three keys: engine-private
    fields (`local_speaker`, `decision`) never cross the repo boundary. Total
    over empty/partial input so it can never crash the ingest path.
    """
    index = _label_index(identity_segments)
    best: dict[str, dict] = {}
    for d in identity_segments:
        key = _speaker_key(d)
        conf = d.get("confidence")
        conf_sort = float(conf) if conf is not None else -1.0
        if key not in best or conf_sort > best[key]["_conf"]:
            best[key] = {
                "label": d.get("name") or f"Speaker {index[key]}",
                "voiceprint_id": d.get("voiceprint_id"),
                "name": d.get("name"),
                "confidence": conf,
                "_conf": conf_sort,
            }
    return {
        v["label"]: {"voiceprint_id": v["voiceprint_id"], "name": v["name"],
                     "confidence": v["confidence"]}
        for v in best.values()
    }


def _representative_clip(session, label: str, session_id: str) -> dict | None:
    """A representative segment for `label` → the "is this you?" clip locator (Task #3).

    The longest segment attributed to the label (a stable sample of that speaker; a
    per-segment confidence isn't stored, so longest is the representative — spec §5). For
    capture meetings `session_id == native_meeting_id` (the audio-dir key), so both keys
    resolve the same recording. Returns None if the label has no timed segment to clip.
    """
    segs = [s for s in (session.raw_diarization or [])
            if s.speaker == label and s.start is not None and s.end is not None
            and s.end > s.start]
    if not segs:
        return None
    best = max(segs, key=lambda s: s.end - s.start)
    return {"conclave_session_id": session_id, "native_meeting_id": session_id,
            "start": float(best.start), "end": float(best.end)}


#: Identity fields carried per C2 segment. Back-filled onto the final view from
#: the streamed lines if the final ("transcript") message omits them.
_C2_IDENTITY_FIELDS = ("voiceprint_id", "name", "confidence", "local_speaker")


def _parse_diarize_ndjson(text: str) -> list[dict]:
    """Parse a /v1/diarize NDJSON body → identity segments carrying voiceprint_id.

    C2 streams per-segment lines `{start, end, voiceprint_id, name, decision,
    confidence, local_speaker}` then a final `{"type":"transcript","segments":
    [...]}` (seal-corrected). The final view is authoritative for boundaries and
    is preferred — but B's persistence needs `voiceprint_id`, and FPM source
    isn't in this repo to guarantee the final segments carry it. So if a final
    segment lacks the `voiceprint_id` key, identity is back-filled from the
    best-overlapping streamed line (which C2 *does* guarantee). Net: correct
    whether or not FPM's final view is identity-bearing, no FPM change needed.
    """
    final, streamed = None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "transcript":
            final = obj.get("segments", [])
        elif "start" in obj:
            streamed.append(obj)
    if final is None:
        return streamed
    if streamed:
        for seg in final:
            if "voiceprint_id" in seg:
                continue  # final already identity-bearing — authoritative, no clobber
            src = _best_overlap(float(seg.get("start") or 0.0),
                                float(seg.get("end") or 0.0), streamed)
            if src:
                for k in _C2_IDENTITY_FIELDS:
                    if k in src:
                        seg[k] = src[k]
    return final


async def _fpm_diarize(client, audio: bytes, filename: str, content_type: str,
                       fpm_workspace: str) -> list[dict]:
    """Call FPM /v1/diarize (offline) → identity segments (final corrected view)."""
    headers = {"Authorization": f"Bearer {settings.fpm_api_token}"} if settings.fpm_api_token else {}
    resp = await client.post(
        f"{settings.fpm_base_url.rstrip('/')}/v1/diarize",
        headers=headers,
        files={"file": (filename, audio, content_type)},
        data={"workspace": fpm_workspace, "tag": "offline"},
    )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM diarize failed ({resp.status_code}): {resp.text[:200]}")
    return _parse_diarize_ndjson(resp.text)


def _ffmpeg_to_wav(audio: bytes) -> bytes:
    """Transcode arbitrary audio (browser webm/opus) → 16 kHz mono WAV via ffmpeg.

    The browser's MediaRecorder produces webm/opus, which NEAR Whisper rejects
    (it expects wav/mp3/m4a like the OpenAI API). FPM decodes webm fine, but ASR
    needs a clean container — so we normalize here before the ASR call.
    """
    import subprocess

    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
        input=audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.decode()[:200] or "ffmpeg produced no output")
    return proc.stdout


async def _transcribe(client, audio: bytes, filename: str, content_type: str) -> list[dict]:
    """Call the NEAR Whisper transcription-service → ASR segments with timestamps."""
    import asyncio

    headers = ({"Authorization": f"Bearer {settings.transcription_service_token}"}
               if settings.transcription_service_token else {})
    # Accept either a base URL (we append the path) or a full .../audio/transcriptions
    # URL (Recato-style), so pointing straight at NEAR Whisper works either way.
    base = settings.transcription_service_url.rstrip("/")
    url = base if base.endswith("/audio/transcriptions") else f"{base}/v1/audio/transcriptions"
    # Normalize to WAV for the ASR provider; fall back to the raw upload if ffmpeg
    # isn't available (then NEAR may still reject webm — but we don't hard-fail here).
    try:
        send = ("audio.wav", await asyncio.to_thread(_ffmpeg_to_wav, audio), "audio/wav")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffmpeg transcode failed (%s); sending raw upload to ASR", exc)
        send = (filename, audio, content_type)
    resp = await client.post(
        url,
        headers=headers,
        files={"file": send},
        data={"model": settings.transcription_model, "response_format": "verbose_json"},
    )
    if resp.status_code != 200:
        raise HTTPException(502, f"transcription failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("segments", [])


@router.post("/{workspace_id}/record", status_code=status.HTTP_202_ACCEPTED)
async def record_meeting(
    workspace_id: str,
    file: UploadFile = File(...),
    intent: Optional[str] = Form(default=None),
    user: dict = Depends(require_current_user),
):
    """Ingest an in-person recording → identified, transcribed Conclave meeting.

    202 {session_id, is_processing: true} — same envelope as upload; enrichment +
    KB indexing run in the background. Re-ingesting identical audio is a 200 no-op.
    """
    _require_member(workspace_id, user["id"])
    if not settings.record_meeting_enabled():
        raise HTTPException(503, "in-person recording is not configured on this server")

    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty recording")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "recording exceeds the 25MB limit")
    filename = file.filename or "recording.webm"
    content_type = file.content_type or "audio/webm"

    import asyncio

    import httpx

    fpm_ws = settings.fpm_workspace_for(workspace_id)
    async with httpx.AsyncClient(timeout=180.0) as client:
        identity, asr = await asyncio.gather(
            _fpm_diarize(client, audio, filename, content_type, fpm_ws),
            _transcribe(client, audio, filename, content_type),
        )

    merged = merge_by_timestamp(asr, identity)
    if not merged:
        raise HTTPException(422, "no speech transcribed from the recording")

    # Hand the merged segments to the EXACT upload ingest path (no new pipeline).
    from api.upload_routes import (
        UploadTranscriptBody,
        _parse_upload,
        _scoped_session_id,
    )

    text = json.dumps(merged)
    body = UploadTranscriptBody(text=text, filename=filename, intent=intent)
    ni = _parse_upload(body)
    session_id = _scoped_session_id(workspace_id, ni, text)

    from transcripts import store

    if store.load_session(session_id) is not None:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"session_id": session_id, "is_processing": False, "status": "duplicate"},
        )

    from transcripts.parse import build_session

    session = build_session(ni, session_id=session_id)
    # Build resolved_speakers from the FPM identity segments (carrying
    # voiceprint_id), NOT the cohort name-matcher: a recorded meeting's labels
    # are FPM emails/`Speaker N`, a different keyspace from the cohort roster.
    # voiceprint_id is the stable key P4/P5 build on (architecture C3).
    session.metadata.resolved_speakers = build_resolved_speakers(identity)
    if intent and intent.strip():
        session.metadata.raw_intent = intent.strip()
    store.save_session(session)
    store.set_workspace(
        session.session_id,
        workspace_id=workspace_id,
        owner_user_id=user["id"],
        visibility="owner-only",
    )

    # Durable via the job queue when on (Task #16), else the same in-process background task.
    from connectors.jobs import enqueue

    enqueue.enrich(session.session_id)

    return {"session_id": session.session_id, "is_processing": True,
            "speakers": sorted({m["speaker"] for m in merged}), "status": "accepted"}


class RecordAgendaBody(BaseModel):
    uid: str
    agenda: str


@router.post("/{workspace_id}/record/agenda", status_code=status.HTTP_204_NO_CONTENT)
async def stash_record_agenda(
    workspace_id: str,
    body: RecordAgendaBody,
    user: dict = Depends(require_current_user),
):
    """Task #12: stash the agenda typed in the record modal, keyed by meeting `uid`.

    The in-person live path streams the mic straight to the capture microservice
    (untouched), so the agenda can't ride the WS. The modal POSTs it here before
    Start; the `meeting.completed` webhook reads it back by `uid` and applies it
    as `session.metadata.raw_intent` before enrichment — giving in-person the same
    agenda grounding online + upload get. 204 even on an empty agenda (no-op stash).
    """
    _require_member(workspace_id, user["id"])
    from infra import inperson_agenda

    inperson_agenda.set_agenda(body.uid, body.agenda, workspace_id=workspace_id)
    return None


class TagSpeakerBody(BaseModel):
    label: str
    name: str
    email: str


@router.post("/{workspace_id}/meetings/{session_id}/tag-speaker")
async def tag_speaker(
    workspace_id: str,
    session_id: str,
    body: TagSpeakerBody,
    user: dict = Depends(require_current_user),
):
    """P4 host tag: bind a meeting's `Speaker N` to a (name, email) via FPM (contract C4).

    Maps the display label → `voiceprint_id` (from the session's `resolved_speakers`),
    proposes the binding to FPM with `proposed_by` = the host's logged-in email, and —
    when FPM auto-confirms (self-tag / dev flag) — re-resolves the name across this
    workspace's transcripts immediately. A pending proposal flips no name (Phase 2: the
    target confirms on the FPM consent dashboard, surfaced on next load).
    """
    _require_member(workspace_id, user["id"])
    from transcripts import store

    session = store.load_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    entry = (session.metadata.resolved_speakers or {}).get(body.label)
    voiceprint_id = entry.get("voiceprint_id") if isinstance(entry, dict) else None
    if not voiceprint_id:
        raise HTTPException(404, f"no voiceprint for label '{body.label}'")

    # Task #3: attach a representative clip the subject can play before consenting — the
    # longest segment attributed to this label (a stable "is this you?" sample). clip_ref
    # is a locator only; the audio stays in Conclave and is served via a signed capability.
    clip_ref = _representative_clip(session, body.label, session_id)
    confidence = entry.get("confidence") if isinstance(entry, dict) else None

    from infra import fpm_consent

    result = await fpm_consent.propose_binding(
        settings.fpm_workspace_for(workspace_id), voiceprint_id,
        proposed_email=body.email, proposed_by=(user.get("email") or ""),
        proposed_name=body.name,
        clip_ref=clip_ref, source="tag", confidence=confidence,
    )
    if result.get("status") == "confirmed":
        store.reresolve_voiceprint(voiceprint_id, result.get("name") or body.name,
                                   workspace_id=workspace_id)
    return {"label": body.label, "voiceprint_id": voiceprint_id,
            "status": result.get("status"), "name": result.get("name"),
            "proposal_id": result.get("proposal_id")}
