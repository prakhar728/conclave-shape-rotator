"""Contribute a Conclave meeting to Shape Rotator OS.

**Arm 1 (LIVE).** POST the host-approved **v2** transcript to Shape OS's public
anon ``context_submissions`` inbox — an INSERT-only, no-read-back RLS surface.
The committed anon key + project URL are public *by design*: Shape OS is a public
repo that ships the anon key, and RLS is the trust boundary (anon may only insert
a ``pending`` row with ``org_id='srfg'`` and a bounded body). We always send the
**approved v2** transcript (the host-corrected text), never raw ASR — the
contribute button is server-gated on v2 approval (see ``api/shape_contrib_routes``).

**Arm 2 (distilled readout → PR) is intentionally NOT implemented.** Since the
2026-06-28 survey, the upstream repo moved *all* transcript-derived content off the
public repo: ``session-insights.json`` / ``constellation-cues.json`` /
``session-readouts/`` / ``.private/`` and the ``transcript-{evidence,distillations}``
generated dirs are gitignored, and ``build-bundles.js`` hardcodes those bundle
fields empty (read at runtime from a gated Supabase view). A readout PR therefore
produces a zero-line committable diff. Revisit Arm 2 as a service-role
``distill-v2`` integration coordinated with dmarz/Andrew. See TASK-20.

Everything here is pure + dependency-injected (the HTTP ``post`` is a parameter),
so tests never touch the real Supabase. The endpoint is host-triggered only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

# Public Shape OS prod values (the repo ships these; RLS is the boundary). Used as
# config defaults; `config.settings.shapeos_*` can override for a test/stub Supabase.
DEFAULT_SUPABASE_URL = "https://txjntzwksiluvqcpccpc.supabase.co"

# `context_submissions.body` CHECK: char_length between 1 and 200000. We pack the
# transcript into as few rows as possible, splitting on segment boundaries so no
# single insert exceeds the cap (the RLS check would otherwise reject the row).
MAX_BODY_CHARS = 200_000
# A small headroom so a multi-byte boundary never tips a chunk over the DB cap.
_CHUNK_TARGET = MAX_BODY_CHARS - 200


@dataclass
class InboxResult:
    """Outcome of an Arm-1 contribution. ``ok`` is the only thing the UI needs;
    ``status`` classifies failures for logs/telemetry (mirrors the JS helper's
    ``unconfigured|network|forbidden|rejected`` taxonomy, plus ``dry_run``)."""

    ok: bool
    status: str  # ok | dry_run | unconfigured | network | forbidden | rejected
    parts: int = 0
    http_statuses: list[int] = field(default_factory=list)
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "parts": self.parts,
            "http_statuses": self.http_statuses,
            **({"detail": self.detail} if self.detail else {}),
        }


def transcript_body(segments: list[dict]) -> str:
    """Render ``[{speaker, text}]`` (the shape ``store.v2_segments_or_raw`` returns)
    into the plain ``[speaker] text`` transcript the inbox stores. Skips empty turns."""
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = (seg.get("speaker") or "Speaker").strip()
        lines.append(f"[{speaker}] {text}")
    return "\n".join(lines)


def chunk_body(body: str, *, limit: int = _CHUNK_TARGET) -> list[str]:
    """Split a transcript into <=``limit``-char chunks on line boundaries, so each
    becomes one valid ``context_submissions`` insert. A single line longer than the
    limit is hard-split (rare; a degenerate mega-turn). Never returns an empty chunk."""
    if not body:
        return []
    if len(body) <= limit:
        return [body]
    chunks: list[str] = []
    cur = ""
    for line in body.split("\n"):
        # Hard-split a single oversized line.
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not cur else f"{cur}\n{line}"
        if len(candidate) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks


def build_payload(*, body: str, title: Optional[str], metadata: dict) -> dict:
    """The ``context_submissions`` row Conclave is allowed to insert under RLS:
    ``processing_status='pending'`` + ``org_id='srfg'`` are forced by the policy, so
    we set them to match (the server re-asserts them; mismatching them 401s). We never
    set status/id — those are server/RLS-owned."""
    payload = {
        "org_id": "srfg",
        "source_kind": "transcript",
        "body": body,
        "processing_status": "pending",
        "metadata": {"submitted_via": "conclave", "char_count": len(body), **metadata},
    }
    if title:
        payload["title"] = title[:300]  # title_len CHECK: <= 300
    return payload


def _classify(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code in (401, 403):
        return "forbidden"
    if status_code in (400, 409, 422):
        return "rejected"
    return "network"


def _post_one(
    *,
    url: str,
    anon_key: str,
    payload: dict,
    post: Callable[..., httpx.Response],
    timeout: float,
) -> tuple[int, str]:
    """POST one row. Mirrors ``apps/os/src/renderer/context-submit.mjs`` exactly:
    ``prefer: return=minimal`` is REQUIRED (no SELECT grant → return=representation 401s).
    Never raises — a transport error is classified ``network``."""
    endpoint = f"{url.rstrip('/')}/rest/v1/context_submissions"
    headers = {
        "apikey": anon_key,
        "authorization": f"Bearer {anon_key}",
        "content-type": "application/json",
        "prefer": "return=minimal",
    }
    try:
        resp = post(endpoint, headers=headers, content=json.dumps(payload), timeout=timeout)
    except Exception:  # noqa: BLE001 — transport/DNS/timeout all map to "network"
        return 0, "network"
    return resp.status_code, _classify(resp.status_code)


def contribute_raw(
    *,
    segments: list[dict],
    title: Optional[str],
    metadata: dict,
    url: str,
    anon_key: str,
    dry_run: bool = False,
    post: Callable[..., httpx.Response] = httpx.post,
    timeout: float = 20.0,
) -> InboxResult:
    """Arm 1: push the corrected transcript into Shape OS's ``context_submissions``
    inbox, one insert per <=200 000-char chunk. All-or-reported: if any chunk fails,
    ``ok`` is False and ``status`` carries the first failure class.

    ``dry_run`` builds + validates the payload but never hits the network (returns a
    simulated success) — the dev/test safety valve so we don't post at real Shape OS.
    """
    body = transcript_body(segments)
    if not body:
        return InboxResult(ok=False, status="rejected", detail="empty transcript")
    if not url or not anon_key:
        return InboxResult(ok=False, status="unconfigured", detail="no Shape OS URL/anon key")

    chunks = chunk_body(body)
    if dry_run:
        return InboxResult(ok=True, status="dry_run", parts=len(chunks))

    statuses: list[int] = []
    n = len(chunks)
    for i, chunk in enumerate(chunks):
        part_title = title if n == 1 else f"{title or 'In-person session'} (part {i + 1}/{n})"
        meta = {**metadata, **({"part": i + 1, "parts": n} if n > 1 else {})}
        payload = build_payload(body=chunk, title=part_title, metadata=meta)
        code, cls = _post_one(
            url=url, anon_key=anon_key, payload=payload, post=post, timeout=timeout
        )
        statuses.append(code)
        if cls != "ok":
            return InboxResult(ok=False, status=cls, parts=n, http_statuses=statuses)
    return InboxResult(ok=True, status="ok", parts=n, http_statuses=statuses)
