"""Post-meeting voice identity for a captured meeting (P4, the POST path).

After finalize, send the meeting's stored audio (capture → Conclave `/audio-chunk`)
to FPM `/v1/diarize` (`tag="offline"`, authoritative) and merge the returned
identified segments onto the transcript's speaker labels by timestamp overlap,
populating `resolved_speakers[label] = {voiceprint_id, name}`. That `voiceprint_id`
is exactly what the `tag-speaker` feedback loop needs to push corrections to FPM.

⚠️ RUNTIME ASSUMPTIONS — design-open; verify against a real meeting (these are the
   spots where runtime behavior should drive the final choice, not a blind guess):
  1. **Audio assembly**: chunks are concatenated as raw bytes. Valid for a single
     WAV stream; webm/opus chunks almost certainly need an ffmpeg remux into one
     container first (same class of issue as the old record_routes webm→wav fix).
  2. **Timestamp alignment**: FPM diarization start/end (audio clock) vs the
     transcript segments' start/end (ASR clock) are assumed to share an origin. If
     they drift, the overlap vote needs an offset.
  3. **LIVE path not wired here** — this is post-meeting only. Live identity would
     call `diarize_audio(tag="live")` on streaming chunks during the meeting.

Best-effort throughout: any failure logs and returns, never blocks finalize/enrich.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _safe(value: str) -> str:
    return "".join(c for c in str(value) if c.isalnum() or c in "-_") or "unknown"


def _assemble_audio(native_meeting_id: str) -> bytes:
    """Concatenate a meeting's stored audio chunks, decrypting each (Task #30).

    Each chunk is encrypted independently (MAGIC || IV || MAC || ct). We decrypt
    chunk-by-chunk before concatenating, with a per-chunk plaintext fallback so legacy
    pre-#30 files (no MAGIC) still assemble — the encrypt-new-meetings-only invariant.
    ⚠️ raw concat of the decrypted bytes (assumption #1). Sidecar `.sha256` hashes (the
    V1 attestation seam) are not chunk audio, so they're skipped.
    """
    from infra import audio_crypto

    audio_dir = Path(os.environ.get("CONCLAVE_AUDIO_DIR", "data/audio")) / _safe(native_meeting_id)
    if not audio_dir.is_dir():
        return b""
    chunks = sorted(
        (p for p in audio_dir.iterdir() if p.is_file() and p.suffix != ".sha256"),
        key=lambda p: p.name,
    )
    return b"".join(audio_crypto.decrypt_if_encrypted(p.read_bytes()) for p in chunks)


async def identify_meeting(session_id: str, native_meeting_id: str,
                           workspace_id: str | None) -> bool:
    """Run post-meeting identity and merge it onto the transcript's resolved_speakers.

    Returns True iff identity was DEFERRED to a durable diarize job (Task #16, queue mode): the
    caller must then NOT run enrichment inline — the result callback chains it after reconcile.
    Returns False when identity ran inline (blocking/legacy) or there was nothing to do.
    """
    if not workspace_id:
        return False
    from infra import fpm_consent
    from transcripts import store

    from config import settings

    # VFTE is scoped by the FPM workspace (fpm_workspace_for) — the SAME mapping the tag path uses
    # (record_routes.tag_speaker → propose_binding). Enroll voiceprints under it, not the raw Conclave
    # workspace, or tagging looks in a different VFTE workspace and never finds the voiceprint.
    vfte_ws = settings.fpm_workspace_for(workspace_id)

    # Task #16: queue mode — instead of the blocking diarize_recording call below, SUBMIT a durable
    # diarize job and return. A DiariZen worker fetches the audio by reference, runs the engine, and
    # POSTs /api/diarize/result, where identify-spans + reconcile run (the exact logic below, shared via
    # connectors.capture.reconcile). Audio-by-reference, so we don't assemble bytes here. Falls through
    # to the blocking path if the submit can't be made (no Redis / unconfigured) — never lose a finalize.
    if settings.inperson_via_capture and settings.diarize_jobs == "queue":
        from connectors.capture.diarize_jobs import submit_diarize_job
        try:
            if submit_diarize_job(session_id=session_id, native_meeting_id=native_meeting_id,
                                  workspace_id=workspace_id):
                return True
        except Exception:  # noqa: BLE001 — never block finalize on a queue hiccup
            logger.exception("identify_meeting: diarize job submit failed for %s — running inline",
                             session_id)

    audio = _assemble_audio(native_meeting_id)
    if not audio:
        logger.info("identify_meeting: no stored audio for %s — skipping", native_meeting_id)
        return False

    session = store.load_session(session_id)
    if session is None:
        return False

    try:
        if settings.inperson_via_capture:
            # Boundary path: capture/DiariZen diarizes → VFTE identifies the spans (no re-diarize in VFTE).
            if settings.diarize_url:
                # Finalizer A: the AUTHORITATIVE diarization comes from the DiariZen GPU post engine
                # (diart was only the live preview). Post the recording → authoritative spans.
                from connectors.capture import diarize_client
                spans = await diarize_client.diarize_recording(audio, workspace=workspace_id)
                src = "DiariZen"
            else:
                # No post engine configured → use capture's own (diart) spans from the live transcript.
                spans = [{"start": seg.start, "end": seg.end, "local_speaker": seg.speaker}
                         for seg in session.raw_diarization
                         if seg.speaker is not None and seg.start is not None]
                src = "diart(raw_diarization)"
            if not spans:
                logger.info("identify_meeting: no %s spans for %s — skipping", src, native_meeting_id)
                return False
            fpm_segs = await fpm_consent.identify_spans(vfte_ws, audio, spans, tag="offline",
                                                        meeting_id=native_meeting_id)
        else:
            # Legacy rollback path: FPM re-diarizes + identifies the recording.
            fpm_segs = await fpm_consent.diarize_audio(vfte_ws, audio, tag="offline")
    except Exception as e:  # noqa: BLE001 — best-effort, never block finalize
        logger.warning("identify_meeting: identity for %s failed: %s", session_id, e)
        return False
    if not fpm_segs:
        return False

    # The two-branch merge (authoritative overwrite vs diart-fallback vote) moved UNCHANGED into
    # connectors.capture.reconcile so the durable job-queue result callback shares the exact logic.
    from connectors.capture.reconcile import reconcile_identity
    authoritative = bool(settings.inperson_via_capture and settings.diarize_url)
    reconcile_identity(session_id, session, fpm_segs, authoritative=authoritative)
    # Task #3 Part (c): consent-to-recognize ≠ consent-to-silence — tell FPM which voiceprints
    # were recognized so it records + emails the consented subjects (best-effort, never blocks).
    try:
        await fpm_consent.notify_recognitions(vfte_ws, fpm_segs, native_meeting_id=native_meeting_id)
    except Exception:  # noqa: BLE001
        logger.warning("identify_meeting: recognition notices failed for %s", session_id,
                       exc_info=True)
    return False
