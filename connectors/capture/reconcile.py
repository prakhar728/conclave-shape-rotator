"""Post-diarization identity reconcile — the two-branch merge, moved here UNCHANGED (Task #16).

This is the exact logic that lived inline at the tail of `identify.py::identify_meeting`. It is
lifted into a function with NO behavioral change so that BOTH callers share one copy:
  * `identify.py::identify_meeting` — the legacy *blocking* finalize path (rollback flag).
  * `api/diarize_result_routes.py` — the durable *job-queue* result callback.

Given the meeting's session, its `raw_diarization` (diart's ASR text + timestamps), and the
`fpm_segs` VFTE returned for the diarized spans, it merges identity onto the transcript:

  (a) AUTHORITATIVE (DiariZen) — re-attribute each ASR segment to the overlapping DiariZen speaker,
      OVERWRITE `raw_diarization` (the sanctioned write-once exception), key `resolved_speakers`
      by DiariZen labels.
  (b) FALLBACK (diart-only) — overlap-vote identity onto the existing diart labels; do NOT overwrite.

`authoritative` selects the branch (it was `settings.inperson_via_capture and settings.diarize_url`
at the original call site; in the queue path the worker always runs DiariZen → authoritative).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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


def reconcile_identity(session_id: str, session, fpm_segs: list[dict], *, authoritative: bool) -> None:
    """Merge `fpm_segs` identity onto the session's transcript. Verbatim two-branch logic."""
    from transcripts import store

    if not fpm_segs:
        return

    # AUTHORITATIVE path (DiariZen): the live diart transcript was a preview; now re-attribute each ASR
    # text segment to DiariZen's overlapping speaker and OVERWRITE the stored transcript (the one
    # sanctioned write-once exception). resolved_speakers is keyed by DiariZen's labels.
    if authoritative:
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
