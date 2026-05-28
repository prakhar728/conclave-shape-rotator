"""Map-reduce enrichment + backfill pass.

`IMPLEMENTATION_PLAN.md` §G7 / §H C8. Produces ``derived`` for a session:

- 1 chunk → one ``invoke_json`` call with ``SINGLE_*`` (the fast path).
- N chunks → N ``invoke_json`` calls with ``CHUNK_*`` (map), then **one**
  ``invoke_json`` summary-reduce with ``REDUCE_*``. Entity dedup and signal
  capping happen deterministically — only the summary actually round-trips
  through the model on the reduce step.

``enrich_pending`` is the backfill: walks ``store.list_pending`` and
re-enriches each session, **stamping provenance** (``model_id``,
``enrich_prompt_version``, ``chunk_count``). A per-session
``LLMUnavailable`` is logged and skipped so a credit-wall / network blip
doesn't crash the whole pass — that's the structural win from §B.2.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from transcripts import store
from transcripts.chunk import chunk_segments
from transcripts.config import MAX_ENTITIES, MAX_SIGNALS
from transcripts.llm import LLMOutputError, LLMUnavailable, invoke_json
from transcripts.models import Derived, Entity, RawSegment, Session, Signal
from transcripts.prompts import (
    CHUNK_SYSTEM,
    CHUNK_USER,
    ENRICH_PROMPT_VERSION,
    REDUCE_SYSTEM,
    REDUCE_USER,
    SINGLE_SYSTEM,
    SINGLE_USER,
)

log = logging.getLogger(__name__)


_VALID_SIGNAL_KINDS = {"decision", "insight", "impactful_point", "action_item", "open_question"}
_VALID_ENTITY_TYPES = {"person", "project", "technology", "concept", "org"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transcript_text(session: Session) -> str:
    """Render the diarization as ``[speaker] text`` lines for the prompt."""
    return _segments_to_text(session.raw_diarization)


def enrich_session(
    session: Session,
    *,
    llm: Any = None,
    model: Optional[str] = None,
    max_chunk_tokens: Optional[int] = None,
) -> Session:
    """Run enrichment and return the session with ``derived`` filled.

    Mutates ``session.derived`` and ``session.metadata`` (provenance stamps)
    only; ``raw_diarization`` is untouched. Pass ``llm`` to inject a fake
    in tests; otherwise the configured backend is used.

    ``max_chunk_tokens`` overrides ``CHUNK_MAX_TOKENS`` for this call only —
    useful when the backend supports a larger context than the default
    (e.g. hosted Gemma at 54K vs local Ollama capped at the Modelfile's
    ``num_ctx=8192``). Pass ``None`` (default) to use the config constant.
    """
    chunker_kwargs = {"max_tokens": max_chunk_tokens} if max_chunk_tokens is not None else {}
    chunks = chunk_segments(session.raw_diarization, **chunker_kwargs)
    chunk_count = max(1, len(chunks))

    if len(chunks) <= 1:
        derived = _enrich_single(
            _segments_to_text(chunks[0] if chunks else session.raw_diarization),
            llm=llm,
            model=model,
        )
    else:
        partials = [
            _enrich_chunk(_segments_to_text(c), index=i, total=len(chunks), llm=llm, model=model)
            for i, c in enumerate(chunks)
        ]
        derived = _reduce(partials, llm=llm, model=model)

    session.derived = derived
    session.metadata.model_id = _model_id(llm, model)
    session.metadata.enrich_prompt_version = ENRICH_PROMPT_VERSION
    session.metadata.chunk_count = chunk_count
    return session


@dataclass
class EnrichReport:
    enriched: int = 0
    skipped_unavailable: int = 0
    skipped_output_error: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (session_id, error)


def enrich_pending(
    *,
    only_stale: bool = True,
    session_id: Optional[str] = None,
    llm: Any = None,
    model: Optional[str] = None,
) -> EnrichReport:
    """Backfill: walk ``store.list_pending`` and enrich each session.

    ``only_stale=True`` (default) treats sessions whose stored
    ``enrich_prompt_version`` doesn't match the current one as pending too
    — that's how a prompt bump triggers re-enrichment without manual flags.

    ``LLMUnavailable`` (credit/connection) → log + skip + continue. The
    next call resumes where this one stopped. Output errors (bad JSON
    after one repair) skip just the offending session — usually a single
    awkward transcript, not the whole batch.
    """
    report = EnrichReport()
    if session_id:
        s = store.load_session(session_id)
        sessions = [s] if s else []
    else:
        sessions = store.list_pending(ENRICH_PROMPT_VERSION if only_stale else None)
    for sess in sessions:
        try:
            enrich_session(sess, llm=llm, model=model)
        except LLMUnavailable as exc:
            log.warning("enrich_pending: LLM unavailable for %s (%s) — skipping", sess.session_id, exc)
            report.skipped_unavailable += 1
            continue
        except LLMOutputError as exc:
            log.warning("enrich_pending: output error for %s (%s) — skipping", sess.session_id, exc)
            report.skipped_output_error += 1
            report.failed.append((sess.session_id, f"LLMOutputError: {exc}"))
            continue
        store.set_derived(sess.session_id, sess.derived)
        store.set_metadata(sess.session_id, sess.metadata)
        report.enriched += 1
    return report


# ---------------------------------------------------------------------------
# Map + reduce
# ---------------------------------------------------------------------------

def _enrich_single(body: str, *, llm: Any, model: Optional[str]) -> Derived:
    data = invoke_json(
        [SystemMessage(content=SINGLE_SYSTEM), HumanMessage(content=SINGLE_USER(body))],
        llm=llm,
        model=model,
        required_keys=("summary",),
    )
    return _to_derived(data)


def _enrich_chunk(body: str, *, index: int, total: int, llm: Any, model: Optional[str]) -> dict:
    """One LLM call per chunk → partial. Returns the raw parsed dict so
    ``_reduce`` can dedupe entities and cap signals deterministically."""
    return invoke_json(
        [SystemMessage(content=CHUNK_SYSTEM), HumanMessage(content=CHUNK_USER(body, index, total))],
        llm=llm,
        model=model,
        required_keys=("summary",),
    )


def _reduce(partials: list[dict], *, llm: Any, model: Optional[str]) -> Derived:
    """Combine N partial extractions into one ``Derived``.

    - **summary**: synthesized by one LLM call over the partial summaries.
    - **signals**: concatenated, dedup'd by normalized text, capped at
      ``MAX_SIGNALS``. Deterministic — no LLM call. Order preserved so the
      first chunk's signals win on ties (rough proxy for "most impactful
      first" since cohort transcripts usually open with the decision).
    - **entities**: concatenated, dedup'd by normalized name (case-/punct-
      insensitive), capped at ``MAX_ENTITIES``. Evidence strings from
      duplicates are joined with ``"; "`` so the surface form's
      cross-chunk provenance is preserved.
    """
    partial_summaries = [str(p.get("summary") or "").strip() for p in partials]
    partial_summaries = [s for s in partial_summaries if s]
    if partial_summaries:
        reduced = invoke_json(
            [
                SystemMessage(content=REDUCE_SYSTEM),
                HumanMessage(content=REDUCE_USER(partial_summaries)),
            ],
            llm=llm,
            model=model,
            required_keys=("summary",),
        )
        summary = str(reduced.get("summary") or "").strip() or None
    else:
        summary = None

    # Signals: concat → dedup by normalized text → cap.
    raw_signals: list[dict] = []
    for p in partials:
        for item in p.get("signals") or []:
            if isinstance(item, dict):
                raw_signals.append(item)
    signals = _dedup_signals(raw_signals)[:MAX_SIGNALS]

    # Entities: concat → dedup by normalized name → cap.
    raw_entities: list[dict] = []
    for p in partials:
        for item in p.get("entities") or []:
            if isinstance(item, dict):
                raw_entities.append(item)
    entities = _dedup_entities(raw_entities)[:MAX_ENTITIES]

    return Derived(summary=summary, signals=signals, entities=entities, graph_nodes=None)


# ---------------------------------------------------------------------------
# Defensive dict → typed
# ---------------------------------------------------------------------------

def _to_derived(data: dict) -> Derived:
    """One-shot path: turn the model's JSON into a typed ``Derived``.

    Coerces unknown ``kind``/``type`` values to defaults, drops blank-text
    signals and blank-name entities. Matches the historical Phase-0
    behavior the 7 legacy tests assert on.
    """
    summary = data.get("summary")
    if summary is not None:
        summary = str(summary).strip() or None

    signals: list[Signal] = []
    for item in data.get("signals") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kind = str(item.get("kind") or "insight").strip().lower()
        if kind not in _VALID_SIGNAL_KINDS:
            kind = "insight"
        # v1: prefer the new `said_by` key, fall back to legacy `speakers`
        # until V3 lands the prompt-contract change. Keeps the suite green
        # against either shape during the v1→v2 transition.
        said_by_raw = item.get("said_by")
        if said_by_raw is None:
            said_by_raw = item.get("speakers")
        said_by = [str(s) for s in (said_by_raw or []) if s]
        about_person = [str(s) for s in (item.get("about_person") or []) if s]
        source_quote = item.get("source_quote")
        source_quote = str(source_quote).strip() if source_quote else None
        signals.append(Signal(
            kind=kind, text=text,
            said_by=said_by, about_person=about_person,
            source_quote=source_quote or None,
        ))

    entities: list[Entity] = []
    for item in data.get("entities") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        etype = str(item.get("type") or "concept").strip().lower()
        if etype not in _VALID_ENTITY_TYPES:
            etype = "concept"
        entities.append(Entity(
            name=name, type=etype,
            evidence=str(item.get("evidence") or "").strip(),
            cohort_status=_coerce_cohort_status(item.get("cohort_status")),
            affiliation=(str(item.get("affiliation")).strip() or None)
                        if item.get("affiliation") else None,
        ))

    # v1: topics on the single-pass path. The reduce-step aggregation
    # across multi-chunk partials lands in V4; for now, single-chunk
    # enrichment can populate topics directly if the model emits them.
    topics_raw = data.get("topics") or []
    topics: Optional[list[str]] = (
        [str(t).strip() for t in topics_raw if t and str(t).strip()]
        if topics_raw else None
    )

    return Derived(summary=summary, signals=signals, entities=entities,
                   topics=topics, graph_nodes=None)


def _coerce_cohort_status(value: Any) -> Optional[str]:
    """Defensive coercion of model-emitted ``cohort_status`` values.

    V1 plumbs the field through; the real deterministic post-process
    (matching against MOCK_DIRECTORY) lands in V4. Returns one of
    ``{"member","external","unknown"}`` or ``None``.
    """
    if value is None:
        return None
    v = str(value).strip().lower()
    return v if v in {"member", "external", "unknown"} else None


# ---------------------------------------------------------------------------
# Reduce-step helpers — deterministic dedup
# ---------------------------------------------------------------------------

def _dedup_signals(raw: list[dict]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for item in raw:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        key = _normalize_for_dedup(text)
        if key in seen:
            continue
        seen.add(key)
        kind = str(item.get("kind") or "insight").strip().lower()
        if kind not in _VALID_SIGNAL_KINDS:
            kind = "insight"
        # v1: same backward-compat read pattern as ``_to_derived``.
        said_by_raw = item.get("said_by")
        if said_by_raw is None:
            said_by_raw = item.get("speakers")
        said_by = [str(s) for s in (said_by_raw or []) if s]
        about_person = [str(s) for s in (item.get("about_person") or []) if s]
        source_quote = item.get("source_quote")
        source_quote = str(source_quote).strip() if source_quote else None
        out.append(Signal(
            kind=kind, text=text,
            said_by=said_by, about_person=about_person,
            source_quote=source_quote or None,
        ))
    return out


def _dedup_entities(raw: list[dict]) -> list[Entity]:
    """Dedup by normalized name; join evidence strings on duplicates.

    v1 plumbs ``cohort_status`` and ``affiliation`` through the dedup —
    the deterministic post-process that *populates* ``cohort_status`` from
    MOCK_DIRECTORY lands in V4 along with the §6 normalization tightening.
    """
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for item in raw:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = _normalize_for_dedup(name)
        if key not in by_key:
            etype = str(item.get("type") or "concept").strip().lower()
            if etype not in _VALID_ENTITY_TYPES:
                etype = "concept"
            by_key[key] = {
                "name": name,
                "type": etype,
                "evidence": str(item.get("evidence") or "").strip(),
                "cohort_status": _coerce_cohort_status(item.get("cohort_status")),
                "affiliation": (str(item.get("affiliation")).strip() or None)
                               if item.get("affiliation") else None,
            }
            order.append(key)
        else:
            extra = str(item.get("evidence") or "").strip()
            if extra and extra not in by_key[key]["evidence"]:
                by_key[key]["evidence"] = (
                    by_key[key]["evidence"] + "; " + extra
                    if by_key[key]["evidence"]
                    else extra
                )
            # cohort_status precedence on collapse: member > external > unknown > None.
            _CS_RANK = {"member": 3, "external": 2, "unknown": 1, None: 0}
            new_cs = _coerce_cohort_status(item.get("cohort_status"))
            if _CS_RANK[new_cs] > _CS_RANK[by_key[key]["cohort_status"]]:
                by_key[key]["cohort_status"] = new_cs
            # affiliation: keep first non-empty.
            if not by_key[key]["affiliation"] and item.get("affiliation"):
                by_key[key]["affiliation"] = str(item.get("affiliation")).strip() or None
    return [Entity(**by_key[k]) for k in order]


def _normalize_for_dedup(s: str) -> str:
    return " ".join(s.lower().split())


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def _segments_to_text(segs: list[RawSegment]) -> str:
    return "\n".join(f"[{s.speaker}] {s.text}" for s in segs)


def _model_id(llm: Any, model_override: Optional[str]) -> str:
    """Best-effort provenance: which model produced this derived block."""
    if model_override:
        return model_override
    if llm is not None:
        # FakeLLM / langchain ChatOpenAI: try to read .model_name, then fall back
        # to the class name (so test FakeLLMs still get *something* recorded).
        for attr in ("model_name", "model", "model_id"):
            val = getattr(llm, attr, None)
            if val:
                return str(val)
        return type(llm).__name__
    # Walk the config to record the resolved backend default.
    try:
        from config import settings
        return settings.ollama_model if settings.llm_backend == "ollama" else settings.default_model
    except Exception:  # noqa: BLE001
        return "unknown"
