"""Recato → Conclave one-shot fetch + translate + POST.

Usage::

    python -m connectors.recato fetch <platform> <native_meeting_id>

The demo path. Lets you pull any past Recato meeting into Conclave without
running the webhook consumer. ``consumer.py`` does the same flow on every
``meeting.completed`` automatically, but for development + ad-hoc re-ingest
this CLI is the fastest loop.

Env vars (see ``connectors/recato/__init__.py`` for the full list):

- ``CONCLAVE_INGEST_URL``    (required)
- ``CONCLAVE_INGEST_SECRET`` (required)
- ``RECATO_API_BASE_URL``    (required, e.g. ``http://localhost:8056``)
- ``RECATO_API_TOKEN``       (required)
- ``CONCLAVE_INGEST_SOURCE`` (optional, defaults to ``"recato"``)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from typing import Optional

import httpx

from .translator import to_canonical


def _env(name: str, *, required: bool = True, default: Optional[str] = None) -> str:
    """Read an env var or die with a clear error message."""
    val = os.environ.get(name, default)
    if required and not val:
        print(f"error: env var {name} is required", file=sys.stderr)
        sys.exit(2)
    return val or ""


def fetch_and_post(platform: str, native_meeting_id: str) -> dict:
    """Fetch one Recato transcript, translate to canonical, POST to Conclave.

    Returns Conclave's response JSON (``{session_id, status}``).
    """
    recato_base = _env("RECATO_API_BASE_URL").rstrip("/")
    recato_token = _env("RECATO_API_TOKEN")
    conclave_url = _env("CONCLAVE_INGEST_URL")
    conclave_secret = _env("CONCLAVE_INGEST_SECRET").encode()
    source = _env("CONCLAVE_INGEST_SOURCE", required=False, default="recato")

    # --- Fetch from Recato -----------------------------------------------
    # Recato's api-gateway accepts BOTH `X-API-Key: <token>` and
    # `Authorization: Bearer <token>` (gateway converts X-API-Key → Authorization
    # before forwarding internally). We send both to be tolerant of either path.
    fetch_url = f"{recato_base}/transcripts/{platform}/{native_meeting_id}"
    headers = {
        "X-API-Key": recato_token,
        "Authorization": f"Bearer {recato_token}",
        "Accept": "application/json",
    }
    print(f"GET {fetch_url} …", file=sys.stderr)
    resp = httpx.get(fetch_url, headers=headers, timeout=30.0)
    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        resp.raise_for_status()
    recato = resp.json()
    seg_count = len(recato.get("segments") or [])
    print(f"  got {seg_count} segments", file=sys.stderr)

    # --- Translate to canonical ------------------------------------------
    canonical = to_canonical(recato, source=source)
    print(f"  translated → canonical (external_id={canonical['meeting']['external_id']})", file=sys.stderr)

    # --- HMAC-sign + POST to Conclave ------------------------------------
    body = json.dumps(canonical, separators=(",", ":")).encode()
    sig = "sha256=" + hmac.new(conclave_secret, body, hashlib.sha256).hexdigest()
    post_headers = {
        "X-Conclave-Signature": sig,
        "Content-Type": "application/json",
    }
    print(f"POST {conclave_url} …", file=sys.stderr)
    resp = httpx.post(conclave_url, content=body, headers=post_headers, timeout=30.0)
    if resp.status_code not in (200, 202):
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        resp.raise_for_status()
    out = resp.json()
    print(f"  HTTP {resp.status_code}: session_id={out.get('session_id')} status={out.get('status')}", file=sys.stderr)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="connectors.recato",
        description="Fetch a Recato transcript and POST to Conclave's canonical ingest.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="One-shot fetch + translate + POST")
    p_fetch.add_argument("platform", help="Meeting platform (gmeet | zoom | teams)")
    p_fetch.add_argument("native_meeting_id", help="Recato's external_id for the meeting")

    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        try:
            out = fetch_and_post(args.platform, args.native_meeting_id)
        except httpx.HTTPStatusError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(out))
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
