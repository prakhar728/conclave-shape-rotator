# EVAL.md — Phase 3.5 decision records

> **This file is a real artifact, not a scratch file** (BUILD-PLAN ground
> rule 7). It accrues decision records: C4 (locked prompt shape + F1),
> C24 (NDCG@10 baseline), C25 (reranker decision), C36 (smoke journey),
> C39 (final perf budgets). Each append is a decision record with
> numbers. Future-you reads this when something needs re-evaluation.
>
> Distinct from `transcripts/eval/EVAL_v2.2.md` (v1 enrichment-prompt
> eval) — this file covers the Phase 3.5 KB pipeline.

---

## C4 — Q1 extraction prompt shape (2026-06-03)

### Decision

**Q1 LOCKED: `one_prompt`** — one schema-guided extraction call per
chunk emitting entities + all five obligation types (Survey D14
Primary). per_type is rejected: it costs ~6× per meeting at ingest and
scored *worse* on the headline metric (macro-F1 0.10 vs 0.12), worse
type-agnostic (0.14 vs 0.22), and worse on entities (0.45 vs 0.50).

**With a mandatory caveat triggered by the pre-registered rule:** both
arms scored below the 0.25 usability floor. Extraction prompts MUST be
iterated before C13 productionizes them (see "Why absolute F1 is low"
— part eval-design artifact, part real quality gap). C13's regression
test should be re-baselined after prompt iteration, not pinned to
these numbers.

### Eval set provenance

3 transcripts from the May-2026 Shape Rotator cohort fixtures, pinned in
C1 (commit d3c3680, Elocute swap 24c9380):

| slug | transcript | shape | gold counts (e/o/q) |
|---|---|---|---|
| project-intros-agents-day3 | Project Intros Agents Day 3 (May 21) | technical-project-critiques | 25 / 10 / 8 |
| dstack-intro-salon | Dstack Intro Salon (May 20) | technical-demo-salon | 32 / 10 / 10 |
| elocute | Elocute (May 26) | founder-demo-feedback | 15 / 8 / 10 |

**Ground truth is Codex-labelled** (C2.7, commit 07785fc): OpenAI Codex
CLI (gpt-5.5, reasoning=high) labelled each transcript from the
bare-schema `tests/fixtures/transcripts/LABELER_PROMPT.md` with no
worked examples and no access to other yamls. Rationale: GPT-family
ground truth is cross-family from BOTH the extractor being graded AND
the (Claude) prompt author — breaks the self-grading loop without
requiring ~6h of human annotation.

**The standing caveat that inherits to every consumer of these
fixtures:** F1 against this ground truth measures *agreement with
Codex*, not accuracy against human judgment. Relative comparisons
(prompt shape A vs B on the same truth) are sound; absolute numbers
should never be quoted as extraction accuracy. If a customer-facing
accuracy claim is ever needed, re-code the eval set with human
annotators first (Q7 wedge re-code is the natural moment).

Cross-validation note: a discarded independent hand-labelling of
elocute (Claude, commit 59829a9) converged with Codex on the anchor
obligations (Wiki email commitment t7, MCP integration action t40,
monetization decision t29/31), which is the best available signal that
the Codex labels are not idiosyncratic.

### Bake-off methodology

- Script: `scripts/eval_extraction_bakeoff.py`; logic in
  `transcripts/extract_bakeoff.py` (strategies) +
  `transcripts/eval_bakeoff.py` (scoring).
- **Strategies:** `one_prompt` (1 call/chunk emitting entities + all 5
  obligation types; Survey D14 Primary) vs `per_type` (1 entities call
  + 5 per-type calls per chunk; D14 Fallback, ~6× cost).
- **Model/backend:** RedPill (Phala TEE-hosted) `google/gemma-3-27b-it`
  — the v1 production backend (`CONCLAVE_LLM_BACKEND=redpill` in .env).
  Deviation from roadmap §3.5a.4's nominal qwen2.5:14b is deliberate:
  the locked prompt shape should be chosen on the model that will run
  it in production. (See `transcripts/OLLAMA.md` "Backend reality
  check".)
- **Chunking:** turn-id-annotated turns packed to ~4k heuristic tokens,
  2-turn overlap (`extract_bakeoff.chunk_turns`). Turn ids rendered as
  `[N] speaker: text`; the model echoes them back.
- **Matching (fuzzy by necessity):** greedy one-to-one assignment;
  obligation pair score = 0.7 × token-set Jaccard on description +
  0.3 × turn-id Jaccard, threshold 0.35; matched within same-type
  buckets for per-type F1, plus a type-agnostic pass to expose pure
  type-confusion cost. Entities matched type-agnostically on max name
  similarity across canonical + surface forms (exact=1.0,
  containment=0.9, else token-set), threshold 0.5.
- **Headline metric:** obligation macro-F1 over types with gold
  support. Tie-breakers: entity F1, then cost (per_type must clearly
  win to justify ~6× ingest calls).

### Results

Full tables in `tests/fixtures/transcripts/bakeoff_results.md`
(re-scored after fixing a punctuation-insensitivity bug in the
token-set matcher; predictions dumped to
`bakeoff_predictions_*.json`, re-scorable via `--rescore`).

Aggregate (all transcripts pooled):

| metric | one_prompt | per_type |
|---|---|---|
| obligation F1: action (n=16) | 0.11 | 0.20 |
| obligation F1: decision (n=1) | 0.00 | 0.00 |
| obligation F1: commitment (n=7) | 0.00 | 0.20 |
| obligation F1: open_question (n=3) | 0.00 | 0.04 |
| obligation F1: blocker (n=1) | 0.50 | 0.05 |
| **obligation macro-F1** | **0.12** | **0.10** |
| obligation F1 (type-agnostic) | 0.22 | 0.14 |
| entity F1 | 0.50 | 0.45 |

Wall-clock per transcript (RedPill gemma-3-27b): one_prompt 164–339s,
per_type 372–726s. Volume: one_prompt emitted 22–47 obligations per
transcript, per_type 58–88 (gold: 8–10) — per_type's per-type prompts
each re-harvest the chunk, multiplying over-extraction.

### Why absolute F1 is low (diagnosis, not excuse)

1. **Granularity mismatch (largest factor).** Codex's gold labels are
   *consolidated*: one obligation spanning 5–9 turns ("Albiona needs a
   callback/onboarding loop — email, SMS, dashboard"), 8–10 per
   transcript. The extractor emits *granular* per-turn obligations
   (20–47), often correct in content but fragmented. Greedy 1:1
   matching counts every fragment beyond the first as a false
   positive. Verified by spot-check: the extractor DID find the
   email/SMS onboarding obligation, the MCP action (t40), the Wiki
   flight-dates commitment (t7) — they match gold semantically but
   are sliced differently.
2. **Type confusion.** Type-agnostic F1 nearly doubles one_prompt's
   score (0.12 → 0.22): the extractor finds obligations but labels
   action/commitment/decision differently than Codex. Consistent with
   Survey T2's warning that these labels have low inter-annotator
   agreement — Codex and gemma are effectively two annotators
   disagreeing.
3. **Gold sparsity.** 28 obligations across 3 transcripts is thin;
   single-instance types (decision n=1, blocker n=1) make those
   per-type F1 cells coin-flips.

Implications for C13: (a) add consolidation instructions to the locked
one_prompt shape (merge repeated obligations before emitting), (b)
consider scoring matches at type-agnostic level for regression
purposes with type-accuracy as a separate metric, (c) re-baseline
after prompt iteration.

### What would change the decision

per_type's only wins were action (0.20 vs 0.11) and commitment (0.20
vs 0.00) — both drowned by its precision collapse elsewhere and 6×
cost. If C13's prompt iteration hits a ceiling on action/commitment
recall specifically, a *hybrid* (one_prompt + one targeted commitment
pass) is the first escalation, not full per_type.

### Decision rule (pre-registered)

Committed before seeing numbers, to keep the call honest:

- per_type wins **only if** its obligation macro-F1 beats one_prompt
  by ≥ 0.10 — the ~6× ingest cost needs a visible quality gap.
- Anything less → **one_prompt** (cheaper, simpler, one schema).
- If both macro-F1 < 0.25: neither shape is usable as-is → fall back
  to one_prompt + manual review tooling per BUILD-PLAN "When something
  deviates", and revisit prompts before C13.

---

## C13 — extraction prompt re-baseline (2026-06-04)

The consolidation + entity-discipline iteration mandated by the C4
usability-floor trigger, measured as bake-off strategy `one_prompt_v2`
(same chunking as the original arms; full tables in
`tests/fixtures/transcripts/bakeoff_results_v2.md`):

| metric | one_prompt (C4) | one_prompt_v2 (C13) |
|---|---|---|
| entity F1 | 0.50 | **0.62** |
| obligation F1, type-agnostic | 0.22 | **0.26** |
| obligation macro-F1 (per-type) | 0.12 | 0.03 |

Reading: the prompt iteration improved *what gets found* (entities,
obligations-as-content) and worsened per-type label agreement with
Codex — consistent with Survey T2 (action/commitment/decision labels
have low inter-annotator agreement; Codex and gemma are two annotators
disagreeing). Per implication (b) recorded at C4, the regression
baseline is therefore pinned on the metrics that reflect user-visible
quality:

**C27 regression baseline: type-agnostic obligation F1 ≥ 0.21,
entity F1 ≥ 0.55** (C13 numbers minus 0.05 slack). Per-type
macro-F1 is reported but non-blocking. Type-accuracy-given-match is
the metric to watch when revisiting D13 (five tables vs enum) at the
two-annotator-agreement trigger.

---

## C24/C25 — search NDCG@10 baseline + Q3 reranker decision (2026-06-04)

Eval: the 28 C2 queries against the live hybrid index (chunks from the
real cohort sessions; `scripts/eval_search_quality.py`; binary chunk
relevance = chunk turn_ids ∩ gold relevant_turn_ids; per-session
retrieval scope).

| configuration | NDCG@10 (n=28) |
|---|---|
| **hybrid (FTS5 + vec, RRF k=60)** | **0.814** |
| FTS5 BM25 only | 0.835 |
| dense (nomic 256-dim) only | 0.693 |

Found + fixed during measurement: `_fts_sanitize` originally joined
terms with implicit AND — natural-language questions scored NDCG 0.000
on the FTS leg because stopwords had to co-occur in one chunk. OR-join
restored BM25 semantics (recall via OR, ordering via rank) and lifted
hybrid 0.693 → 0.814.

**Q3 DECISION: ship WITHOUT the cross-encoder reranker.** Pre-registered
rule (C4 §Bake-off methodology / roadmap 3.5c.4): add BGE only if
NDCG@10 < 0.6. We're at 0.814. No reranker, no +50-200ms per query,
no third model in the enclave. Revisit if real users complain about
top-10 quality (the feature-flag escalation stays cheap).

Honest caveat on FTS-only beating hybrid by 0.02: the gold queries are
Codex-written and tend to quote transcript vocabulary, which favors
lexical matching; dense retrieval earns its place on paraphrase
queries this eval under-represents. Hybrid stays (Survey D7), n=28 is
too small to read a 0.02 gap as signal.

**C27 regression floor: hybrid NDCG@10 ≥ 0.75** (0.814 − ~0.06 slack).

---

## C36/C39 — smoke journey + perf sanity (2026-06-04)

Programmatic journey against the REAL DB via TestClient (fresh signup,
demo content from migration 0009 + seed_demo.py):

1. signup → personal workspace ✓
2. /entities → 74 rows, 5ms (top: DStack, Andrew Miller, LSDan…) ✓
3. /entities/DStack → 3 meetings ✓
4. /obligations → 123 current rows ✓
5. /search "deploying applications in trusted execution environments"
   → 20 results, top hit demo-dstack-intro-salon, **84ms** ✓
6. /graph → 3 meetings + 74 entities + 13 speakers, 107 edges, **7ms** ✓
7. meeting view via graph node (demo session, authed) ✓ ;
   anonymous request 403 ✓
8. /ingest-metrics → per-stage means present ✓

Perf vs roadmap budgets (3.5f.5): search 84ms (< 500ms no-reranker
budget) · graph 7ms live / <1s enforced at 50 synthetic meetings by
tests/test_graph_perf.py. Suite: 522 passed (target 450+).

Ingest cost reality (roadmap §7 had only estimates): per-session stage
means now queryable via /ingest-metrics; extraction ≈1 call/chunk,
importance ≈1/10 items, upsert ≈1/obligation — matching the budget
table's "~3-7× baseline" prediction. Demo+cohort extraction across 8
sessions produced 210 entities / 518 obligations / 1977 mentions.

Known v1 demo caveats: cohort + demo copies of the same 3 transcripts
both exist (entity duplicates across session families are expected and
ER-merged within type+name); context headers off by default for cost
(--headers flag exists on both backfill + seed scripts).
