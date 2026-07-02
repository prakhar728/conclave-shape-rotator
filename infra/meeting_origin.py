"""Derive a meeting's *origin* (how it was captured) for the UI badge (Task #38).

`session.metadata.source` alone can't tell in-person from an online bot: both the
in-person diarization path (`api/webhooks_capture.py`) and the Meet/Zoom/Teams bot
(`api/bot_routes.py`) write the same ingest `source` (`CONCLAVE_INGEST_SOURCE`,
default ``"capture"``). The real discriminator is the capture `platform`
(`inperson` / `google_meet` / `zoom` / `teams`), which Task #38 now persists onto
`SessionMetadata.platform`.

This module maps ``(source, platform)`` → a canonical ``origin`` string the
frontend renders as a quiet badge. Legacy sessions predate the persisted
`platform`; for those we fall back to the `bot_invitations` table (an online bot
meeting always has an invitation row; in-person never does).

Canonical origins: ``in_person`` · ``google_meet`` · ``zoom`` · ``teams`` ·
``online`` (other/unknown bot) · ``upload`` · ``demo`` · ``unknown``.
The label + icon live in the frontend (`lib/meetingOrigin.ts`); the server only
emits the canonical string.
"""
from __future__ import annotations

import os
from typing import Optional


def _capture_sources() -> set[str]:
    """Ingest `source` values that mean "a capture path" (in-person OR online bot).

    Read at call time so tests / deployments that set ``CONCLAVE_INGEST_SOURCE``
    are honored. ``"capture"`` is always included as the built-in default.
    """
    return {"capture", os.environ.get("CONCLAVE_INGEST_SOURCE", "capture")}


#: Normalized platform token → canonical origin. Keys are lowercased with
#: separators (``_``/``-``/spaces) stripped so ``in_person``/``inperson`` and
#: ``google_meet``/``googlemeet`` both match.
_PLATFORM_ORIGINS: dict[str, str] = {
    "inperson": "in_person",
    "googlemeet": "google_meet",
    "meet": "google_meet",
    "zoom": "zoom",
    "teams": "teams",
    "msteams": "teams",
}


def _norm_platform(platform: Optional[str]) -> Optional[str]:
    if not platform:
        return None
    key = "".join(c for c in str(platform).lower() if c.isalnum())
    return key or None


def derive_origin(
    source: Optional[str],
    platform: Optional[str],
    bot_platform: Optional[str] = None,
) -> str:
    """Map ``(source, platform)`` → a canonical origin string. Pure.

    ``bot_platform`` is the legacy fallback: the platform recorded on a
    `bot_invitations` row when the session predates the persisted `platform`.
    It is consulted only when `platform` is absent.
    """
    src = (source or "").strip().lower()
    if src == "demo":
        return "demo"

    key = _norm_platform(platform) or _norm_platform(bot_platform)
    if key is not None:
        if key in _PLATFORM_ORIGINS:
            return _PLATFORM_ORIGINS[key]
        # A platform we don't have a specific label for → generic online.
        return "online"

    # No platform signal at all. A capture-source session with no platform is a
    # legacy in-person recording (an online one would have carried a platform or
    # a bot_invitation); anything else is a pasted/uploaded transcript.
    if src in _capture_sources():
        return "in_person"
    if src:
        return "upload"
    return "unknown"


def resolve_origin(session) -> str:
    """Origin for a stored `Session`, with the legacy `bot_invitations` fallback.

    New sessions carry `metadata.platform` → this is a pure metadata read (no I/O).
    Only legacy capture sessions (no platform) trigger a single lookup, and the
    lookup is fail-open so a missing/legacy DB never breaks the view.
    """
    m = session.metadata
    bot_platform: Optional[str] = None
    if not m.platform and (m.source or "").strip().lower() in _capture_sources():
        try:
            from infra import bot_invitations

            # session_id == native_meeting_id for capture meetings (in-person and
            # online alike), so this resolves the platform for legacy online bots.
            inv = bot_invitations.find_latest_by_native(session.session_id)
            if inv:
                bot_platform = inv.get("platform")
        except Exception:  # noqa: BLE001 — fallback only; never break the view
            bot_platform = None
    return derive_origin(m.source, m.platform, bot_platform)
