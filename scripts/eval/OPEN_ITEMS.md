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

## OI-7 — Entity-resolution over-merge ("black-hole" entities)  ·  OPEN — TOP BLOCKER
*Found: 2026-06-09 while debugging Connections (feat/connections). This is
currently the #1 thing on the table — it gates connections AND search AND the
graph (everything that reads entities).*

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

**Likely root cause:** `transcripts/entity_resolution.py` / the upsert path is
**over-merging** unrelated mentions into a few magnets (a threshold / upsert
bug), despite the codebase's stated "conservative, false-merges-unrecoverable"
philosophy. A `DStack`-named entity should never have `hermes` as a surface.

**Plan (agreed):**
1. **Diagnose** the root cause — read `entity_resolution.py` + upsert; trace how
   `DStack` accumulated 406 mentions / 94 surfaces. Contained, read-only-ish.
2. **Fix on its OWN branch off `main`** (e.g. `fix/entity-resolution-overmerge`)
   — NOT on `feat/connections`; the fix is broadly useful and must merge
   independently, not be trapped behind the held connections feature.
3. **Merge → then re-run Connections** (rebase feat/connections on fixed main)
   to confirm the downstream improvement.

The cheap root-cause fix comes FIRST; the full editable-entities + ledger
system (`ENTITY-CANON.md`) is the longer-term layer, not the first move.
