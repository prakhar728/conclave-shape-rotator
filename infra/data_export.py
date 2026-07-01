"""Assemble a user's "download my data" ZIP (Task #18).

Owner-scoped export of everything Conclave holds for a user's OWN meetings:
per-meeting JSON (derived insights + metadata + shares + KB knowledge +
voiceprint refs), the raw transcript as ``.txt``, an optional decrypted
``audio.wav`` (Task #30), and a top-level ``manifest.json``.

Scope is the load-bearing invariant: the ONLY meetings in the ZIP are those
where ``owner_user_id == user.id`` (``store.list_owned_sessions``), so a user's
export can never leak another user's data. Voiceprints are refs only — the
actual signed vectors come from FPM's ``GET /v1/me/voiceprints/export`` (Task
#4); we never duplicate them here. Embeddings/chunks are excluded (large,
derived, re-buildable).

Two modes:
- **Sync** (default, no audio): :func:`build_zip_bytes` runs on the request.
- **Async** (audio on): the request creates an export record
  (:func:`create_export`) and enqueues a ``data_export`` job (Task #16 queue);
  the worker runs :func:`run_export_job`, which decrypts + bundles the audio
  off the request path and writes the ZIP to the export store for later
  download. Filesystem-backed state (``status.json`` + ``export.zip``) keeps the
  cross-request handoff migration-free.
"""
from __future__ import annotations

import io
import json
import logging
import os
import secrets
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: Export bundle schema version — bump when the ZIP layout / manifest changes.
SCHEMA_VERSION = "export-v0"

#: Where async export artifacts live (status + built ZIP), one dir per export.
_DEFAULT_EXPORT_DIR = "data/exports"

#: FPM endpoint that returns the real signed voiceprint vectors (Task #4). The
#: manifest points users here instead of duplicating voiceprints in the dump.
VOICEPRINT_EXPORT_ENDPOINT = "/v1/me/voiceprints/export"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    """Filesystem-safe token for a session id used as a ZIP dir / export dir name."""
    return "".join(c for c in str(value) if c.isalnum() or c in "-_") or "unknown"


# ---------------------------------------------------------------------------
# Per-meeting assembly
# ---------------------------------------------------------------------------

def _transcript_text(session) -> str:
    """Raw diarized transcript as ``[speaker] text`` lines (immutable source)."""
    lines = []
    for seg in session.raw_diarization:
        speaker = getattr(seg, "speaker", None) or "Speaker"
        text = getattr(seg, "text", "") or ""
        lines.append(f"[{speaker}] {text}")
    return "\n".join(lines) + ("\n" if lines else "")


def _voiceprint_refs(session) -> list[str]:
    """Unique ``voiceprint_id`` values referenced by this meeting's resolved
    speakers — refs only (the vectors live in FPM; see Task #4)."""
    refs: list[str] = []
    for entry in (session.metadata.resolved_speakers or {}).values():
        if isinstance(entry, dict):
            vid = entry.get("voiceprint_id")
            if vid and vid not in refs:
                refs.append(vid)
    return refs


def _knowledge_for_session(session_id: str) -> dict:
    """KB entities / obligations / facts scoped to one session (no embeddings)."""
    from storage import kb_graph

    entities = kb_graph.entities_for_sessions([session_id])
    obligations = kb_graph.current_obligations(session_ids=[session_id])
    return {
        "entities": entities,
        "obligations": obligations,
        "facts": _facts_for_session(session_id),
    }


def _facts_for_session(session_id: str) -> list[dict]:
    """Defensive read of any ``facts`` rows for a session.

    The facts table exists (Alembic 0007) but the current pipeline doesn't
    populate it. Query defensively so the export captures them if that ever
    changes, without assuming a column layout that isn't there yet.
    """
    from storage.sqlite import _get_conn

    try:
        conn = _get_conn()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(facts)").fetchall()]
        if "session_id" not in cols:
            return []
        rows = conn.execute(
            "SELECT * FROM facts WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001 — facts are best-effort extra, never fail the export
        logger.debug("data_export: facts read failed for %s", session_id, exc_info=True)
        return []


def _meeting_payload(session, *, audio_included: bool) -> dict:
    """The per-meeting ``meeting.json`` body — derived view + provenance."""
    from api.transcripts_routes import to_view
    from infra.workspaces import list_meeting_shares

    view = to_view(session)  # card + signals + entities; never raw_diarization
    return {
        "session_id": session.session_id,
        "view": view,
        "metadata": session.metadata.model_dump(),
        "shares": list_meeting_shares(session.session_id),
        "knowledge": _knowledge_for_session(session.session_id),
        "voiceprint_refs": _voiceprint_refs(session),
        "audio_included": audio_included,
    }


# ---------------------------------------------------------------------------
# ZIP assembly (sync core; the async job reuses this)
# ---------------------------------------------------------------------------

def build_zip_bytes(user: dict, *, include_audio: bool = False) -> bytes:
    """Build the full export ZIP for ``user`` and return its bytes.

    Owner-scoped: only ``owner_user_id == user['id']`` meetings are included.
    When ``include_audio`` is set, each meeting whose ``store_audio`` is on gets
    a decrypted ``audio.wav`` (Task #30). Callers on the request path pass
    ``include_audio=False`` (fast, sync); the async job passes ``True``.
    """
    from transcripts import store

    from infra import identity

    sessions = store.list_owned_sessions(user["id"])
    tnc_status = identity.get_tnc_status(user["id"])

    buf = io.BytesIO()
    manifest_meetings: list[dict] = []
    all_voiceprint_refs: list[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for session in sessions:
            sid = session.session_id
            base = f"meetings/{_safe_id(sid)}"

            audio_included = False
            if include_audio and getattr(session.metadata, "store_audio", None):
                audio = _load_audio(sid)
                if audio:
                    zf.writestr(f"{base}/audio.wav", audio)
                    audio_included = True

            payload = _meeting_payload(session, audio_included=audio_included)
            zf.writestr(
                f"{base}/meeting.json",
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            )
            zf.writestr(f"{base}/transcript.txt", _transcript_text(session))

            for vid in payload["voiceprint_refs"]:
                if vid not in all_voiceprint_refs:
                    all_voiceprint_refs.append(vid)

            manifest_meetings.append({
                "session_id": sid,
                "date": session.metadata.date,
                "source": session.metadata.source,
                "summary": session.derived.summary,
                "meeting_json": f"{base}/meeting.json",
                "transcript_txt": f"{base}/transcript.txt",
                "audio_wav": f"{base}/audio.wav" if audio_included else None,
                "store_audio": getattr(session.metadata, "store_audio", None),
            })

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "user": {
                "id": user["id"],
                "email": user.get("email"),
                "display_name": user.get("display_name"),
            },
            "tnc": {
                "accepted_at": tnc_status["accepted_at"],
                "version": tnc_status["version"],
            },
            "include_audio": include_audio,
            "counts": {"meetings": len(manifest_meetings)},
            "meetings": manifest_meetings,
            "voiceprints": {
                "note": (
                    "This dump lists voiceprint_id references only. Download the "
                    "actual signed voiceprint vectors from FPM (Task #4)."
                ),
                "export_endpoint": VOICEPRINT_EXPORT_ENDPOINT,
                "referenced_ids": all_voiceprint_refs,
            },
            "excluded": ["embeddings", "chunks"],
        }
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        )

    return buf.getvalue()


def _load_audio(session_id: str) -> bytes:
    """Decrypt + assemble a meeting's stored audio (Task #30). Empty on none.

    For capture meetings ``session_id == native_meeting_id`` (the audio-dir
    key), matching how the audio endpoint resolves it.
    """
    try:
        from connectors.capture.identify import _assemble_audio
        return _assemble_audio(session_id)
    except Exception:  # noqa: BLE001 — a broken/absent audio dir never fails the export
        logger.warning("data_export: audio assembly failed for %s", session_id, exc_info=True)
        return b""


def export_filename(user: dict) -> str:
    """Suggested download filename, e.g. ``conclave-export-usr_ab12.zip``."""
    return f"conclave-export-{_safe_id(user.get('id') or 'me')}.zip"


# ---------------------------------------------------------------------------
# Async export store (filesystem-backed; no migration needed)
# ---------------------------------------------------------------------------

def _export_root() -> Path:
    return Path(os.environ.get("CONCLAVE_EXPORT_DIR", _DEFAULT_EXPORT_DIR))


def _export_dir(export_id: str) -> Path:
    return _export_root() / _safe_id(export_id)


def _status_path(export_id: str) -> Path:
    return _export_dir(export_id) / "status.json"


def zip_path(export_id: str) -> Path:
    return _export_dir(export_id) / "export.zip"


def create_export(user: dict, *, include_audio: bool) -> str:
    """Register a new async export for ``user`` (status=pending). Returns its id.

    Records the owning ``user_id`` so the status/download routes can reject a
    different user (the async-side scope check that mirrors the owner filter).
    """
    export_id = f"exp_{secrets.token_hex(6)}"
    d = _export_dir(export_id)
    d.mkdir(parents=True, exist_ok=True)
    status = {
        "export_id": export_id,
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_display_name": user.get("display_name"),
        "include_audio": include_audio,
        "status": "pending",
        "created_at": _now_iso(),
        "error": None,
    }
    _write_status(export_id, status)
    return export_id


def _write_status(export_id: str, status: dict) -> None:
    _status_path(export_id).write_text(json.dumps(status, indent=2, default=str))


def get_export(export_id: str) -> Optional[dict]:
    """Load an export's status record, or None if the id is unknown."""
    p = _status_path(export_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def run_export_job(export_id: str) -> None:
    """Build the ZIP for a registered export and persist it (async worker path).

    Reuses :func:`build_zip_bytes` with the export's recorded ``include_audio``.
    Best-effort: any failure flips the status to ``failed`` with the error so
    the poller can surface it, and never raises out of the worker.
    """
    status = get_export(export_id)
    if status is None:
        logger.warning("data_export: run_export_job for unknown export %s", export_id)
        return
    status["status"] = "processing"
    _write_status(export_id, status)
    try:
        user = {
            "id": status["user_id"],
            "email": status.get("user_email"),
            "display_name": status.get("user_display_name"),
        }
        data = build_zip_bytes(user, include_audio=bool(status.get("include_audio")))
        zip_path(export_id).write_bytes(data)
        status["status"] = "done"
        status["bytes"] = len(data)
        status["completed_at"] = _now_iso()
        _write_status(export_id, status)
    except Exception as e:  # noqa: BLE001 — surface as a failed status, don't crash the worker
        logger.exception("data_export: export %s failed", export_id)
        status["status"] = "failed"
        status["error"] = str(e)
        _write_status(export_id, status)
