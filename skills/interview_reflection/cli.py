"""
CLI runner for interview_reflection.

Two modes:

    # Single fixture → collaboration profile + rubric panel + composed summary
    python -m skills.interview_reflection.cli prod_internal

    # Cohort matching demo (THE artifact for Novel): ingest many transcripts,
    # then print ranked cross-person intros + each person's panel
    python -m skills.interview_reflection.cli --match tests/fixtures/interview_reflection/*.txt

Both modes ingest into a fresh temporary ledger so runs are reproducible and the
shared data/ ledger is left untouched. With CONCLAVE_NEARAI_API_KEY set the real
LLM + real embeddings are used; otherwise the offline fallbacks apply.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import yaml

from skills.interview_reflection import run_skill
from skills.interview_reflection.aggregate import (
    list_all_slugs,
    load_latest_record,
)
from skills.interview_reflection.models import TranscriptInput
from skills.interview_reflection.rubrics import RUBRIC_REGISTRY
from skills.interview_reflection.skill import run_matching


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "interview_reflection"
BAR = "─" * 78


def _print_block(title: str, body: str) -> None:
    print(f"\n{BAR}\n{title}\n{BAR}\n{body}")


def _print_backend() -> None:
    from config import settings
    from skills.interview_reflection.config import PROFILE_MODEL, RUBRIC_MODEL, COMPOSE_MODEL
    if settings.llm_backend == "ollama":
        print(f"[cli] backend: ollama @ {settings.ollama_base_url} (model: {settings.ollama_model})")
    else:
        print(f"[cli] backend: nearai @ {settings.nearai_base_url}")
        print(f"[cli]   profile/rubric/compose models: {PROFILE_MODEL} / {RUBRIC_MODEL} / {COMPOSE_MODEL}")
    print(f"[cli]   embedding model: {settings.embedding_model}")


def _slug_for(path: Path) -> str:
    expected = path.with_suffix("").with_suffix(".expected.yaml")
    if expected.exists():
        meta = yaml.safe_load(expected.read_text()) or {}
        if meta.get("interviewee_slug"):
            return meta["interviewee_slug"]
    return path.stem


def _ingest(paths: list[Path], ledger_root: Path) -> None:
    for path in paths:
        slug = _slug_for(path)
        print(f"[cli]   ingesting {path.name} → slug={slug} ...", flush=True)
        run_skill(
            [TranscriptInput(transcript=path.read_text(), interviewee_slug=slug)],
            ledger_root=ledger_root,
        )


def _fmt_items(items: list[dict]) -> str:
    if not items:
        return "    (none)"
    lines = []
    for it in items:
        tags = f" [{', '.join(it['tags'])}]" if it.get("tags") else ""
        cred = f" ({it['credibility']})" if it.get("credibility") else ""
        lines.append(f"    • {it['text']}{tags}{cred}")
        if it.get("quote"):
            lines.append(f"        “{it['quote']}”")
    return "\n".join(lines)


def _print_panel(slug: str, record: dict) -> None:
    profile = record.get("collaboration_profile") or {}
    panel = record.get("rubric_panel") or {}
    header = f"{slug.upper()} — {profile.get('building') or '(building unknown)'} · stage={profile.get('stage') or '?'}"
    print(f"\n{BAR}\n{header}\n{BAR}")
    print("  OFFERS\n" + _fmt_items(profile.get("offers")))
    print("  NEEDS\n" + _fmt_items(profile.get("needs")))
    print("  INTERESTS\n" + _fmt_items(profile.get("interests")))
    print("  RUBRICS")
    for key, spec in RUBRIC_REGISTRY.items():
        rs = panel.get(key) or {}
        if rs.get("reported"):
            print(f"    {spec['name']}: {rs['score']}/5 [{rs.get('band')}]")
        else:
            print(f"    {spec['name']}: insufficient evidence")
    if record.get("summary"):
        print(f"  SUMMARY\n    {record['summary']}")
    for b in record.get("bullets") or []:
        print(f"    {b}")


def _print_intros(result: dict) -> None:
    intros = result["intros"]
    _print_block(f"RANKED INTROS ({len(intros)})", "")
    if not intros:
        print("  (no intros — profiles too thin; see S10 enrichment)")
        return
    for i in intros:
        tags = f"  tags={i['tags']}" if i.get("tags") else ""
        print(f"\n  {i['from']} → {i['to']}  [{i['type']}]  score={i['score']}{tags}")
        print(f"    {i['reason']}")
        if i.get("quote_from"):
            print(f"    {i['from']}: “{i['quote_from']}”")
        if i.get("quote_to"):
            print(f"    {i['to']}: “{i['quote_to']}”")


def _run_match(targets: list[str], as_json: bool) -> int:
    paths = [Path(t) for t in targets]
    missing = [p for p in paths if not p.exists()]
    if missing:
        sys.exit(f"error: missing transcript file(s): {', '.join(str(m) for m in missing)}")
    if not paths:
        sys.exit("error: --match needs one or more transcript .txt paths")

    _print_backend()
    ledger_root = Path(tempfile.mkdtemp(prefix="ir_match_"))
    print(f"[cli] match mode: {len(paths)} transcript(s) → ledger {ledger_root}")

    started = time.monotonic()
    _ingest(paths, ledger_root)
    result = run_matching(root=ledger_root)
    print(f"[cli] done in {time.monotonic() - started:.1f}s")

    if as_json:
        records = {s: load_latest_record(s, root=ledger_root) for s in list_all_slugs(ledger_root)}
        print(json.dumps({"matching": result, "panels": records}, indent=2))
        return 0

    _print_intros(result)
    print(f"\n{BAR}\nPER-PERSON PANELS\n{BAR}")
    for slug in list_all_slugs(ledger_root):
        record = load_latest_record(slug, root=ledger_root)
        if record:
            _print_panel(slug, record)
    return 0


def _run_single(slug: str, as_json: bool) -> int:
    path = FIXTURE_DIR / f"{slug}.txt"
    if not path.exists():
        sys.exit(f"error: no fixture {slug!r} (looked at {path})")
    _print_backend()
    ledger_root = Path(tempfile.mkdtemp(prefix="ir_single_"))
    interviewee = _slug_for(path)

    started = time.monotonic()
    response = run_skill(
        [TranscriptInput(transcript=path.read_text(), interviewee_slug=interviewee)],
        ledger_root=ledger_root,
    )
    print(f"[cli] done in {time.monotonic() - started:.1f}s")
    result = response.results[0]

    if as_json:
        print(json.dumps(result, indent=2))
        return 0
    _print_panel(interviewee, result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="interview_reflection CLI")
    parser.add_argument("targets", nargs="*",
                        help="fixture slug (default mode) or .txt paths (with --match)")
    parser.add_argument("--match", action="store_true",
                        help="cohort matching demo: ingest the given transcripts, print intros + panels")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    args = parser.parse_args()

    if args.match:
        return _run_match(args.targets, args.json)
    if not args.targets:
        parser.error("provide a fixture slug, or use --match with transcript paths")
    return _run_single(args.targets[0], args.json)


if __name__ == "__main__":
    raise SystemExit(main())
