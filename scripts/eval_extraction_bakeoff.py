#!/usr/bin/env python3
"""Run the Q1 bake-off: one-prompt vs per-type extraction on the 3 fixtures.

Usage:
    python3 scripts/eval_extraction_bakeoff.py [--model MODEL] [--only SLUG]
        [--strategies one_prompt,per_type] [--out PATH]

Writes tests/fixtures/transcripts/bakeoff_results.md and also dumps raw
predictions next to it (bakeoff_predictions_<strategy>_<slug>.json) so a
re-score doesn't need a re-extract.

Phase 3.5.0 C3 — see discoveries/KB-AND-GRAPH-BUILD-PLAN.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from transcripts.sources import read_file  # noqa: E402
from transcripts.extract_bakeoff import (  # noqa: E402
    chunk_turns,
    extract_one_prompt,
    extract_per_type,
    render_chunk,
)
from transcripts.eval_bakeoff import score_transcript, render_report  # noqa: E402

FIXTURE_DIR = REPO / "tests" / "fixtures" / "transcripts"


def extract_one_prompt_v2(segments, *, llm=None, model=None):
    """C13's production prompt (consolidation + entity discipline),
    run through the same chunking as the original bake-off arms so the
    comparison isolates the prompt change."""
    from transcripts.extract import (
        extract_from_chunk, merge_entities, dedupe_obligations,
    )
    entities, obligations = [], []
    for chunk in chunk_turns(segments):
        r = extract_from_chunk(
            render_chunk(chunk), turn_count=len(segments), llm=llm, model=model,
        )
        entities.extend(r.entities)
        obligations.extend(r.obligations)
    return {
        "entities": merge_entities(entities),
        "obligations": dedupe_obligations(obligations),
    }


STRATEGIES = {
    "one_prompt": extract_one_prompt,
    "per_type": extract_per_type,
    "one_prompt_v2": extract_one_prompt_v2,
}


def load_gold() -> dict[str, dict]:
    out = {}
    for p in sorted(FIXTURE_DIR.glob("*.expected.yaml")):
        slug = p.name.removesuffix(".expected.yaml")
        with open(p) as fh:
            out[slug] = yaml.safe_load(fh)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="model override for config.get_llm")
    ap.add_argument("--only", default=None, help="run a single fixture slug")
    ap.add_argument("--strategies", default="one_prompt,per_type")
    ap.add_argument("--out", default=str(FIXTURE_DIR / "bakeoff_results.md"))
    ap.add_argument("--rescore", action="store_true",
                    help="skip extraction; re-score existing prediction dumps")
    args = ap.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    for s in strategies:
        if s not in STRATEGIES:
            ap.error(f"unknown strategy {s!r} (choose from {sorted(STRATEGIES)})")

    gold = load_gold()
    if args.only:
        if args.only not in gold:
            ap.error(f"unknown slug {args.only!r} (have {sorted(gold)})")
        gold = {args.only: gold[args.only]}

    results: dict[str, dict] = {}
    for slug, g in gold.items():
        transcript_path = FIXTURE_DIR / g["transcript"]
        ni = read_file(transcript_path)
        results[slug] = {}
        for strategy in strategies:
            dump = FIXTURE_DIR / f"bakeoff_predictions_{strategy}_{slug}.json"
            if args.rescore and dump.exists():
                pred = json.loads(dump.read_text())
                print(f"[rescore] {slug} / {strategy}: loaded {dump.name}")
            else:
                t0 = time.time()
                print(f"[extract] {slug} / {strategy} ({len(ni.segments)} turns)...",
                      flush=True)
                pred = STRATEGIES[strategy](ni.segments, model=args.model)
                dt = time.time() - t0
                print(f"[extract] {slug} / {strategy}: "
                      f"{len(pred['entities'])} entities, "
                      f"{len(pred['obligations'])} obligations in {dt:.0f}s",
                      flush=True)
                dump.write_text(json.dumps(pred, indent=2))
            results[slug][strategy] = score_transcript(pred, g)

    # Resolve the real backend default rather than guessing at it.
    if args.model:
        model_id = args.model
    else:
        try:
            from config import settings
            backend = settings.llm_backend
            default_model = {
                "redpill": getattr(settings, "redpill_model", "?"),
                "nearai": getattr(settings, "nearai_model", "?"),
                "ollama": getattr(settings, "ollama_model", "?"),
            }.get(backend, "?")
            model_id = f"{backend}:{default_model}"
        except Exception:
            model_id = "config.get_llm() default (backend unresolved)"
    report = render_report(results, model_id=model_id)
    Path(args.out).write_text(report)
    print(f"\nwrote {args.out}\n")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
