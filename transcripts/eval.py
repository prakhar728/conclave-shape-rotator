"""Golden-set runner + set-overlap metrics — the regression gate.

`IMPLEMENTATION_PLAN.md` §G10. Deterministic metrics only; no LLM-as-judge
(avoids cost + circularity per §B.11). The summary stays a manual-eyeball
v1 — only signals and entities are scored, since those are the structured
outputs we can score reliably with set overlap.

Inputs: a directory of ``<session_slug>.expected.yaml`` files, each
declaring the expected signals (texts only — kind is ignored for v1) and
entities (names only). The runner ingests + enriches each transcript and
compares its ``Derived`` against the expected set.

Metrics per session:
- ``signal_coverage`` = |extracted ∩ expected| / |expected|  (recall)
- ``entity_precision`` = |extracted ∩ expected| / |extracted|
- ``entity_recall``    = |extracted ∩ expected| / |expected|
- ``entity_f1``        = harmonic mean

Aggregate: simple average across sessions. Save with
``save_baseline``/``diff_baseline`` so a prompt change shows up as
"signal coverage 0.62 → 0.71 (+0.09)" in the report — that's the number
that has to move for a prompt change to be worth shipping.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from transcripts.config import GOLDEN_DIR

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SessionScore:
    session_id: str
    signal_coverage: float
    entity_precision: float
    entity_recall: float
    entity_f1: float
    # Diagnostics so a regression report can point at what changed.
    missing_signals: list[str] = field(default_factory=list)
    spurious_entities: list[str] = field(default_factory=list)
    missing_entities: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    sessions: list[SessionScore] = field(default_factory=list)
    # Aggregates — set after all sessions scored.
    avg_signal_coverage: float = 0.0
    avg_entity_precision: float = 0.0
    avg_entity_recall: float = 0.0
    avg_entity_f1: float = 0.0

    def finalize(self) -> "EvalReport":
        n = len(self.sessions) or 1
        self.avg_signal_coverage = sum(s.signal_coverage for s in self.sessions) / n
        self.avg_entity_precision = sum(s.entity_precision for s in self.sessions) / n
        self.avg_entity_recall = sum(s.entity_recall for s in self.sessions) / n
        self.avg_entity_f1 = sum(s.entity_f1 for s in self.sessions) / n
        return self


# ---------------------------------------------------------------------------
# Metric math (deterministic, no LLM, fully unit-testable)
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace. Identical key as the dedup helper."""
    return " ".join(s.lower().split())


def _score(derived: Any, expected: dict) -> SessionScore:
    """Score one session's ``Derived`` against an ``expected`` dict.

    ``expected`` shape:
        {
          "signals":  ["text", ...],   # signal coverage uses fuzzy text match
          "entities": ["name", ...],   # entity P/R uses normalized name match
        }
    """
    expected_signals = {_normalize(s) for s in (expected.get("signals") or []) if s}
    expected_entities = {_normalize(e) for e in (expected.get("entities") or []) if e}

    extracted_signal_texts = {_normalize(s.text) for s in (derived.signals or []) if s.text}
    extracted_entity_names = {_normalize(e.name) for e in (derived.entities or []) if e.name}

    sig_match = extracted_signal_texts & expected_signals
    signal_coverage = (len(sig_match) / len(expected_signals)) if expected_signals else 1.0

    ent_match = extracted_entity_names & expected_entities
    entity_precision = (
        len(ent_match) / len(extracted_entity_names) if extracted_entity_names else 0.0
    )
    entity_recall = (
        len(ent_match) / len(expected_entities) if expected_entities else 1.0
    )
    if entity_precision + entity_recall > 0:
        entity_f1 = 2 * entity_precision * entity_recall / (entity_precision + entity_recall)
    else:
        entity_f1 = 0.0

    return SessionScore(
        session_id=str(expected.get("session_id") or ""),
        signal_coverage=round(signal_coverage, 4),
        entity_precision=round(entity_precision, 4),
        entity_recall=round(entity_recall, 4),
        entity_f1=round(entity_f1, 4),
        missing_signals=sorted(expected_signals - extracted_signal_texts),
        missing_entities=sorted(expected_entities - extracted_entity_names),
        spurious_entities=sorted(extracted_entity_names - expected_entities),
    )


# ---------------------------------------------------------------------------
# Golden-set IO
# ---------------------------------------------------------------------------

def _load_golden(golden_dir: Path) -> dict[str, dict]:
    """Walk ``<slug>.expected.yaml`` files → ``{session_id: expected}``.

    Phase 1 stores golden expectations in YAML alongside the transcript
    fixtures so a hand-labeller can edit them in a normal editor. The
    ``session_id`` is the filename stem (matching the ingest slug)."""
    import yaml

    out: dict[str, dict] = {}
    if not golden_dir.is_dir():
        return out
    for fp in sorted(golden_dir.glob("*.expected.yaml")):
        try:
            data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            log.warning("eval: bad YAML in %s (%s); skipping", fp, exc)
            continue
        sid = fp.stem.replace(".expected", "")
        data["session_id"] = data.get("session_id") or sid
        out[data["session_id"]] = data
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_eval(
    golden_dir: Path = GOLDEN_DIR,
    *,
    llm: Any = None,
    model: Optional[str] = None,
    enrich: bool = True,
) -> EvalReport:
    """Score every session that has a matching ``<slug>.expected.yaml``.

    By default, runs enrichment on each session first (real LLM call).
    Pass ``enrich=False`` to score whatever's currently in the store —
    useful for "did the dedup logic regress?" without paying for re-enrich.
    """
    from transcripts import store
    from transcripts.enrich import enrich_session

    expected_by_id = _load_golden(golden_dir)
    report = EvalReport()
    for sid, expected in expected_by_id.items():
        session = store.load_session(sid)
        if session is None:
            log.warning("eval: golden references unknown session_id %r — skipping", sid)
            continue
        if enrich:
            enrich_session(session, llm=llm, model=model)
        score = _score(session.derived, expected)
        score.session_id = sid
        report.sessions.append(score)
    return report.finalize()


# ---------------------------------------------------------------------------
# Baseline persistence — "did this prompt change move a number?"
# ---------------------------------------------------------------------------

def save_baseline(report: EvalReport, path: Path) -> None:
    """Write the aggregate + per-session scores to JSON for later diffing."""
    payload = {
        "aggregate": {
            "avg_signal_coverage": report.avg_signal_coverage,
            "avg_entity_precision": report.avg_entity_precision,
            "avg_entity_recall": report.avg_entity_recall,
            "avg_entity_f1": report.avg_entity_f1,
        },
        "sessions": [asdict(s) for s in report.sessions],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def diff_baseline(report: EvalReport, baseline_path: Path) -> dict:
    """Compute deltas against a previously-saved baseline. Pretty-print friendly."""
    if not baseline_path.exists():
        return {"warning": f"no baseline at {baseline_path}; nothing to compare"}
    prev = json.loads(baseline_path.read_text(encoding="utf-8"))
    pa = prev.get("aggregate") or {}
    return {
        "signal_coverage":  _delta(pa.get("avg_signal_coverage", 0.0), report.avg_signal_coverage),
        "entity_precision": _delta(pa.get("avg_entity_precision", 0.0), report.avg_entity_precision),
        "entity_recall":    _delta(pa.get("avg_entity_recall", 0.0), report.avg_entity_recall),
        "entity_f1":        _delta(pa.get("avg_entity_f1", 0.0), report.avg_entity_f1),
    }


def _delta(prev: float, now: float) -> dict:
    return {"prev": round(prev, 4), "now": round(now, 4), "delta": round(now - prev, 4)}
