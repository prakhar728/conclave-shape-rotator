"""Phase 3.5.0 C2 schema test — every `.expected.yaml` in
``tests/fixtures/transcripts/`` loads, conforms to the row schemas
documented in ``tests/fixtures/transcripts/CONVENTIONS.md``, and
references a transcript file that actually sits next to it.

This test is the contract that C3's bake-off harness and C13's
extraction regression both depend on. Keep it strict: a yaml that
"mostly works" should still fail here.

Empty lists are permitted (stubs awaiting hand-coding).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

import pytest
import yaml

from transcripts.sources import read_file

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "transcripts"

OBLIGATION_TYPES = {"action", "decision", "commitment", "open_question", "blocker"}
ENTITY_TYPES = {"person", "project", "topic", "company", "tool"}
QUERY_INTENTS = {"factoid", "aggregate", "relational", "temporal"}
STATUS_VALUES = {"open", "resolved", "unclear"}


def _yaml_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.expected.yaml"))


@pytest.fixture(scope="module")
def yamls() -> dict[Path, dict[str, Any]]:
    out: dict[Path, dict[str, Any]] = {}
    for p in _yaml_paths():
        with open(p) as fh:
            out[p] = yaml.safe_load(fh) or {}
    return out


def test_three_fixtures_present() -> None:
    """C1 exit gate, re-checked here: the eval set is exactly the 3
    transcripts pinned in C1."""
    # Path.stem only strips ".yaml" — the slug is the part before ".expected.yaml".
    names = {p.name.removesuffix(".expected.yaml") for p in _yaml_paths()}
    assert names == {
        "project-intros-agents-day3",
        "dstack-intro-salon",
        "elocute",
    }, f"unexpected fixture slug set: {sorted(names)}"


def test_top_level_keys(yamls: dict[Path, dict[str, Any]]) -> None:
    """transcript / shape / notes / entities / obligations / queries
    are all present in every yaml; entities/obligations/queries are lists."""
    required = {"transcript", "shape", "notes", "entities", "obligations", "queries"}
    for path, data in yamls.items():
        missing = required - set(data.keys())
        assert not missing, f"{path.name} missing keys: {missing}"
        assert isinstance(data["transcript"], str) and data["transcript"].strip(), (
            f"{path.name}: transcript must be a non-empty string"
        )
        assert isinstance(data["shape"], str) and data["shape"].strip(), (
            f"{path.name}: shape must be a non-empty string"
        )
        for key in ("entities", "obligations", "queries"):
            assert isinstance(data[key], list), (
                f"{path.name}: {key} must be a list (use [] for empty)"
            )


def test_transcripts_resolvable(yamls: dict[Path, dict[str, Any]]) -> None:
    """Each yaml's `transcript:` names a file that sits next to it in
    the fixtures dir. Without this the bake-off can't even start."""
    for path, data in yamls.items():
        target = FIXTURE_DIR / data["transcript"]
        assert target.exists(), (
            f"{path.name}: transcript {data['transcript']!r} not found at {target}"
        )


def test_entities_row_schema(yamls: dict[Path, dict[str, Any]]) -> None:
    for path, data in yamls.items():
        for i, e in enumerate(data["entities"]):
            ctx = f"{path.name} entities[{i}]"
            assert isinstance(e, dict), f"{ctx}: not a mapping"
            assert e.get("type") in ENTITY_TYPES, (
                f"{ctx}: type {e.get('type')!r} not in {sorted(ENTITY_TYPES)}"
            )
            assert isinstance(e.get("canonical_name"), str) and e["canonical_name"].strip(), (
                f"{ctx}: canonical_name must be a non-empty string"
            )
            assert isinstance(e.get("raw_mentions"), list) and e["raw_mentions"], (
                f"{ctx}: raw_mentions must be a non-empty list"
            )
            assert all(isinstance(s, str) and s for s in e["raw_mentions"]), (
                f"{ctx}: raw_mentions entries must be non-empty strings"
            )
            _check_turn_ids(e.get("turn_ids"), ctx)


def test_obligations_row_schema(yamls: dict[Path, dict[str, Any]]) -> None:
    for path, data in yamls.items():
        for i, o in enumerate(data["obligations"]):
            ctx = f"{path.name} obligations[{i}]"
            assert isinstance(o, dict), f"{ctx}: not a mapping"
            assert o.get("type") in OBLIGATION_TYPES, (
                f"{ctx}: type {o.get('type')!r} not in {sorted(OBLIGATION_TYPES)}"
            )
            for sk in ("description", "source_quote"):
                v = o.get(sk)
                assert isinstance(v, str) and v.strip(), (
                    f"{ctx}: {sk} must be a non-empty string"
                )
            _check_turn_ids(o.get("turn_ids"), ctx, allow_empty=False)
            # owner_raw_text / due_date_raw are nullable strings
            for nk in ("owner_raw_text", "due_date_raw"):
                v = o.get(nk, "<MISSING>")
                assert v == "<MISSING>" or v is None or isinstance(v, str), (
                    f"{ctx}: {nk} must be a string or null"
                )
                # Field must be explicitly present (None is fine, missing is not).
                assert v != "<MISSING>", f"{ctx}: {nk} must be explicitly set (use null)"
            assert o.get("status_inferred") in STATUS_VALUES, (
                f"{ctx}: status_inferred {o.get('status_inferred')!r} "
                f"not in {sorted(STATUS_VALUES)}"
            )


def test_queries_row_schema(yamls: dict[Path, dict[str, Any]]) -> None:
    for path, data in yamls.items():
        for i, q in enumerate(data["queries"]):
            ctx = f"{path.name} queries[{i}]"
            assert isinstance(q, dict), f"{ctx}: not a mapping"
            assert isinstance(q.get("q"), str) and q["q"].strip(), (
                f"{ctx}: q must be a non-empty string"
            )
            assert q.get("intent") in QUERY_INTENTS, (
                f"{ctx}: intent {q.get('intent')!r} not in {sorted(QUERY_INTENTS)}"
            )
            _check_turn_ids(q.get("relevant_turn_ids"), ctx, allow_empty=False)


def test_turn_ids_within_transcript_bounds(
    yamls: dict[Path, dict[str, Any]],
) -> None:
    """Every turn_id referenced in any row must be a valid 0-indexed
    position in the transcript's parsed segment list. Catches the most
    common hand-coding error: referencing a turn that doesn't exist
    because parsing differs from a labeller's mental model."""
    for path, data in yamls.items():
        target = FIXTURE_DIR / data["transcript"]
        ni = read_file(target)
        n = len(ni.segments)
        if n == 0:
            pytest.fail(f"{path.name}: transcript {target.name} parsed to 0 segments")

        for i, e in enumerate(data["entities"]):
            _check_turn_ids_bounded(
                e.get("turn_ids") or [], n, f"{path.name} entities[{i}]"
            )
        for i, o in enumerate(data["obligations"]):
            _check_turn_ids_bounded(
                o.get("turn_ids") or [], n, f"{path.name} obligations[{i}]"
            )
        for i, q in enumerate(data["queries"]):
            _check_turn_ids_bounded(
                q.get("relevant_turn_ids") or [], n,
                f"{path.name} queries[{i}]",
            )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _check_turn_ids(value: Any, ctx: str, *, allow_empty: bool = True) -> None:
    assert isinstance(value, list), f"{ctx}: turn_ids must be a list"
    if not allow_empty:
        assert value, f"{ctx}: turn_ids must be non-empty"
    assert all(isinstance(v, int) and v >= 0 for v in value), (
        f"{ctx}: turn_ids entries must be non-negative ints"
    )


def _check_turn_ids_bounded(ids: Iterable[int], n_segments: int, ctx: str) -> None:
    for tid in ids:
        assert 0 <= tid < n_segments, (
            f"{ctx}: turn_id {tid} out of range "
            f"(transcript has {n_segments} segments)"
        )
