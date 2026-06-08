# Eval — Open Items ("things still left on our plate")

Running backlog for the Conclave evaluation effort. Items are parked here
when found mid-stream so they don't derail the current phase; we pick them
up once the eval scaffold is built out or when a item is explicitly
prioritized. **Surface this list to the user at phase boundaries.**

Status legend: `OPEN` (not started) · `DEFERRED` (intentionally waiting on
something) · `DONE` (resolved, kept for history).

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

**Diagnostics / fixes (cheap → expensive):**
- (a) **Per-query win/loss** dense vs FTS over the 244 queries. Does dense
  win ≥~25%? Decides "keep vs cut." *Cheapest; do this first.*
- (b) **768-dim vs 256-dim** dense re-run — isolates truncation (config fix
  if it jumps).
- (c) **Recall@50 vs NDCG@10** — does dense *miss* relevant chunks or just
  rank them lower? Different problem, different fix.
- (d) **Weighted / tuned RRF** (favor FTS, sweep k).
- (e) **Decouple dense chunk size** from FTS chunk size (smaller embed chunks).
- (f) **Stronger / full-precision embedding model**; re-verify task prefixes.

**When:** after the full eval scaffold is in, or when prioritized.

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
