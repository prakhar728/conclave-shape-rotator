"""Layer-1 entry point: raw transcript -> structured, enriched, stored session.

    python -m transcripts.cli session.json
    python -m transcripts.cli - < session.json            # read stdin
    python -m transcripts.cli session.json --source voxterm --tags 1on1,mentoring
    python -m transcripts.cli session.json --no-enrich     # parse + store only
    python -m transcripts.cli session.json --dry-run --json # full session JSON, no write

By default it parses, enriches via the configured (NearAI/TEE) LLM, saves to
the SQLite store, and prints a markdown summary + signals to stdout — pipe that
to Slack, Notion, or any router.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from transcripts import store
from transcripts.enrich import enrich_session
from transcripts.models import Session
from transcripts.parse import parse_transcript


def _read_input(path: str) -> object:
    raw = sys.stdin.read() if path == "-" else open(path, "r", encoding="utf-8").read()
    return json.loads(raw)


def render_markdown(session: Session) -> str:
    """Human/router-friendly digest of summary + signals + entities."""
    m = session.metadata
    d = session.derived
    lines = [
        f"### Session `{session.session_id}`",
        f"*{m.date} · source: {m.source} · {len(session.raw_diarization)} segments*",
        "",
    ]
    if d.summary:
        lines += ["**Summary**", d.summary, ""]
    if d.signals:
        lines.append("**Signals**")
        for s in d.signals:
            who = f" ({', '.join(s.speakers)})" if s.speakers else ""
            lines.append(f"- `{s.kind}`{who}: {s.text}")
        lines.append("")
    if d.entities:
        ents = ", ".join(f"{e.name} ({e.type})" for e in d.entities)
        lines += ["**Entities**", ents, ""]
    if d.summary is None and not d.signals:
        lines.append("_(not enriched)_")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="transcripts.cli", description=__doc__)
    p.add_argument("input", help="path to a transcript JSON file, or '-' for stdin")
    p.add_argument("--source", help="override source label (default: inferred)")
    p.add_argument("--session-id", help="override session id (default: record_id or content hash)")
    p.add_argument("--tags", help="comma-separated tags to attach to metadata")
    p.add_argument("--model", help="LLM model id for enrichment (default: backend default)")
    p.add_argument("--no-enrich", action="store_true", help="parse + store only, skip the LLM pass")
    p.add_argument("--dry-run", action="store_true", help="do not write to the store")
    p.add_argument("--json", action="store_true", help="emit the full session JSON instead of markdown")
    args = p.parse_args(argv)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None

    raw = _read_input(args.input)
    session = parse_transcript(
        raw, source=args.source, session_id=args.session_id, tags=tags
    )

    if not session.raw_diarization:
        print(f"error: no usable segments found in {args.input!r}", file=sys.stderr)
        return 2

    if not args.no_enrich:
        session = enrich_session(session, model=args.model)

    if not args.dry_run:
        store.save_session(session)

    if args.json:
        print(session.model_dump_json(indent=2))
    else:
        print(render_markdown(session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
