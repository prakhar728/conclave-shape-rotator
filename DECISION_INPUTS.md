# Decision Inputs — What We Need to Know Before Architecture Lock

> **Purpose:** the surveys in `METHODOLOGY_SURVEY.md` give us a menu of methodologies. We can't choose between them without empirical knowledge of our corpus, our cohort, our LLM behavior, and our users. This doc enumerates the information needed, why each piece matters, how to obtain it, and how decisions unlock each other.
>
> **Date:** 2026-05-28. **Branch:** `transcripts-phase1`.
> **Read order:** §I (priority/sequence) → categories A-H. Each category lists information needed, why it matters, how to find out, effort estimate. Categories ordered by how much they unlock.
>
> Companion to `METHODOLOGY_SURVEY.md` (what's possible), `BUILD_PLAN.md` (strategy), `IMPLEMENTATION_PLAN.md` (execution). This doc is the *empirical audit* — the data without which the surveys are just menus.

---

## I. Priority sequence — what unlocks what

```
A (data audit)  ─┬──►  D (LLM capability)  ──►  E (schema validation)  ──►  D13, D14, T1, T2
                 │                              │
                 │                              └──►  T3, T4
                 │
                 ├──►  chunking decisions (D1, D2, D3 sizing)
                 │
B (roster)  ─────┴──►  D11 confidence + ground-truth owner labels

C (user interviews)  ──►  reframes everything — DO FIRST IF POSSIBLE

G (ops constraints)  ──►  bounds D5, D8 (mostly back-of-envelope)

F (corpus stats)  ──►  validates D6, D9 — but only AFTER extraction runs

H (annotation logistics)  ──►  gates A, D, E from being done at all
```

**Cheapest, most-unlocking sequence:**

1. **A + B in one afternoon** (Python scripts, no LLM). Settles ~6 architecture decisions immediately.
2. **C user interviews (2-3 cohort members)** in parallel. Reframes everything else if needed — **highest-risk skip.**
3. **H annotation plan** in parallel (~2 hours).
4. **D + E together** as the §3 step 1+2 experiment in `METHODOLOGY_SURVEY.md`.
5. **F** falls out of the first full extraction run; defer measurement.

**A, B, G are free wins** — measurable today, lock 8+ decisions immediately.

**C is the highest-risk skip.** Without it, we might build a beautifully-architected system that doesn't answer the questions users care about.

D, E, F are sequenced — each depends on the previous.

---

## A. Data characterization — what's actually IN our 13 transcripts

Without this, every chunking/extraction parameter is a guess.

| # | Question | Why it matters | How to find out | Effort |
|---|---|---|---|---|
| A1 | Token length distribution per transcript (min/median/p95/max) | Chunking strategy (D1): do most transcripts fit in one chunk? How often is map-reduce needed? | Python script over `external/shape-rotator-os/apps/os/src/content/context/raw-scripts/*.txt`; token-count with tiktoken or chars × 0.25 | 30 min |
| A2 | Turn length distribution (median, max, p95, count of turns >budget) | Does the "20-min monologue" edge case (D2) actually exist? How often? | Same script | 30 min |
| A3 | Turn count per transcript | Sanity check: how many extraction units per transcript? | Same script | 30 min |
| A4 | Speaker count per transcript | Affects entity resolution complexity + future permission model | Same script | 30 min |
| A5 | Speaker label type distribution (% real names / % parenthetical / % `Speaker N`) | Drives identity-resolution coverage expectations (D11); reveals how much identity work is even possible | Same script | 30 min |
| A6 | Meeting type distribution (intro, workshop, 1-on-1, panel) | Different shapes likely need different extraction prompts; affects T1 (single vs per-type) and the open question of whether short intros are worth extracting | Visual inspection + filename heuristics + sample-read | 1 hr |
| A7 | BOM / encoding issues count | Pre-parse cleanup scope | Same script | 30 min |
| A8 | Substantive content vs filler density | Are short intros worth extracting? (open §7.4) | Manual read of 3-4 transcripts | 1 hr |

**Output:** a `data_audit.md` or `data_audit.json` with histograms.
**Decides:** D1, D2, D3 chunk sizing; reveals whether T1's bake-off is feasible; sets expectation for entity resolution coverage.

---

## B. Cohort roster reality — what's actually IN cohort-data

Without this, entity resolution design (D11, D12) is theoretical.

| # | Question | Why | How | Effort |
|---|---|---|---|---|
| B1 | Total roster size | Sanity-check the ~50 people claim | `ls cohort-data/people/*.md` + frontmatter parse | 15 min |
| B2 | Naming variants per member (formal/nick/aliases) | Drives `_normalize_name` and alias-lookup logic in identity.py | Frontmatter inspection + grep for known nicks in transcripts | 1 hr |
| B3 | Speaker-to-roster match rate on 13 transcripts | Tells us actual coverage of the mock-identity approach | Match script | 1 hr |
| B4 | Speakers NOT in roster (guests, drop-ins, mis-spellings) | Long-tail size; need separate path? | Same script | 30 min |
| B5 | Roster freshness vs speakers actually appearing | Are we matching against the right snapshot? | Same script + spot-check | 30 min |

**Output:** roster audit summary.
**Decides:** D11 (roster-first feasibility); unlocks T2 ground truth (need known speakers for owner-resolution scoring).

---

## C. Query / use case reality — what users actually want

The only category requiring going outside engineering. The hardest to skip and the most-likely-to-invalidate-architecture if skipped.

| # | Question | Why | How | Effort |
|---|---|---|---|---|
| C1 | What questions would a cohort member actually ask their transcripts? | Drives §9.3 retrieval pattern set; reveals if proposed schema matches user intent | 5 user interviews with cohort members (or 2-3 if pressed) | 3-5 hrs total |
| C2 | What does "useful meeting prep for X" look like CONCRETELY? | Defines the success metric; concretizes the killer use case | Same interviews | (included) |
| C3 | Who is the user — member, organizer, both? | Affects permission design (1.5) and surface choice | Same interviews | (included) |
| C4 | Output format expectations (dashboard? Slack? email brief?) | Affects Phase 1d dashboard scope + API design | Same interviews | (included) |
| C5 | Freshness expectation (real-time / daily batch / on-demand) | Reaffirms or invalidates assumption A2 (offline/batch) | Same interviews | (included) |
| C6 | Consequence of missed action item vs false positive | Drives precision/recall tradeoff for extraction prompts | Same interviews | (included) |
| C7 | Top-5 most-wanted views (rank-order) | Prioritizes which §9.3 retrieval patterns to ship first | Same interviews | (included) |
| C8 | Do they care about "what was discussed" vs "what was decided/committed"? | If only the latter, simpler schema; if both, our 5-type design is justified | Same interviews | (included) |

**Output:** user interview notes.
**Decides:** D13 finality; reframes T1/T4 if user-facing metrics differ from internal F1; potentially invalidates §9.3 retrieval set if real queries differ.
**Risk if skipped:** building a beautifully-architected system that doesn't answer the questions users care about.

---

## D. LLM capability on OUR data — not on benchmark data

The literature tells us nothing about how qwen2.5:14b or NearAI's default behaves on OUR transcripts. Must measure.

| # | Question | Why | How | Effort |
|---|---|---|---|---|
| D1-cap | F1 of qwen2.5:14b vs hand-coded GT on action / decision / commitment / question / blocker | Baseline for all extraction decisions | §3 step 1+2 of METHODOLOGY_SURVEY | 1 day |
| D2-cap | F1 of NearAI default model on same eval | Cost-vs-quality tradeoff per backend | Same eval, swap backend | 1 hr (eval) + credit cost |
| D3-cap | Owner-resolution accuracy specifically | Settles T2 component and §7.4 open question on implicit assignment | Same eval, separate metric | included |
| D4-cap | JSON output reliability per backend (raw-parse rate, repair-success rate, total failure rate) | Drives `llm.py` retry/timeout strategy and per-backend budget | Run extraction 100× on 10 chunks, count failures by category | 2 hrs |
| D5-cap | Hedging false-positive rate ("we could maybe…", "I might…") | §7.4 open question; drives prompt design | Same eval, add false-positive metric per source quote | included |
| D6-cap | Entity hallucination rate (invented projects, mis-attributed quotes) | Drives entity-resolution confidence threshold and Mem0 conflict policy | Same eval, manual spot-check of entities not in source | 1 hr |
| D7-cap | Latency per chunk per backend (p50, p95) | Operational planning + batch sizing + dashboard UX expectations | Time the eval runs | included |
| D8-cap | Cost per transcript on NearAI (median, p95) | Budget for cohort run — the current $15 cap was hit on minimal work | Token count × pricing | 30 min |
| D9-cap | Effective context window of qwen2.5:14b at full `num_ctx` | Sanity-check D1 chunk budget — does qwen actually use 8k well or degrade? | "Needle in haystack" test: insert known sentence at varying depths, ask qwen to find it | 2 hrs |
| D10-cap | Embedding quality of nomic-embed-text on transcript text | Drives D8 confidence; potential A/B against bge-small | Small eval: top-k retrieval on 20 hand-labeled queries | 4 hrs |

**Output:** capability report (`capability_audit.md`).
**Decides:** D14 (single vs per-type prompts) via T1; confirms or rejects D8; gives concrete numbers for D10 (conflict-resolution feasibility at meeting batch sizes); informs T3 (reranker need).

---

## E. Schema-shape unknowns — require ground truth from D

Each needs the hand-coded ground truth to answer. Bundled with D temporally.

| # | Question | Why | How |
|---|---|---|---|
| E1 | Action vs Decision vs Commitment annotator agreement (%) | T2 — settles D13 (5 tables vs 1 with `type` enum). Threshold: >80% keep distinct, <80% collapse | Two-annotator coding of 50 items |
| E2 | Open Question frequency per transcript | Decides if it's first-class extractable or rare-edge | Count in GT set |
| E3 | Blocker frequency per transcript | Same | Same |
| E4 | Implicit-owner rate (action items with no clear assignee) | Drives `owner_evidence` enum design and per-evidence-type prompt tuning | Count in GT set |
| E5 | Empty/hedged action rate (over-extraction) | Drives prompt tuning for hedging filter; sets expectation for false-positive rate | Count in GT set |
| E6 | Cross-type confusion (item labeled both "decision" and "commitment" by different annotators) | Reveals which types are blurry vs sharp | Confusion matrix from agreement data |

**Output:** schema validation table.
**Decides:** T2 (settles D13); resolves several §7.4 open questions; informs final prompt design.

---

## F. Cross-meeting connection reality

Requires extraction to have run across all 13 transcripts. Premature to measure now, but plan the measurement.

| # | Question | Why | How |
|---|---|---|---|
| F1 | Average entities-per-transcript | Sanity-check graph size projections | Aggregate after first full extraction pass |
| F2 | % of entities appearing in N>1 transcripts (cross-meeting recurrence rate) | THE CORE PREMISE OF CONNECTION-FINDING. If this is low, the entire product thesis is wrong | Aggregate after extraction |
| F3 | Average follow-up density (action item raised in T1, resolved/discussed in T2) | Validates bi-temporal facts (D9) and meeting-prep use case | Manual coding or LLM judgment over GT set + 5 more transcripts |
| F4 | Edge density per entity (entity → entity co-occurrence graph) | Drives graph-walk strategy + when to index | Aggregate after extraction |
| F5 | Distribution of meeting types over time (do projects show up repeatedly?) | Connection-finding only valuable if projects/topics persist | Visual analysis of A6 over date dimension |

**Output:** corpus stats after first full extraction pass.
**Decides:** validates D6 (graph layer) and D9 (bi-temporal) design.
**Critical:** **if F2 is low (<30% of entities recur), the connection-finding premise is wrong and the architecture should pivot to a per-meeting tool.** Measure this before investing heavily in graph layer.

---

## G. Operational constraints

Mostly knowable from infra docs or asking. Should be documented for future reference.

| # | Question | Why | How |
|---|---|---|---|
| G1 | Phala CVM memory / CPU / storage limits | Bounds embedding model size + DB growth ceiling | Phala docs / ops contact |
| G2 | Network egress policy (NearAI allowed? strictly local?) | Affects backend choice and disaster planning | Ops contact |
| G3 | SQLite DB projected size at 100 / 1000 transcripts | Capacity planning | Estimate: chunks (n) × stores (4) × dim (768) × float32 + relational overhead |
| G4 | Backup / data-loss tolerance | Affects ingest idempotency requirements + raw-write-once policy | Ops contact |
| G5 | LLM cost ceiling per cohort run | The $15 NearAI cap was already hit. What's the actual budget? | Ask user |
| G6 | Ollama startup time on Apple Silicon (M-series) at our chosen `num_ctx` | Dev loop latency | Time it |
| G7 | Per-backend `num_ctx` truncation behavior | Ollama silently truncates; need to know thresholds for safety | Test with known oversized input |

**Output:** ops constraints sheet.
**Decides:** bounds D5 (vector store size); bounds D8 (embedding model size choice); informs G5 budget-driven decisions about NearAI vs Ollama for production runs.

---

## H. Annotation logistics

Settles whether the experiments in §3 of METHODOLOGY_SURVEY are even feasible at the right quality.

| # | Question | Why | How |
|---|---|---|---|
| H1 | Who hand-codes the ground truth? | Resource availability gates everything in D, E, F | Decide |
| H2 | Time to code one full transcript thoroughly | Budget the eval set | Try one yourself, time it |
| H3 | Annotation guidelines doc | Reduces inter-annotator noise; pre-defines "what IS an action item" | Write before two-coder phase |
| H4 | Methodology for agreement (Cohen's kappa vs % agreement) | Statistical legitimacy of T2 result | Pick before coding |
| H5 | Coverage — is 3 of 13 enough for the eval set? | Eval set representativeness | Stratify: 1 intro, 1 workshop, 1 1-on-1; spot-check |
| H6 | Re-coding cadence (how often does GT need refresh?) | Long-term eval-set maintenance | Decide policy |

**Output:** annotation plan + guidelines doc.
**Unblocks:** D, E, F experiments at credible quality.

---

## II. What this doc deliberately doesn't ask

Things we are NOT investigating now (in scope but premature, or genuinely out of scope):

- **Embedding-model A/B beyond D10-cap.** A single primary (nomic) is enough; sophisticated bake-off is a Phase 2 question.
- **Multi-tenant scaling.** Phase 1 is one cohort.
- **Latency SLOs.** Batch pipeline — no real-time SLO yet.
- **Voiceprint identity.** Out of scope per BUILD_PLAN A3.
- **Privacy/legal review.** Consent assumed (A1); legal review is its own track.
- **GraphRAG community detection at our scale.** Already decided to skip (D17).

---

## III. The single number that would change the most decisions

**F2 — cross-meeting entity recurrence rate.**

If, on our 13 real transcripts, fewer than ~30% of named entities (people excluded, since they always recur) appear in 2+ transcripts, the entire "connection-finding" premise is shaky. Projects, topics, and decisions must demonstrably persist across the corpus for the graph layer and meeting-prep features to deliver. We can't measure F2 until we have extraction running, but we can do a quick *manual* approximation today: visually scan 5 transcripts, list the projects/topics/technologies mentioned, count overlaps. If overlap is sparse → architecture pivots to per-meeting tool + simple search.

Add this as a pre-extraction sanity check. ~1 hour of manual work, could save weeks of misdirected architecture.

---

## IV. Recommended immediate next moves

In order of cost (cheapest first):

1. **Hour 1 — F2 manual approximation.** Scan 5 transcripts. List entities. Count overlap. If overlap density is convincing, proceed; if not, raise it as a serious product question.
2. **Hour 2 — A + B Python scripts.** Histograms, roster match rate. Lock 6+ chunking/identity decisions.
3. **Day 1 — H annotation plan + guidelines doc.** Then code one transcript yourself to time it.
4. **Day 2 — C interviews booked.** In parallel with engineering work.
5. **Day 2-3 — D + E experiments** (per METHODOLOGY_SURVEY §3 steps 1+2). Settles T1, T2, several open questions.
6. **G + ops** as background fact-finding throughout.

After steps 1-5, the open tensions in METHODOLOGY_SURVEY (T1-T4) should be empirically resolved. Architecture can lock; build proceeds.
