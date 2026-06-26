"""Live transcription view — SSE generator diffs the buffer; page renders + routes mount."""
import asyncio

import pytest

from api import live_routes


def test_live_view_page_renders_with_meeting_id():
    html = live_routes.live_page("meet-xyz")
    assert "meet-xyz" in html
    assert "EventSource" in html and "/api/meetings/meet-xyz/live" in html


def test_routes_registered():
    paths = {r.path for r in live_routes.router.routes}
    assert "/api/meetings/{native_id}/live" in paths
    assert "/api/meetings/{native_id}/live-view" in paths


@pytest.mark.asyncio
async def test_sse_streams_only_new_segments(monkeypatch):
    # the buffer grows append-only; the stream must emit each row once, in order.
    buffers = [
        [{"speaker": "speaker0", "text": "hello", "start": 0.0, "end": 1.0}],
        [{"speaker": "speaker0", "text": "hello", "start": 0.0, "end": 1.0},
         {"speaker": "speaker1", "text": "hi", "start": 1.0, "end": 2.0}],
    ]
    state = {"poll": 0}

    def fake_live(_nid):
        i = min(state["poll"], len(buffers) - 1)
        return buffers[i]

    async def fake_sleep(_s):
        state["poll"] += 1
        if state["poll"] >= 3:
            raise asyncio.CancelledError       # end the stream after a couple polls

    monkeypatch.setattr(live_routes.transcripts_store, "live_segments", fake_live)
    monkeypatch.setattr(live_routes.asyncio, "sleep", fake_sleep)

    resp = await live_routes.live_stream("m1")
    chunks = []
    try:
        async for c in resp.body_iterator:
            chunks.append(c if isinstance(c, str) else c.decode())
    except asyncio.CancelledError:
        pass
    body = "".join(chunks)
    # both speakers streamed, each exactly once (no dupes from the second poll re-sending the first)
    assert body.count('"speaker0"') == 1
    assert body.count('"speaker1"') == 1
    assert "hello" in body and "hi" in body
