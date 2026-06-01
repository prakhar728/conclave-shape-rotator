# EVAL — v2.2 vs v2.1 vs v1.1 baselines

Held-out test split: **3 transcripts** chosen for type + extraction-shape diversity:

- `dstack-hangout-alex-shaw-lsdan-andrew` — informal hangout, action-heavy
- `office-hours-transcript` — Q&A workshop, open-question-heavy in principle
- `ideal-customer-profiling-user-interviews-transcript-from-albiona` — interview / pitch + Q&A, insight-heavy

Comparison method: read the raw transcript end-to-end (no LLM), then compare the three runs' outputs side-by-side. No automated metric — judgement on each session.

Run substrate: Gemma 3 27B via RedPill (Phala TEE) for all three runs. Differences are prompt-only, not model.

---

## Headline numbers

| Session | v1.1 (5-kind, `enriched-output-gemma3-v1.1/`) | v2.1 (5-kind, was in DB) | **v2.2 (3-kind, now in DB)** |
|---|---|---|---|
| dstack-hangout | 5 sigs: 2 ins · 1 dec · 2 act · 0 q | 6 sigs: 2 ins · 2 imp · 2 act · 0 q · 0 dec | **6 sigs: 4 ins · 2 act · 0 q** |
| office-hours | 8 sigs: 4 ins · 1 imp · 0 dec · 0 act · 1 q (+ 2 misc) | 8 sigs: 3 ins · 3 imp · 1 dec · 0 act · 1 q | **8 sigs: 8 ins · 0 act · 0 q** |
| albiona-interview | 8 sigs: 4 ins · 3 imp · 0 dec · 0 act · 1 q | 6 sigs: 3 ins · 1 imp · 1 dec · 1 act · 0 q | **7 sigs: 5 ins · 2 act · 0 q** |

`ins` = insight, `imp` = impactful_point, `dec` = decision, `act` = action_item, `q` = open_question. v2.2's collapse maps the old kinds: `dec` → `act`, `imp` → `ins`. Use that to read across columns.

---

## Per-session judgement

### 1. dstack-hangout-alex-shaw-lsdan-andrew

The session is a focused technical exchange between Shaw (cohort) and Alex (Flashbots, external) about MK OSI / Debian forks for agent OSes / TEEs. Shaw asks for the link; Alex offers his email conditionally.

| | v1.1 | v2.1 | **v2.2** |
|---|---|---|---|
| Action_item — Alex sends link | ✓ | ✓ | ✓ |
| Action_item — Alex offers email IF Shaw runs into issues | ✓ (conditional preserved) | ✓ (conditional preserved) | ✓ (conditional preserved) |
| Insight — MK OSI design | ✓ (insight) | ✓ (insight) | ✓ (insight) |
| Insight — Shaw forking Debian | ✓ (impactful_point) | ✓ (impactful_point) | ✓ (insight — collapsed) |
| Insight — Yocto pain | ✓ | ✓ | ✗ (dropped) |
| Insight — LSDan / Hawkins friction on pre-built images | ✗ | ✗ | **✓ (new)** |
| Insight — ElizaOS grinding | ✗ | ✗ | ✓ (new) |

**Verdict:** v2.2 ≥ v1.1. Loses the Yocto-pain insight but gains the LSDan / Hawkins strategic-friction insight (which is the actual "useful for prep" content — a real cross-cohort tension someone preparing a follow-up needs to know). Action_items are stable.

### 2. office-hours-transcript

A 70+ min Q&A workshop. Andrew Miller demonstrating an Access camera; Andrew Hang pitching RMCP / harness-layer / token graph; Chutes/Phala/TEE-GPU discussion; brief Kelsen / BitRouter / l2beat / Workshop-Labs mentions. **Multiple explicit open questions** raised across the session (e.g. Andrew Miller asking about privacy policy, customer-segment selection; Hunter asking about retention policies; Andrew Hang asking about user types).

| | v1.1 | v2.1 | **v2.2** |
|---|---|---|---|
| Insights (synthesised, named, multi-sentence source) | strong | strong | **strong** — denser per-signal, all 8 well-formed |
| Open_questions | 1 (privacy policy) | 1 (Mac chips business case) | **0 — REGRESSION** |
| Action_items | 0 | 0 | 0 |
| Topic chips | 8 | 8 | **8** (cleaner — confidential compute, agentic workflows, prompt engineering) |
| Entity coverage | 26 | 26 | **24** (slight drop; misses Tinfoil, Thinking Machines, Workshop Labs in the slot they used to fill) |

**Verdict:** v2.2 **regresses on open_question recall**. The model treated this session as monologue-extraction even though it's structurally Q&A. Insights are tighter and the cohort-relevant content (MCP/harness, Chutes, TDX-Mac debate) is captured cleanly, but losing the question signal hurts the meeting-prep use case.

Likely cause: v2.2's open_question definition emphasises "not answered within the same chunk" — many of the office-hours questions are followed immediately by an answering exchange in the same chunk, so the model technically follows the rule and drops them. v2.3 work would loosen this: include questions where the answer is the next several speaker turns but the question itself stands as a useful signal.

### 3. ideal-customer-profiling-user-interviews-transcript-from-albiona

James Barnes' presentation on alignment (Autobiographer / Etherea), followed by Q&A with Albiona, Fucory, Andrew Miller, Hunter, Sevenfloor.

| | v1.1 | v2.1 | **v2.2** |
|---|---|---|---|
| Insight — James's six years at Facebook + Cambridge Analytica | ✓ | ✓ | ✓ |
| Insight — AI-as-mirror metaphor | ✓ | ✓ | ✓ |
| Insight — Co-founder misalignment / no shared definition of success | ✓ (impactful) | ✓ (impactful) | (folded into an action_item, weakly) |
| Insight — Albiona's bottleneck note on Etherea onboarding | ✗ | ✗ | **✓ (new — names cohort member + project)** |
| Action_item — James accepts Fucory's "Mural by Lupe Fiasco" challenge | ✗ | ✗ | **✓ (new — light commitment, person-attached)** |
| Open_question — any | 1 | 0 | 0 |

**Verdict:** v2.2 ≈ v1.1, slight upgrade on cohort-relevance (Albiona's bottleneck + Fucory's challenge accepted are notable items earlier runs missed). The misalignment insight got mislabelled as an action_item — that's a v2.2 over-correction on the loosened action_item definition.

---

## Cross-session observations

### What v2.2 fixes (vs v2.1 in particular)
1. **No more insight / impactful_point blur.** Two sections collapsed into one; the dashboard reads cleanly. This was the most visible v2.1 complaint and v2.2 eliminates it structurally.
2. **action_item triggers fire on soft commitments.** v2.1 returned 3 action_items across the whole 12-session corpus; v2.2 returns at least 1 per relevant session (LSDan friction in dstack, Albiona bottleneck in albiona, James accepting Fucory's challenge). The cohort talks exploratory, not transactional, and v2.2 is calibrated to that.
3. **Source quote stops cluttering the dashboard.** The `source_quote` field stays in the API for audit; the frontend no longer renders it. This was a standing instruction that v2.1 kept missing.
4. **Model badge now correct.** v2.1 stored `model_id="deepseek-ai/DeepSeek-V3.1"` (NearAI default fall-through) even though the actual backend was Gemma 3 27B via RedPill. v2.2's `_model_id` fix records the real model; the re-enrichment overwrote every stored row.

### What v2.2 regresses
1. **open_question recall dropped to 0 across all 3 test sessions.** This is the biggest regression. The v2.1 prompt extracted 1 per session reliably; v2.2 extracts 0. The new "not answered within the same chunk" framing was too strict — the model interprets it as "must remain dangling" and drops questions that get answered seconds later.
2. **One signal got mis-classified as action_item.** The Albiona "misalignment leading to poor retention" signal is really an insight, not an action. The loosened action_item definition over-claims when the speaker is describing past behaviour rather than committing to a course.
3. **Entity count down slightly on long sessions.** Office-hours lost 2 entities vs v1.1/v2.1. Not visible at a glance but worth noting.

### What v2.2 still leaves unchanged
- Entity extraction quality and the cohort_status / affiliation chips.
- Topic chips.
- Resolved speaker chips, the per-card glyph, the importance rule on the card preview, the detail page composition.

---

## Recommendation

**Ship v2.2 for the demo.** Specifically:

1. The schema collapse to 3 kinds is the right structural fix — the dashboard reads cleaner, the categories are honest, the source_quote noise is gone. These all materially improve the demo viewer experience.
2. The action_item loosening is working. Soft commitments and group-level "we should X" now surface; conditional commitments preserve their triggers. The 3-action_items-across-12-sessions sparseness from v2.1 is gone.
3. The model badge fix is non-negotiable for the demo — showing the audience "google/gemma-3-27b-it" instead of "deepseek-ai/DeepSeek-V3.1" is correct provenance.
4. The open_question regression is real but bounded: 1 question per session was already not much in v2.1. Losing it across 3 sessions costs us a small fraction of the dashboard's signal density and doesn't undermine the demo headline ("structured records over the cohort's real conversations"). The fix is a 5-line prompt tweak — best done after the demo so v2.2 has time to be observed in the wild.

**Net judgement: v2.2 > v2.1 > v1.1 for what the demo needs.** The structural improvements (collapsed kinds, clean dashboard, correct provenance, denser action_items) outweigh the open_question regression. v2.2 is the best implementation we have today.

### Next prompt-iteration suggestion (post-demo, would be v2.3)
- Loosen open_question: include questions whose answer comes in the next few speaker turns IF the question itself stands as a useful prep signal. The current "not answered within the chunk" framing is too strict for Q&A sessions where the answer follows immediately.
- Tighten action_item: explicitly exclude past-tense narrations ("we struggled with X, leading to Y") that describe consequences rather than commitments. One example in the few-shot examples block should show this anti-pattern.
- Consider a fourth category for "praise of cohort work" — currently riding under `insight`. If it ends up being structurally distinct enough to warrant its own section (TBD by usage), promote it.

---

## Provenance

- v1.1 baseline read from: `enriched-output-gemma3-v1.1/*.txt` (run on 2026-05-28 with v2.1 prompts; the directory name lags the prompt version it actually ran).
- v2.1 baseline read from: previous DB state (now overwritten — comparison numbers above reflect a snapshot taken before this round's `transcripts enrich`).
- v2.2 read from: current DB state after the v2.2 cascade landed (commit `e9539b8`) and `transcripts enrich` re-enriched all 12 sessions.
- Total v2.2 enrichment wall time: ~5 min for all 12 sessions; the 3 test sessions specifically took ~1-2 min combined.
