"""Transcripts CLI — subcommand dispatcher.

    python -m transcripts.cli ingest <path> [--force] [--dry-run] [--tags ...]
    python -m transcripts.cli run <file>   # legacy: parse + enrich + store one file

`ingest` is the C4 path: scan a file/directory, read with `sources.read_file`,
build sessions, save raw to the store. **No LLM ever constructed in this path**
— enrichment lives behind `enrich_pending` (C8). `link`/`enrich`/`eval`/`serve`
land in later steps.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from transcripts import store
from transcripts.enrich import enrich_session
from transcripts.ingest import ingest_path
from transcripts.models import Session
from transcripts.parse import parse_transcript


# ---------------------------------------------------------------------------
# Rendering (kept from the legacy quick-run path)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _cmd_ingest(args: argparse.Namespace) -> int:
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    report = ingest_path(args.path, force=args.force, dry_run=args.dry_run, tags=tags)
    print(
        f"ingest: stored={report.stored} replaced={report.replaced} "
        f"skipped={report.skipped} failed={len(report.failed)}"
    )
    for path, err in report.failed:
        print(f"  ! {path}: {err}", file=sys.stderr)
    return 0 if not report.failed else 1


def _cmd_run(args: argparse.Namespace) -> int:
    """Legacy single-file quick run — parse + (optional) enrich + (optional) store."""
    raw_text = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        raw = raw_text  # fall back to Otter-style text via sources.read_obj

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    session = parse_transcript(raw, source=args.source, session_id=args.session_id, tags=tags)

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="transcripts.cli")
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("ingest", help="batch-ingest transcript files (no LLM)")
    pi.add_argument("path", help="file or directory of transcripts")
    pi.add_argument("--force", action="store_true", help="replace existing sessions")
    pi.add_argument("--dry-run", action="store_true", help="parse but do not write to the store")
    pi.add_argument("--tags", help="comma-separated tags attached to every ingested session")
    pi.set_defaults(func=_cmd_ingest)

    pr = sub.add_parser("run", help="legacy: parse + enrich + store one file, print markdown")
    pr.add_argument("input", help="path to a transcript file, or '-' for stdin")
    pr.add_argument("--source", help="override source label (default: inferred)")
    pr.add_argument("--session-id", help="override session id (default: record_id or content hash)")
    pr.add_argument("--tags", help="comma-separated tags to attach to metadata")
    pr.add_argument("--model", help="LLM model id for enrichment (default: backend default)")
    pr.add_argument("--no-enrich", action="store_true", help="parse + store only, skip the LLM pass")
    pr.add_argument("--dry-run", action="store_true", help="do not write to the store")
    pr.add_argument("--json", action="store_true", help="emit the full session JSON instead of markdown")
    pr.set_defaults(func=_cmd_run)

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
