"""Live transcription view (SSE) — watch diart's live segments arrive during a meeting.

Conclave had no live view: capture publishes → the consumer buffers into `live_segments` → that buffer was
drained only at finalize, so transcripts surfaced only after the meeting. This adds a real-time tail:

  GET /api/meetings/{native_id}/live        text/event-stream of new live_segments as they arrive
  GET /api/meetings/{native_id}/live-view   a minimal page (EventSource) to watch [speaker] text live

It polls the `live_segments` buffer (the capture consumer writes it as segments arrive), so it shows the
**diart live preview** during the meeting — before the authoritative DiariZen pass lands at finalize.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from transcripts import store as transcripts_store

router = APIRouter(prefix="/api/meetings", tags=["live"])

_POLL_SEC = 1.0
_MAX_SEC = 4 * 3600  # safety cap on a stream's lifetime


@router.get("/{native_id}/live")
async def live_stream(native_id: str) -> StreamingResponse:
    """SSE: stream each new `live_segments` row for a meeting as it lands (append-only buffer)."""

    async def gen():
        yield "retry: 2000\n\n"
        sent, waited = 0, 0.0
        while waited < _MAX_SEC:
            segs = await run_in_threadpool(transcripts_store.live_segments, native_id)
            for s in segs[sent:]:
                yield f"data: {json.dumps(s)}\n\n"
            sent = len(segs)
            yield ": keepalive\n\n"          # comment frame keeps proxies from idling the connection
            await asyncio.sleep(_POLL_SEC)
            waited += _POLL_SEC

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{native_id}/live-view", response_class=HTMLResponse)
def live_page(native_id: str) -> str:
    return _PAGE.replace("__MEETING__", native_id)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live transcript — __MEETING__</title>
<style>
 :root{color-scheme:light dark}
 body{font:15px/1.5 ui-monospace,Menlo,monospace;margin:0;padding:24px;max-width:860px}
 h1{font-size:17px;margin:0 0 2px} .sub{opacity:.6;font-size:13px;margin:0 0 16px}
 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#888;margin-right:7px}
 .dot.live{background:#16a34a;animation:p 1.1s infinite}@keyframes p{50%{opacity:.35}}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #8883;vertical-align:top}
 th{opacity:.55} td.spk{font-weight:700;white-space:nowrap}
</style></head><body>
 <h1>Live transcript <span style="opacity:.5">· __MEETING__</span></h1>
 <p class="sub"><span class="dot" id="dot"></span><span id="st">connecting…</span> — diart live preview; DiariZen finalizes at meeting-end.</p>
 <table><thead><tr><th style="width:96px">time</th><th style="width:120px">speaker</th><th>text</th></tr></thead>
 <tbody id="rows"></tbody></table>
<script>
const rows=document.getElementById("rows"), st=document.getElementById("st"), dot=document.getElementById("dot");
const es=new EventSource("/api/meetings/__MEETING__/live");
es.onopen=()=>{st.textContent="live";dot.className="dot live"};
es.onerror=()=>{st.textContent="reconnecting…";dot.className="dot"};
es.onmessage=(e)=>{
  const s=JSON.parse(e.data);
  const tr=document.createElement("tr");
  const t=(s.start??0).toFixed?.(2)+"–"+(s.end??0).toFixed?.(2);
  tr.innerHTML=`<td>${t}</td><td class="spk">${s.speaker??""}</td><td>${s.text??""}</td>`;
  rows.prepend(tr);
};
</script></body></html>"""
