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
    """Concatenate a meeting's stored audio chunks. ⚠️ raw concat (assumption #1)."""
    audio_dir = Path(os.environ.get("CONCLAVE_AUDIO_DIR", "data/audio")) / _safe(native_meeting_id)
    if not audio_dir.is_dir():
        return b""
    chunks = sorted((p for p in audio_dir.iterdir() if p.is_file()), key=lambda p: p.name)
    return b"".join(p.read_bytes() for p in chunks)


def _overlapping_identity(start, end, fpm_segs: list[dict]) -> dict | None:
    """The FPM segment with the most time-overlap that carries a voiceprint_id."""
    best, best_overlap = None, 0.0
    s0, e0 = float(start or 0), float(end or 0)
    for fs in fpm_segs:
        if not fs.get("voiceprint_id"):
            continue
        overlap = min(e0, float(fs.get("end") or 0)) - max(s0, float(fs.get("start") or 0))
        if overlap > best_overlap:
            best_overlap, best = overlap, fs
    return best


async def identify_meeting(session_id: str, native_meeting_id: str, workspace_id: str | None) -> None:
    """Run post-meeting identity and merge it onto the transcript's resolved_speakers."""
    if not workspace_id:
        return
    from infra import fpm_consent
    from transcripts import store

    from config import settings

    # VFTE is scoped by the FPM workspace (fpm_workspace_for) — the SAME mapping the tag path uses
    # (record_routes.tag_speaker → propose_binding). Enroll voiceprints under it, not the raw Conclave
    # workspace, or tagging looks in a different VFTE workspace and never finds the voiceprint.
    vfte_ws = settings.fpm_workspace_for(workspace_id)

    audio = _assemble_audio(native_meeting_id)
    if not audio:
        logger.info("identify_meeting: no stored audio for %s — skipping", native_meeting_id)
        return

    session = store.load_session(session_id)
    if session is None:
        return

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
                return
            fpm_segs = await fpm_consent.identify_spans(vfte_ws, audio, spans, tag="offline")
        else:
            # Legacy rollback path: FPM re-diarizes + identifies the recording.
            fpm_segs = await fpm_consent.diarize_audio(vfte_ws, audio, tag="offline")
    except Exception as e:  # noqa: BLE001 — best-effort, never block finalize
        logger.warning("identify_meeting: identity for %s failed: %s", session_id, e)
        return
    if not fpm_segs:
        return

    # AUTHORITATIVE path (DiariZen): the live diart transcript was a preview; now re-attribute each ASR
    # text segment to DiariZen's overlapping speaker and OVERWRITE the stored transcript (the one
    # sanctioned write-once exception). resolved_speakers is keyed by DiariZen's labels.
    if settings.inperson_via_capture and settings.diarize_url:
        from transcripts.models import RawSegment
        new_raw = []
        for seg in session.raw_diarization:                # diart's ASR text + timestamps
            ident = _overlapping_identity(seg.start, seg.end, fpm_segs)
            label = (ident or {}).get("local_speaker") or seg.speaker   # DiariZen label (fallback diart)
            new_raw.append(RawSegment(speaker=label, text=seg.text, start=seg.start, end=seg.end))
        resolved = dict(session.metadata.resolved_speakers or {})
        for fs in fpm_segs:                                # names keyed by DiariZen label
            ls = fs.get("local_speaker")
            if ls and fs.get("voiceprint_id"):
                entry = dict(resolved.get(ls) or {})
                entry["voiceprint_id"] = fs["voiceprint_id"]
                if fs.get("name") and not entry.get("name"):  # don't clobber a manual tag
                    entry["name"] = fs["name"]
                resolved[ls] = entry
        store.set_raw_diarization(session_id, [s.model_dump() for s in new_raw])
        md = session.metadata.model_copy(update={"resolved_speakers": resolved})
        store.set_metadata(session_id, md)
        logger.info("identify_meeting: %s — AUTHORITATIVE DiariZen overwrite (%d segs, %d speakers)",
                    session_id, len(new_raw), len(resolved))
        return

    # FALLBACK (diart-only / legacy): vote identity onto the existing diart labels; do NOT overwrite raw.
    votes: dict[str, dict[str, tuple[int, str | None]]] = {}
    for seg in session.raw_diarization:
        ident = _overlapping_identity(seg.start, seg.end, fpm_segs)
        if not ident:
            continue
        vp = ident["voiceprint_id"]
        per_label = votes.setdefault(seg.speaker, {})
        count, _name = per_label.get(vp, (0, ident.get("name")))
        per_label[vp] = (count + 1, ident.get("name"))
    if not votes:
        return

    resolved = dict(session.metadata.resolved_speakers or {})
    for label, vmap in votes.items():
        vp, (_count, name) = max(vmap.items(), key=lambda kv: kv[1][0])
        entry = dict(resolved.get(label) or {})
        entry["voiceprint_id"] = vp
        if name and not entry.get("name"):  # don't clobber a manual tag
            entry["name"] = name
        resolved[label] = entry
    md = session.metadata.model_copy(update={"resolved_speakers": resolved})
    store.set_metadata(session_id, md)
    logger.info("identify_meeting: %s — identified %d label(s)", session_id, len(votes))
