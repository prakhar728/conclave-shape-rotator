"""Transcripts CLI — subcommand dispatcher.

    python -m transcripts.cli ingest <path> [--force] [--dry-run] [--tags ...]
    python -m transcripts.cli llm status|use|smoke   # flip / inspect the LLM backend
    python -m transcripts.cli run <file>             # legacy: parse + enrich + store one file

`ingest` is the C4 path: scan a file/directory, read with `sources.read_file`,
build sessions, save raw to the store. **No LLM ever constructed in this path**
— enrichment lives behind `enrich_pending` (C8). `link`/`enrich`/`eval`/`serve`
land in later steps.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from transcripts import store
from transcripts.enrich import enrich_pending, enrich_session
from transcripts.identity import MOCK_DIRECTORY, link_identities
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


# ---------------------------------------------------------------------------
# `llm` subcommand — flip / inspect the backend switch
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_BACKEND_RE = re.compile(r"^CONCLAVE_LLM_BACKEND\s*=", re.MULTILINE)


def _read_env() -> str:
    return _ENV_PATH.read_text(encoding="utf-8") if _ENV_PATH.exists() else ""


def _write_backend(value: str) -> None:
    """Persist `CONCLAVE_LLM_BACKEND=<value>` to .env (idempotent)."""
    text = _read_env()
    if _BACKEND_RE.search(text):
        text = _BACKEND_RE.sub(f"CONCLAVE_LLM_BACKEND=", text)  # normalize prefix
        text = re.sub(
            r"^CONCLAVE_LLM_BACKEND=.*$",
            f"CONCLAVE_LLM_BACKEND={value}",
            text,
            flags=re.MULTILINE,
        )
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\n# LLM backend switch (nearai = production TEE; ollama = local dev)\nCONCLAVE_LLM_BACKEND={value}\n"
    _ENV_PATH.write_text(text, encoding="utf-8")


def _ollama_reachable(base_url: str) -> tuple[bool, list[str]]:
    """Probe the Ollama daemon. Returns (reachable, installed_model_tags)."""
    # base_url ends with /v1 (OpenAI-compat); the tags endpoint is on the root.
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    try:
        with urllib.request.urlopen(f"{root}/api/tags", timeout=2) as r:
            payload = json.loads(r.read().decode("utf-8"))
        return True, [m.get("name", "") for m in payload.get("models", [])]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError):
        return False, []


def _cmd_llm_status(args: argparse.Namespace) -> int:
    # Re-read settings here so the output reflects the live .env, not a snapshot.
    from importlib import reload
    import config as _config
    reload(_config)
    s = _config.settings

    print(f"backend:        {s.llm_backend}")
    if s.llm_backend == "ollama":
        print(f"ollama_model:   {s.ollama_model}")
        print(f"ollama_url:     {s.ollama_base_url}")
        reachable, tags = _ollama_reachable(s.ollama_base_url)
        print(f"ollama daemon:  {'✓ reachable' if reachable else '✗ unreachable'}")
        if reachable:
            # Ollama lists tags as `name:tag` (`:latest` when unspecified);
            # accept either form so `qwen2.5-conclave` matches `qwen2.5-conclave:latest`.
            wanted = s.ollama_model if ":" in s.ollama_model else f"{s.ollama_model}:latest"
            present = wanted in tags or s.ollama_model in tags
            print(f"model present:  {'✓' if present else '✗ — run: ollama pull qwen2.5:7b-instruct && ollama create '+s.ollama_model+' -f ollama/Modelfile.qwen-conclave'}")
            if tags:
                print(f"installed tags: {', '.join(tags)}")
    else:
        print(f"nearai_model:   {s.default_model}")
        print(f"nearai_url:     {s.nearai_base_url}")
        print(f"api key:        {'set' if s.nearai_api_key else 'MISSING — set CONCLAVE_NEARAI_API_KEY'}")
    return 0


def _cmd_llm_use(args: argparse.Namespace) -> int:
    target = args.backend.lower()
    if target not in {"ollama", "nearai"}:
        print(f"error: backend must be 'ollama' or 'nearai' (got {args.backend!r})", file=sys.stderr)
        return 2
    _write_backend(target)
    print(f"wrote CONCLAVE_LLM_BACKEND={target} to {_ENV_PATH}")
    print("(new shells / processes will pick this up; current process keeps its old setting)")
    return _cmd_llm_status(args)


def _cmd_llm_smoke(args: argparse.Namespace) -> int:
    """One round-trip through `config.get_llm` — proves the wiring end-to-end."""
    from importlib import reload
    import config as _config
    reload(_config)
    llm = _config.get_llm()
    print(f"invoking {_config.settings.llm_backend} backend…")
    try:
        resp = llm.invoke([{"role": "user", "content": "Reply with the single word: pong"}])
        content = getattr(resp, "content", str(resp)).strip()
        print(f"response: {content[:200]}")
        return 0
    except Exception as exc:  # noqa: BLE001 — smoke test surfaces all failures
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _cmd_enrich(args: argparse.Namespace) -> int:
    """Run map-reduce enrichment over pending (or stale) stored sessions."""
    report = enrich_pending(
        only_stale=not args.all,
        session_id=args.session,
        model=args.model,
    )
    print(
        f"enrich: enriched={report.enriched} "
        f"skipped_unavailable={report.skipped_unavailable} "
        f"skipped_output_error={report.skipped_output_error}"
    )
    for sid, err in report.failed:
        print(f"  ! {sid}: {err}", file=sys.stderr)
    return 0 if not report.failed else 1


def _cmd_link(args: argparse.Namespace) -> int:
    """Re-run mock identity linkage over stored sessions (no LLM)."""
    changed = link_identities(session_id=args.session)
    print(f"link: directory_size={len(MOCK_DIRECTORY)} sessions_updated={changed}")
    return 0


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

    pe = sub.add_parser("enrich", help="map-reduce enrichment over pending sessions (uses the LLM)")
    pe.add_argument("--all", action="store_true", help="enrich every session, not just pending/stale")
    pe.add_argument("--session", help="limit to a single session_id")
    pe.add_argument("--model", help="LLM model id override (default: backend default)")
    pe.set_defaults(func=_cmd_enrich)

    pln = sub.add_parser("link", help="re-run mock identity linkage over stored sessions")
    pln.add_argument("--session", help="limit to a single session_id")
    pln.set_defaults(func=_cmd_link)

    pl = sub.add_parser("llm", help="inspect or flip the LLM backend (nearai ⇄ ollama)")
    psub = pl.add_subparsers(dest="llm_cmd")
    pls = psub.add_parser("status", help="show current backend + reachability")
    pls.set_defaults(func=_cmd_llm_status)
    plu = psub.add_parser("use", help="persist a backend to .env (ollama|nearai)")
    plu.add_argument("backend", help="ollama or nearai")
    plu.set_defaults(func=_cmd_llm_use)
    plk = psub.add_parser("smoke", help="one round-trip through get_llm to prove wiring")
    plk.set_defaults(func=_cmd_llm_smoke)
    pl.set_defaults(func=lambda a: (pl.print_help() or 2))

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
