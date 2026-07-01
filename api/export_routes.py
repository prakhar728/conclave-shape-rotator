"""Data-dump export surface (Task #18) — "download my data".

Owner-scoped export of a user's OWN meetings (transcripts, summaries + derived
signals, meeting shares, KB knowledge, voiceprint refs, and — opt-in — audio).

Two paths, chosen by the audio toggle (TASK-18 §0 decision 4):

- **Audio OFF (default) → synchronous.** ``GET /api/users/me/export`` builds the
  ZIP on the request and streams it. Fast: no audio decrypt/assembly.
- **Audio ON → asynchronous.** ``POST /api/users/me/export/jobs`` registers an
  export and enqueues a ``data_export`` job (Task #16 queue) that decrypts +
  bundles the audio off the request path. The client then polls
  ``GET .../export/jobs/{id}`` and downloads from ``.../download`` when done.

All routes require the current user; the async status/download routes also
verify the export belongs to the caller (the async-side scope check).
"""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.session import require_current_user
from connectors.jobs import enqueue
from infra import data_export

router = APIRouter(prefix="/api/users/me", tags=["export"])


def _zip_response(data: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
def download_my_data(user: dict = Depends(require_current_user)) -> StreamingResponse:
    """Synchronous ZIP of the user's owned data (no audio). Streams the file."""
    data = data_export.build_zip_bytes(user, include_audio=False)
    return _zip_response(data, data_export.export_filename(user))


class StartExportBody(BaseModel):
    # Audio ON routes through the async queue (large, decrypt-heavy). Default
    # OFF here too, but the sync GET above is the usual no-audio path.
    include_audio: bool = False


class ExportJobResponse(BaseModel):
    export_id: str
    status: str
    include_audio: bool
    error: str | None = None


def _owned_export_or_404(export_id: str, user: dict) -> dict:
    """Load an export record, enforcing that it belongs to `user`.

    404 for an unknown id; 404 (not 403) for someone else's id so we don't leak
    that the id exists — the owner check is the async-side scope isolation.
    """
    status = data_export.get_export(export_id)
    if status is None or status.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="export not found")
    return status


@router.post("/export/jobs", response_model=ExportJobResponse, status_code=202)
def start_export_job(
    body: StartExportBody,
    user: dict = Depends(require_current_user),
) -> ExportJobResponse:
    """Register an async export and enqueue its build (used for audio-on dumps)."""
    export_id = data_export.create_export(user, include_audio=body.include_audio)
    enqueue.data_export(export_id)
    return ExportJobResponse(
        export_id=export_id, status="pending", include_audio=body.include_audio
    )


@router.get("/export/jobs/{export_id}", response_model=ExportJobResponse)
def get_export_job(
    export_id: str,
    user: dict = Depends(require_current_user),
) -> ExportJobResponse:
    """Poll an async export's status (owner-checked)."""
    status = _owned_export_or_404(export_id, user)
    return ExportJobResponse(
        export_id=export_id,
        status=status.get("status", "pending"),
        include_audio=bool(status.get("include_audio")),
        error=status.get("error"),
    )


@router.get("/export/jobs/{export_id}/download")
def download_export_job(
    export_id: str,
    user: dict = Depends(require_current_user),
) -> StreamingResponse:
    """Download a finished async export ZIP (owner-checked)."""
    status = _owned_export_or_404(export_id, user)
    if status.get("status") != "done":
        raise HTTPException(
            status_code=409,
            detail=f"export not ready (status={status.get('status')!r})",
        )
    path = data_export.zip_path(export_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="export artifact missing")
    return _zip_response(path.read_bytes(), data_export.export_filename(user))
