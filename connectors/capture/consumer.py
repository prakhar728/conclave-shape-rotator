"""Redis consumer-group reader: capture segments → Conclave live buffer (P1).

The stateless capture microservice `XADD`s each transcript segment to the
`transcription_segments` Redis stream (collector format: a single `payload`
field holding JSON — see capture `segment-publisher.ts`). Conclave reads that
stream as a **consumer group**, so a reconnect after a capture/Conclave restart
resumes from the last *unacked* message (replay/reconnect — decision 6), and
buffers each segment via `store.append_segment` (the `live_segments` table).

Lifecycle mirrors `scheduler` — `start()` on app startup, `stop()` on shutdown.
If `REDIS_URL` is unset the consumer is a no-op, so non-streaming deployments
(and tests) are unaffected. `redis` is imported lazily for the same reason.

Ordering: `seq = round(start * 1000)` (audio-time ms) — stable across restarts,
no fragile in-memory counter. Dedupe on `segment_id` is enforced by the table's
partial-unique index, so at-least-once delivery is safe.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

STREAM = os.environ.get("CAPTURE_SEGMENT_STREAM", "transcription_segments")
GROUP = os.environ.get("CAPTURE_CONSUMER_GROUP", "conclave-ingest")
CONSUMER = os.environ.get("CONCLAVE_CONSUMER_NAME", "conclave-1")

_task: "asyncio.Task | None" = None
_stop = False


def _ingest_message(fields: dict) -> None:
    """Parse one stream message and buffer it. Tolerant of control/non-segment msgs."""
    from transcripts import store

    raw = fields.get("payload")
    data = json.loads(raw) if raw else fields

    # Key live_segments by the NATIVE meet code (`uid`, e.g. "azw-xwqq-bjk") — that's
    # what the finalize webhook + post-stop ingest look up. The bot also sends a synth
    # `meeting_id` int; do NOT key on that or finalize finds nothing.
    meeting_key = data.get("uid") or data.get("native_meeting_id") or data.get("meeting_id")
    if not meeting_key:
        return

    # The bot publishes {"type":"transcription","segments":[{text,speaker,start,end,...}]}.
    # Accept that, plus flat single-segment shapes. Control frames (session_start/end)
    # have no segments and no text → skipped.
    msg_type = data.get("type")
    if msg_type and msg_type not in ("segment", "transcript", "transcription"):
        return
    segments = data.get("segments")
    if not isinstance(segments, list):
        segments = [data] if data.get("text") is not None else []

    for seg in segments:
        text = seg.get("text")
        if text is None:
            continue
        try:
            seq = int(round(float(seg.get("start") or 0) * 1000))
        except (TypeError, ValueError):
            seq = 0
        segment = {
            "speaker": seg.get("speaker"),
            "text": text,
            "start": seg.get("start"),
            "end": seg.get("end"),
            "language": seg.get("language"),
        }
        store.append_segment(
            meeting_key, seq, segment, segment_id=seg.get("segment_id")
        )


async def _consume() -> None:
    url = os.environ.get("REDIS_URL")
    if not url:
        logger.info("capture consumer: REDIS_URL unset — streaming ingest disabled")
        return
    import redis.asyncio as redis  # lazy: only needed when streaming is configured

    client = redis.from_url(url, decode_responses=True)
    try:
        await client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:  # type: ignore[attr-defined]
        if "BUSYGROUP" not in str(e):  # group already exists → fine
            logger.warning("capture consumer: xgroup_create failed: %s", e)
    logger.info("capture consumer: reading %s as %s/%s", STREAM, GROUP, CONSUMER)

    while not _stop:
        try:
            resp = await client.xreadgroup(
                GROUP, CONSUMER, {STREAM: ">"}, count=64, block=2000
            )
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001 — keep the loop alive across blips
            logger.warning("capture consumer: read error (%s) — retrying", e)
            await asyncio.sleep(1)
            continue
        if not resp:
            continue
        for _stream_key, messages in resp:
            for msg_id, fields in messages:
                try:
                    await asyncio.to_thread(_ingest_message, fields)
                except Exception as e:  # noqa: BLE001 — bad msg must not wedge the stream
                    logger.warning("capture consumer: bad message %s: %s", msg_id, e)
                finally:
                    # ACK even on parse failure so one poison message can't block the group.
                    await client.xack(STREAM, GROUP, msg_id)
    try:
        await client.aclose()
    except Exception:  # noqa: BLE001
        pass


def start() -> None:
    """Launch the consumer as a background task (no-op if already running)."""
    global _task, _stop
    if _task is not None and not _task.done():
        return
    _stop = False
    _task = asyncio.create_task(_consume())


async def stop() -> None:
    """Signal the loop to drain and stop; cancel if it doesn't exit promptly."""
    global _stop
    _stop = True
    if _task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(_task), timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        except Exception:  # noqa: BLE001
            pass
