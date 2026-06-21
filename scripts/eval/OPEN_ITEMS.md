# Eval — Open Items ("things still left on our plate")

Running backlog for the Conclave evaluation effort. Items are parked here
when found mid-stream so they don't derail the current phase; we pick them
up once the eval scaffold is built out or when a item is explicitly
prioritized. **Surface this list to the user at phase boundaries.**

Status legend: `OPEN` (not started) · `DEFERRED` (intentionally waiting on
something) · `DONE` (resolved, kept for history).

---

## OI-5 — Experiment observability: tokens, latency, traces across models  ·  OPEN
*Raised: 2026-06-08. Separate thread (needs its own plan + decisions).*

Today we have **partial** experiment observability and it blocks principled
model/cost decisions:
- **Time:** `ingest_metrics(session, stage)` logs `ms_elapsed` + `llm_call_count`
  + `items_in/out`. Bake-offs logged wall-clock. OK-ish.
- **Tokens:** NOT tracked — only call counts. EVAL.md cost figures are
  estimates (calls × assumed per-call), not measured prompt/completion tokens.
- **Traces / bottlenecks:** none. **LangSmith and all cloud tracing are
  deliberately hard-disabled in `config.py`** because they ship transcript
  content to a third party — incompatible with the TEE "operator-blind"
  thesis. So observability MUST be local/self-hosted; the off-the-shelf
  answer is off-limits.

**Scope when prioritized:** decide what to measure (tokens in/out per stage
per model, p50/p95 latency, $ per meeting-hour by backend), a local trace
sink (not LangSmith), and a cross-model cost/latency comparison harness.
Pairs naturally with the RedPill-vs-alternatives model bake-off. NOTE: this
is about the **LLM stages** (extraction/headers/enrichment on RedPill/gemma),
NOT retrieval — retrieval (FTS+dense+RRF) is LLM-free and local.

---

## OI-1 — Dense retrieval underperforms FTS on meeting QA  ·  OPEN
*Found: Phase 1a (2026-06-08). See `transcripts/EVAL.md` H1.*

**Observation.** Held-out QMSum NDCG@10: dense **0.628** vs FTS **0.773**;
RRF-fusing dense *lowers* hybrid (0.760 < 0.773). Worst on ICSI/Academic.
0.628 is mediocre-but-functional, **not broken** (broken would be ~0.1–0.3) —
it retrieves relevant content, just ranks it a notch below BM25.

**Why this matters.** The Phase-3 cross-session matcher leans on the same
embeddings. If dense ranking is weak, collaboration matching inherits it.
Resolve (or at least understand) before trusting Phase 3 matching.

**Candidate reasons (most → least likely to be the lever):**
1. **Matryoshka-256 truncation.** ANN index uses 256-dim truncated nomic
   vectors (768 stored). Truncation may cost ranking precision.
2. **Eval favors lexical by construction.** QMSum gold spans are broad
   (10–90 turns) and queries reuse transcript content words → BM25-friendly.
   May *understate* dense's true value rather than reflect a model flaw.
3. **Equal-weight RRF (k=60).** If dense is noisier, equal fusion drags
   hybrid even when dense helps on a query *subset* the aggregate hides.
4. **Chunk granularity.** ~1228-tok chunks may be too coarse for the
   embedding to localize the answer; a keyword hit is sharper.
5. **Prefix / model fit.** nomic needs `search_query:` / `search_document:`
   prefixes — verify applied. Model may simply be weak on disfluent meeting
   speech (ICSI dense was the worst cell).

**Diagnosis DONE (2026-06-08, `scripts/eval/ablate_dense.py`, 244 queries):**

| metric | FTS | dense |
|---|---|---|
| mean NDCG@10 | 0.773 | 0.628 |
| mean recall@10 | 0.916 | 0.776 |
| mean recall@50 | 1.000* | 0.850 |

Win/loss: dense **wins 23.4%**, loses 59.4%, ties 17.2% (avg +0.24 when it
wins, −0.34 when it loses). Complementarity on the 42 "hard" queries where
FTS fails (NDCG<0.5): **dense beats FTS on 64%**, big-rescue (+0.3) on 26%.
*(*FTS recall@50=1.0 is partly trivial: per-meeting scope + ≤50 chunks/meeting
means fetching 50 returns everything; the real comparison is recall@10 and the
fact dense@50=0.85 means it genuinely MISSES ~15% on long meetings.)*

**Verdict: dense is not broken and should NOT be cut — it's a weaker-but-
genuinely-complementary leg being fused naively.**
- It rescues 64% of the queries FTS fails → real complementary value (the
  whole reason hybrid exists). Cutting it would lose the tail.
- BUT equal-weight RRF (k=60) lets the weaker leg drag down the 59% FTS
  already wins → hybrid (0.760) dips just below FTS-only (0.773).
- It also has a real **recall miss** (~15% at @50, worse on long meetings) —
  consistent with Matryoshka-256 truncation and/or long-meeting candidate
  overflow.

**Lever (highest ROI first):**
1. **Weighted / asymmetric fusion** — let dense *promote* on its confident
   tail rescues without dragging the cases FTS nails. Cheapest, biggest win.
   *This is the fix; needs its own eval plan (how to pick weights w/o
   overfitting the 244 queries — held-out split or k-fold).*
2. **768-dim vs 256-dim** dense re-run — isolate the truncation recall loss.
3. Decouple dense chunk size; verify nomic task prefixes; stronger model.

**Phase 2/3 implication:** the matcher uses embeddings for *similarity*, not
ranking-vs-FTS, so the ranking loss doesn't directly doom it — but the ~15%
recall miss is a yellow flag (the matcher could miss ~1-in-7 real overlaps).
Worth re-checking once the matcher exists.

**When:** the *fix* (weighted fusion) is a separate scoped effort with its own
eval-design decisions, per user. Diagnosis is done; fix is deferred.

---

## OI-2 — Headers-ON retrieval not measured  ·  DEFERRED
*Found: Phase 1a. EVAL.md H1 was run headers-OFF for cost parity with the
C24 baseline. Production default is headers-ON (per-chunk LLM context
header). Unknown whether headers move retrieval quality. `--headers` flag
exists on `score_retrieval.py`; costs LLM calls. Run when comparing to the
true production config.*

---

## OI-4 — Held-out extraction eval (AMI)  ·  DEFERRED
*Decided: 2026-06-08. Phase 1b was scoped as "AMI → extraction F1" but
deferred after investigation:*
- *No clean drop-in gold: HF `knkarthick/AMI` and `gcunhase/AMICorpusXML`
  both give a single combined summary blob (anonymized speakers). Typed
  DECISIONS/ACTIONS gold requires parsing AMI's raw NITE manual XML.*
- *Structural mismatch (the real blocker): AMI decisions/actions are
  abstractive, consolidated, non-turn-anchored summary sentences; our
  extractor emits granular, turn-anchored, 5-type obligations. A
  precision-F1 would be low by construction (same granularity mismatch as
  EVAL.md C4/C13, worse) — measures gold-shape, not extraction quality.
  No dataset swap fixes this (ICSI/ELITR are abstractive too).*

*If revived: the only defensible metric is **type-agnostic obligation
recall** ("does the extractor surface content matching each human-flagged
decision/action?"), which dodges the precision artifact and answers the
Phase-3 gate ("is extraction good enough to feed the matcher?"). ~half a
day of XML work. Extraction is already measured in-sample (Codex gold,
EVAL.md C13: entity F1 0.62, type-agnostic obligation 0.26).*

---

## OI-3 — Cross-meeting / corpus-wide retrieval unmeasured  ·  DEFERRED
*The headline gap: all retrieval numbers so far are per-meeting-scoped
(rank within the correct transcript). Production `/search` retrieves across
all visible meetings — the "find the right meeting among 20+" discrimination
is untested. QMSum has **no gold** for this (queries are per-meeting, no
cross-meeting/negative labels), so a QMSum proxy would be contaminated.
Correct instrument = the **Phase 3 planted-needle corpus** (authored
cross-meeting gold). Do it there, not as a Phase-1 hack.*

---

## OI-7 — Entity-resolution over-merge ("black-hole" entities)  ·  RESOLVED (2026-06-11)
*Found 2026-06-09 (debugging Connections); root cause confirmed + fix shipped
2026-06-11 on `fix/entity-resolution-overmerge` (7 commits). Full record +
before/after numbers in `transcripts/EVAL.md` (record E1, "Outcome"). Validation:
re-ingesting the exact 14 cohort fixtures that caused the black holes now yields a
clean surface distribution (max 4 surfaces, **0 black holes**; was 94/75/52/46),
with entity F1 0.59 (≥ 0.55 floor) and obligation type-agnostic 0.27 (≥ 0.21) held.
Connections re-run on the clean layer is the follow-up.*

**Evidence (real cohort DB):** a few entities have absorbed hundreds of
unrelated mentions —
- `DStack` = **94 distinct surface forms / 406 mentions** (swallowed
  `hermes`, `ethereum`, `chatgpt`, `claude`, `github`, …)
- `CBM` = 75 surfaces · `Dstack` = 52 · `Jupyter Notebook` = 46
- everything else is a normal **2–3** surfaces → a sharp cliff = a real bug,
  not just messy data.

**Why it matters:** in retrieve-rerank terms the **entity index is corrupt**, so
the Connections matcher (Stage 1+2, which is itself correct/done) builds
candidates on garbage — no reranker can fix it. Same corruption pollutes
search results and the graph.

**CONFIRMED root cause (2026-06-11): degenerate short-text embeddings → blind
auto-merge.** The embedder (`nomic-embed-text:v1.5` via Ollama) returns a
**near-constant vector for ultra-short inputs**, so bare entity names collapse
onto a single point. Evidence (real cohort DB + live embedder):
- `embed("DStack") == embed("Benchling") == embed("ChatGPT")` are **byte-identical**
  (cosine 1.0000); full sentences embed fine (cos ~0.53). Collapse scales with
  length: 1 token → 1.000, 2 → 0.882, 5–6 → 0.55–0.79 (the fixed
  `"search_document: "` prefix dominates a 1-token input).
- **80 / 225 stored entity vectors are mutually identical** (cos > 0.999) — all
  single-token names; the 3 single-token black holes are one vector
  (`DStack ≡ CBM ≡ Dstack`).
- cosine ≈ 1.0 trips `resolve_entity`'s **auto-merge band (`sim > 0.90`)**, which
  **never calls the LLM** → every short non-person name is absorbed into whichever
  entity sits at the collapse point for its type (→ one black hole per non-person
  type). Replaying `_llm_tiebreak` returns `same=False` on the swallowed pairs —
  the LLM is correct, it just never runs.
- **Natural control:** ~70 person names also collapse, yet every person entity is
  clean (1 surface) — persons use the exact-match path (`entity_resolution.py:88–94`),
  not embeddings. ⇒ bug = (short-name embedding collapse) × (non-person cosine
  auto-merge). **Retrieval/search is fine** (long-text chunk/obligation embeddings
  are healthy); corruption is contained to the entity layer.

The earlier "threshold / upsert bug" guess is wrong: 0.90 is never reached by real
name geometry, and the LLM tiebreak is accurate. The lever is NOT the threshold or
the prompt.

**Fix (in progress, `fix/entity-resolution-overmerge`):**
1. **Eval blind spots first** — add an embedder-health signal, an over-merge
   guardrail metric, and a de-mocked real-embedder resolution test (the prior
   signals all missed this: bake-off scores extraction-per-transcript not
   cross-session resolution; the resolution unit tests mock the embedder with
   synthetic vectors).
2. **Resolver fix** — lexical-first gate (normalize + edit-distance / shared-token /
   phonetic) for non-person merges; demote bare-name cosine auto-merge; route
   genuine decisions through the LLM tiebreak. Grounded in `METHODOLOGY_SURVEY.md`
   D12 (`open`, trigger "dedup quality drops below acceptable" — now fired) + O3,
   and `v1_improvements.md §6`.
3. **Re-ingest** cohort → surface-count cliff restored → **then re-run Connections**.

The full editable-entities + ledger system (`ENTITY-CANON.md`) remains the
longer-term layer, not this fix.

---

## OI-8 — TEE-compatible embedding service  ·  OPEN
*Raised: 2026-06-11 (while fixing OI-7). Separate from the OI-7 fix — do NOT fold in.*

The team plans to move everything into a TEE, where local **Ollama may not be
feasible**. Backend reality today (verified in `config.py` + `transcripts/embed.py`):
- **LLM is already TEE-served** — `config.get_llm` defaults to `redpill`
  (`google/gemma-3-27b-it` on Phala RedPill TEE; `nearai`/DeepSeek alt). Ollama
  (`qwen2.5-conclave`) is dev-only. No TEE work needed for the LLM.
- **Embeddings are the ONLY hard Ollama dependency** — `transcripts/embed.py` always
  posts to Ollama `/api/embed` with `nomic-embed-text:v1.5`, regardless of
  `CONCLAVE_LLM_BACKEND`. (`config.embedding_model = "all-MiniLM-L6-v2"` is stale /
  unused — embed.py hardcodes nomic; stored vectors confirm nomic.)

**Scope when prioritized:** pick a TEE-compatible embedder — (a) a small embedding
model running *inside* the enclave (nomic-embed is ~137M; doable without Ollama via a
minimal runtime/ONNX), or (b) a TEE-hosted `/embeddings` endpoint (RedPill is
OpenAI-compatible). The embedder is **model-keyed + swappable** (`EMBED_MODEL_ID` one
constant; `embeddings` table namespaces by `model_id`), so the swap is a contained
change + a re-embed. The OI-7 fix **de-risks this** — resolution becomes lexical-first
+ LLM-tiebreak, so the embedder is no longer the arbiter of entity identity, and the
remaining embeddings (chunk retrieval + entity definitions) work on any decent
sentence-embedder.

---

## OI-6 — Connections Stage-2 LLM: live vs batch placement  ·  DEFERRED
*Raised: 2026-06-08 (Phase 3 v1, `companion/connect_reason.py`).*

The connection-judge LLM (`config.get_llm`, in-TEE RedPill) is the precision
layer over the Stage-1 graph. **It is an LLM, and Conclave's core thesis is
"no LLM on the query path — operator can't read your data."** v1 runs it
OFFLINE (the `collab_review.py` runner), so the live query path stays
pure-SQL and the thesis holds. Productionizing requires a decision:

- **Batch / nightly enrichment (recommended):** judge offline, write validated
  suggestions back to the DB; live path just reads them → query path stays
  LLM-free, operator-blind claim intact.
- **Live in-TEE at query time:** fresher, still in-TEE, but puts an LLM on the
  live query path (weakens the "pure-SQL query path" story).

**Resolve before productionizing.** Until then, keep Stage-2 invocation
offline/batch only.
