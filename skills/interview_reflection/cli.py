"""
End-to-end smoke runner for interview_reflection (Track A v0).

Pipes a fixture transcript through deterministic → agent → guardrails using the
**real** NearAI LLM. Lets you eyeball output quality on synthetic transcripts
before Step 10 (real Novel transcripts).

Usage:

    # Single fixture through the pipeline
    python -m skills.interview_reflection.cli <fixture-slug>
    python -m skills.interview_reflection.cli prod_internal --share

    # Multi-session trajectory through the pipeline + aggregation (Step 7)
    python -m skills.interview_reflection.cli leo \\
        --history prod_external,prod_mixed,prod_internal

Available fixture slugs:
    collab_internal, collab_mixed, edge_derailed, edge_silent,
    prod_external, prod_internal, prod_mixed, prod_shifting,
    research_external, research_shifting

Requires CONCLAVE_NEARAI_API_KEY in env (same key V2 uses).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from pathlib import Path

import yaml

from skills.interview_reflection import run_skill
from skills.interview_reflection.aggregate import run_aggregate
from skills.interview_reflection.models import TranscriptInput


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "interview_reflection"


def _load_fixture(slug: str) -> tuple[str, dict]:
    transcript_path = FIXTURE_DIR / f"{slug}.txt"
    expected_path = FIXTURE_DIR / f"{slug}.expected.yaml"
    if not transcript_path.exists():
        sys.exit(f"error: no fixture {slug!r} (looked at {transcript_path})")
    transcript = transcript_path.read_text()
    expected = yaml.safe_load(expected_path.read_text()) if expected_path.exists() else {}
    return transcript, expected


def _print_block(title: str, body: str) -> None:
    bar = "─" * 78
    print(f"\n{bar}\n{title}\n{bar}\n{body}")


def _print_backend() -> None:
    """Print the active LLM backend and the per-node model IDs in effect."""
    from config import settings
    from skills.interview_reflection.config import OWNERSHIP_MODEL, THEMES_MODEL
    if settings.llm_backend == "ollama":
        print(
            f"[cli] backend: ollama @ {settings.ollama_base_url} "
            f"(model: {settings.ollama_model} — overrides ignored in ollama mode)"
        )
    else:
        print(f"[cli] backend: nearai @ {settings.nearai_base_url}")
        print(f"[cli]   themes_model:    {THEMES_MODEL}")
        print(f"[cli]   ownership_model: {OWNERSHIP_MODEL}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "slug",
        help=(
            "single mode: fixture slug, e.g. prod_internal. "
            "history mode (with --history): interviewee_slug to anchor the sequence under."
        ),
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="set share_with_interviewee=True to exercise IntervieweeOutput path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print raw JSON instead of pretty blocks",
    )
    parser.add_argument(
        "--history",
        help=(
            "comma-separated fixture slugs run as a single interviewee's session "
            "trajectory. Each fixture is pumped through the full pipeline in order, "
            "then aggregate.run_aggregate produces the cross-session summary."
        ),
    )
    args = parser.parse_args()

    if args.history:
        return _run_history(args)
    return _run_single(args)


def _run_single(args) -> int:

    transcript, expected = _load_fixture(args.slug)
    interviewee_slug = expected.get("interviewee_slug", "unknown")

    print(f"[cli] fixture: {args.slug}")
    print(f"[cli] interviewee_slug: {interviewee_slug}")
    print(f"[cli] team_context: {expected.get('team_context', '?')}")
    print(f"[cli] human_attribution_bucket: {expected.get('human_attribution_bucket') or expected.get('attribution_bucket')}")
    print(f"[cli] share_with_interviewee: {args.share}")
    _print_backend()

    started = time.monotonic()
    response = run_skill([
        TranscriptInput(
            transcript=transcript,
            interviewee_slug=interviewee_slug,
            share_with_interviewee=args.share,
        )
    ])
    elapsed = time.monotonic() - started

    print(f"[cli] done in {elapsed:.1f}s")

    result = response.results[0]

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    _print_block("themes", "\n".join(f"  • {t}" for t in result.get("themes", [])))
    _print_block("session_summary", result.get("session_summary", "") or "(empty)")
    _print_block(
        "attribution_patterns",
        json.dumps(result.get("attribution_patterns", {}), indent=2),
    )
    _print_block(
        "suggested_next_questions",
        "\n".join(f"  • {q}" for q in result.get("suggested_next_questions", [])) or "(empty)",
    )

    if "interviewee_output" in result:
        io = result["interviewee_output"]
        _print_block(
            "interviewee_output.themes",
            "\n".join(f"  • {t}" for t in io.get("themes", [])) or "(empty)",
        )
        _print_block(
            "interviewee_output.ownership_prompts",
            "\n".join(f"  • {p}" for p in io.get("ownership_prompts", [])) or "(empty)",
        )
        _print_block(
            "interviewee_output.evidence_quotes",
            "\n".join(f"  • {q}" for q in io.get("evidence_quotes", [])) or "(empty)",
        )

    if "_leakage_warning" in result:
        _print_block("⚠ leakage warning", result["_leakage_warning"])

    return 0


def _run_history(args) -> int:
    """Run a sequence of fixtures as one interviewee's session history and aggregate."""
    from config import settings

    slugs = [s.strip() for s in args.history.split(",") if s.strip()]
    if len(slugs) < 2:
        print(f"error: --history needs at least 2 comma-separated slugs, got {slugs!r}")
        return 1

    print(f"[cli] history mode for interviewee_slug={args.slug!r}")
    print(f"[cli] sessions: {' → '.join(slugs)}")
    _print_backend()

    digests: list[dict] = []
    for idx, slug in enumerate(slugs, 1):
        transcript, _expected = _load_fixture(slug)
        print(f"\n[cli] session {idx}/{len(slugs)}: {slug} — calling LLM...")
        started = time.monotonic()
        response = run_skill([
            TranscriptInput(
                transcript=transcript,
                interviewee_slug=args.slug,
                share_with_interviewee=False,
            )
        ])
        elapsed = time.monotonic() - started
        result = response.results[0]
        # Stamp ingest time in the in-memory digest so aggregate can show a window.
        # append_digest already stamps the persisted copy, but the response is
        # a separate object that doesn't get that side-effect.
        result.setdefault("ingest_timestamp", _dt.datetime.now(_dt.UTC).isoformat())
        print(f"[cli]   {elapsed:.1f}s · themes={result.get('themes')} · attribution={result.get('attribution_patterns')}")
        digests.append(result)

    aggregate = run_aggregate(digests)

    if args.json:
        print(json.dumps(aggregate, indent=2))
        return 0

    _print_block(
        "session_count / window",
        f"{aggregate['session_count']} sessions · "
        f"first={aggregate.get('first_ingest')} · last={aggregate.get('last_ingest')}",
    )
    _print_block(
        "attribution_trajectory",
        f"{aggregate['attribution_trajectory']}\nseries: {aggregate['attribution_series']}",
    )
    _print_block(
        "recurring_themes",
        "\n".join(
            f"  • {r['theme']} (sessions={r['sessions']}, "
            f"first={r['first_seen_index']}, last={r['last_seen_index']})"
            for r in aggregate["recurring_themes"]
        ) or "(none)",
    )
    _print_block("new_themes (latest session only)",
                 "\n".join(f"  • {t}" for t in aggregate["new_themes"]) or "(none)")
    _print_block("dropped_themes (in earlier sessions, not in latest)",
                 "\n".join(f"  • {t}" for t in aggregate["dropped_themes"]) or "(none)")
    _print_block("overall_assessment", aggregate["overall_assessment"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
