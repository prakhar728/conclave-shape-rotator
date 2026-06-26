"""Client for the authoritative DiariZen diarization service (topology A — the GPU post engine).

In the finalizer-A flow, diart gives the live on-screen preview, but the STORED transcript's diarization
comes from DiariZen: at finalize Conclave POSTs the recording here, gets authoritative
`{start, end, local_speaker}` spans, then hands those spans to VFTE `/v1/identify-spans` for names.

The DiariZen service (capture's diarize-gpu container) returns the same heartbeat-NDJSON shape the FPM
remote engine speaks: blank `\\n` keepalives while it runs, then one final
`{"segments":[{"start","end","local_speaker"}], ...}` line. We stream, ignore blanks, parse the last
non-blank line. Identity is NOT requested here — this box only diarizes (stateless, holds no voiceprints).
"""
from __future__ import annotations

import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

DIARIZE_TIMEOUT = httpx.Timeout(600.0)   # DiariZen is minutes-long on a real recording


async def diarize_recording(audio: bytes, *, filename: str = "meeting.wav",
                            workspace: str = "") -> list[dict]:
    """POST the recording to the DiariZen service → authoritative `[{start,end,local_speaker}]` spans.

    Returns [] if `diarize_url` is unconfigured or the service yields nothing (caller falls back).
    """
    url = settings.diarize_url.rstrip("/")
    if not url:
        return []
    headers = {"Authorization": f"Bearer {settings.diarize_token}"} if settings.diarize_token else {}
    segments: list[dict] = []
    async with httpx.AsyncClient(timeout=DIARIZE_TIMEOUT) as client:
        async with client.stream(
            "POST", f"{url}/diarize", headers=headers,
            files={"file": (filename, audio, "audio/wav")},
            data={"workspace": workspace},
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                logger.warning("DiariZen diarize failed (%s): %s", resp.status_code, body[:200])
                return []
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue  # heartbeat keepalive
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("segments") is not None:
                    segments = obj["segments"]
    return segments
