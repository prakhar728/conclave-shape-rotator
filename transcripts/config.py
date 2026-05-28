"""Pipeline-wide constants for the transcripts package.

`IMPLEMENTATION_PLAN.md` §F. Distinct from the **host** ``config.py`` at
the repo root (which owns ``get_llm`` and provider settings). This module
is pure data — no logic, no I/O — so it's safe to import from anywhere.

The single non-obvious knob is ``CHUNK_MAX_TOKENS``. It must be **≤ the
model's ``num_ctx``** or long transcripts get silently truncated inside
the model with zero error (the gotcha §F flags about Ollama defaulting
to 2048). Our ``ollama/Modelfile.qwen-conclave`` bakes ``num_ctx=8192``,
giving 2k tokens of headroom over the chunk budget for prompt scaffolding
and the JSON response.
"""
from __future__ import annotations

from pathlib import Path

# --- Chunking --------------------------------------------------------------

#: Per-chunk input budget, in (heuristic) tokens. MUST be ≤ model num_ctx.
CHUNK_MAX_TOKENS: int = 6000

#: Trailing-context overlap between adjacent chunks. Keeps the reducer
#: from missing a signal that straddles a chunk boundary.
CHUNK_OVERLAP_TOKENS: int = 400

#: Chars-per-token heuristic. English averages ~4 chars/token; we use the
#: inverse here so ``estimate_tokens(text) = len(text) * TOKENS_PER_CHAR``.
TOKENS_PER_CHAR: float = 0.25


# --- Model selection -------------------------------------------------------

#: Per-stage model overrides. ``None`` → ``config.get_llm()`` backend default
#: (qwen2.5-conclave under Ollama, deepseek under NearAI). Pin these only
#: after eval (C9) says a specific id is worth committing to.
ENRICH_MODEL: str | None = None
REDUCE_MODEL: str | None = None


# --- Reduce caps -----------------------------------------------------------

#: Maximum number of signals to keep after the reduce step.
MAX_SIGNALS: int = 8

#: Maximum number of entities to keep after the reduce step.
MAX_ENTITIES: int = 30

#: Maximum number of topics in `Derived.topics` after the reduce step. Topics
#: are short theme tags (1–3 words) — 8 is plenty for a meeting card filter.
MAX_TOPICS: int = 8


# --- Paths -----------------------------------------------------------------

#: Golden-set directory (C9 eval consumes this). The 13 real cohort
#: transcripts already live here from C1.
GOLDEN_DIR: Path = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "transcripts"
