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

---

## H1 — held-out retrieval cross-check on QMSum (2026-06-08)

The C24 number (NDCG@10 0.814) is **in-sample**: 28 Codex-written queries
over the same 3 cohort transcripts the FTS sanitizer was tuned on, with
queries that tend to quote transcript vocabulary. This record answers
"does retrieval quality survive a held-out, human-labelled, paraphrase-
heavy benchmark on meetings the system has never seen?"

### Setup
- **Data:** QMSum (Zhong et al. 2021) test split, all 3 domains —
  Academic (ICSI), Product (AMI), Committee (parliamentary). 35 meetings,
  **244 human-annotated specific queries** with gold `relevant_text_span`
  turn ranges. Cloned at `datasets/qmsum/`.
- **Harness:** `scripts/eval/ingest_harness.py` pushes each meeting through
  the **real production seam** (`store.save_session` → `kb_pipeline.index_session`)
  — not a hand-rewired copy — so the eval re-measures whatever the live
  pipeline does. Scorer `scripts/eval/score_retrieval.py`; translator
  `scripts/eval/qmsum.py`.
- **Methodology = C24, held identical for comparability:** binary chunk
  relevance (chunk relevant iff `turn_ids ∩ gold`), per-meeting retrieval
  scope, RRF k=60, fetch 50, headers OFF, NDCG@10.

### Results (NDCG@10)

| domain | n | FTS | dense | hybrid |
|---|---|---|---|---|
| Academic (ICSI) | 49 | 0.676 | 0.592 | 0.684 |
| Committee | 66 | 0.777 | 0.640 | 0.755 |
| Product (AMI) | 129 | 0.807 | 0.636 | 0.791 |
| **OVERALL** | **244** | **0.773** | **0.628** | **0.760** |

vs in-sample C24: hybrid 0.814 / FTS 0.835 / dense 0.693 (n=28).

### Reading
1. **Retrieval quality generalizes — it was not an in-sample mirage.**
   Hybrid 0.760 held-out vs 0.814 in-sample (−0.054) on a different corpus,
   human (not Codex) queries, and 244 (not 28) queries. The leakage worry
   that the 0.814 was inflated by Codex quoting transcript vocabulary turns
   out to cost only ~0.05. This materially de-risks using retrieval as the
   substrate for the cross-session layer.
2. **FTS ≥ hybrid persists on held-out human paraphrase queries** (0.773 vs
   0.760 overall; FTS wins Committee + Product, hybrid edges Academic). The
   C24 hypothesis that dense "earns its place on paraphrase queries this
   eval under-represents" is *not* supported here: even on paraphrase-heavy
   human queries, dense (0.628) trails FTS, and RRF-fusing it in slightly
   lowers the overall score. Caveat: QMSum specific-queries still share
   content words with the transcript and gold spans are broad, both of
   which favour lexical recall — so this weakens, not kills, the dense case.
   **Action: this strengthens the C25 "no reranker" call and adds a new
   open question — is the dense leg net-positive at all on meeting QA? Worth
   an ablation before investing further in embeddings.** Still above the
   C25 reranker trigger (NDCG@10 < 0.6) on every domain, so no reranker.
3. **Domain spread:** Product/AMI strongest (0.79), ICSI weakest (0.68 —
   disfluent, cross-talk-heavy research meetings are genuinely harder).

### Caveats inheriting from this record
- Numbers are headers-OFF (cost parity with C24). Production default is
  headers-ON; a `--headers` run would measure that (LLM cost). Not yet run.
- This validates *retrieval*, the single-meeting component. It says nothing
  about cross-session/collaboration quality (separate eval).

---

## E1 — entity-resolution over-merge root cause + eval blind-spot (2026-06-11)

*Branch `fix/entity-resolution-overmerge`. Tracked as OI-7 in
`scripts/eval/OPEN_ITEMS.md`. This record documents (a) the confirmed cause and
(b) why no existing eval caught it — the second is the actionable part.*

### Symptom
A few entities became "black holes" in the real cohort DB: `DStack` = 94 distinct
surface forms / 406 mentions (swallowed `hermes`, `ethereum`, `chatgpt`, `claude`,
`github`, …), `CBM` = 75, `Dstack` = 52, `Jupyter Notebook` = 46; **everything
else sits at a normal 2–3** — a sharp cliff. Surfaced downstream as coincidental
Connections matches (the matcher joins on a corrupt entity index).

### Root cause — degenerate short-text embeddings → blind auto-merge
`nomic-embed-text:v1.5` (Ollama) returns a **near-constant vector for ultra-short
inputs**, so bare entity names collapse onto one point `C`:
- `embed("DStack") == embed("Benchling") == embed("ChatGPT")` **byte-identical**
  (cosine 1.0000); sentences embed fine (cos ~0.53). Collapse scales with length:
  1 tok → 1.000, 2 → 0.882, 5–6 → 0.55–0.79. Mechanism: the fixed
  `"search_document: "` prefix dominates a 1-token input.
- **80 / 225 stored entity vectors are mutually identical** (cos > 0.999), all
  single-token names; `DStack ≡ CBM ≡ Dstack`.
- cos ≈ 1.0 trips `resolve_entity`'s auto-merge band (`sim > 0.90`), which **never
  calls the LLM** → every short non-person name is absorbed into the per-type
  incumbent at `C` (one black hole per non-person type). Replaying `_llm_tiebreak`
  on the swallowed pairs returns `same=False` — the LLM is accurate; it just never
  runs.
- **Natural control:** ~70 person names also collapse onto `C`, yet every person
  entity is clean (1 surface) — persons use the exact-match path
  (`entity_resolution.py:88–94`), not embeddings. ⇒ bug = (short-name embedding
  collapse) × (non-person cosine auto-merge). Long-text (chunk/obligation)
  embeddings are healthy ⇒ **retrieval/search unaffected; contained to the entity
  layer.** The threshold (0.90) and the LLM prompt are NOT the lever.

### Why no existing eval caught it (the blind spot)
- **Bake-off entity F1 (C4/C13) measures the wrong stage.** It scores
  `extract`/`extract_from_chunk` **per single transcript** vs Codex gold — it never
  exercises the **cross-session resolver over an accumulated pool**, which is where
  the merge happens. And F1 matches on canonical_name, so a black-hole "DStack"
  still matches gold "DStack"; the junk surfaces don't move per-transcript F1.
- **`tests/test_entity_resolution.py` mocks the embedder.** Its 11 unit tests build
  **synthetic fixed-angle vectors** (10°/35°/60°) to test band routing. They assume
  the embedder produces meaningful cosines, so the real collapse is invisible — the
  bug lives in the embedding the tests stub out.
- **`tests/test_kb_extract_pipeline.py`** monkeypatches embeddings + uses a size-1
  pool; collapse needs real embeddings + an accumulating pool.
- **No resolution-quality metric existed** (over/under-merge / cluster purity). The
  surface-count cliff that exposed it was an ad-hoc query, never a checked signal.

### Eval signals added (this record's deliverable)
- `tests/test_embed_health.py` — calls the **real** embedder on distinct short
  names; asserts they are not near-identical (max pairwise cosine bound). Standing
  monitor for the collapse; would have caught this immediately.
- `scripts/eval/check_entity_merge.py` — over-merge guardrail: flags any entity
  whose distinct-surface count exceeds a cliff threshold + prints the distribution.
- A **real-embedder** `resolve_entity` no-merge test (lexically-disjoint short
  names over an accumulated pool must NOT merge) — de-mocks the resolution test.

### Fix direction (grounded in METHODOLOGY_SURVEY D12/O3 + v1_improvements §6)
Lexical-first gate (normalize + edit-distance / shared-token / phonetic) for
non-person merges; demote bare-name cosine auto-merge; route genuine decisions
through the (accurate) LLM tiebreak. D12 was pre-registered `open` with trigger
"dedup quality drops below acceptable" — that trigger has fired.

### Acceptance
After the fix: the new guardrail + no-merge tests pass; **entity F1 stays ≥ C27
floor (0.55)**; a cohort re-ingest shows no entity > ~10 surfaces (bar genuine
high-frequency); the Connections junk class disappears.

### Outcome — fix shipped + validated (2026-06-11)
Shipped across 7 commits (eval signals → extraction definition/role → storage
category + definition-embedding → lexical-first resolver → API → frontend →
re-ingest). `resolve_entity` now embeds the entity **definition** (a sentence),
not the bare name; gates merges **lexical-first**; routes the rest through the LLM
tiebreak fed names+definitions — **no bare-cosine auto-merge** (the black-hole
short-circuit is gone). Taxonomy delivered as a derived `category`
(person/tech/affiliation), **no DB migration**.

- **Mechanism (regression-locked):** `tests/test_entity_resolution.py::
  test_real_embedder_disjoint_short_names_do_not_merge` flips from xfail to a real
  pass — collapsed short-name vectors (cos≈1.0) no longer merge.
- **Old metrics held** (bake-off `one_prompt_v2`, redpill gemma): entity F1
  **0.59** (≥ C27 floor 0.55), obligation type-agnostic **0.27** (≥ 0.21) — the
  obligation/insights prompt was untouched.
- **New metric — re-ingest of ALL 14 cohort fixtures** (the exact transcripts that
  produced the black holes) into a throwaway DB with the fixed pipeline: **575
  entities, surface distribution 1:520 / 2:29 / 3:3 / 4:1 — max 4 surfaces, ZERO
  black holes** (was `DStack` 94 / `CBM` 75 / `Dstack` 52 / `Jupyter Notebook`
  46). The cliff is gone. (`scripts/eval/reingest_oi7.py`.)
