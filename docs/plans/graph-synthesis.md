# Part 2 — Graph Synthesis (the KB layer)

> Status: DESIGN (no code yet). To be built in a SEPARATE worktree cut from
> `feat/transcript-refine`. This is the analog of `transcript-refine.md` (Part 1).
> Part 1 = ground-truth capture; **Part 2 = turning that ground truth into a graph.**

## 1. Context
Part 1 produces a **human-approved, corrected transcript (`v2`)** plus a **per-user
vocab** of confirmed entities + types. Part 2 consumes those as **high-precision
priors** and builds the knowledge graph: entity nodes + typed **edges** + collab
signals — with the LLM no longer guessing entities the human already confirmed.

Today's KB (`kb_extract` → `entity_resolution` → `kb_graph`) is LLM-only, produces
entity *nodes* + *mentions* + *obligations* but **no entity↔entity edges** (the
`facts` table exists, migration `0007`, with **no write path**), and ignores the
human corrections. Part 2 fixes all three.

## 2. The contract — what Part 2 consumes (pinned by `tests/test_part2_contract.py`)
```python
from transcripts import store, vocab

store.load_v2(session_id) -> TranscriptV2 | None      # consume ONLY when .status == "approved"
   TranscriptV2 { session_id, status, approved_at,
                  segments:    [V2Segment{ segment_id, speaker_label, speaker_name, tokens[] }],
                  annotations: [CandidateAnnotation{ span{segment_id,token_start,token_end},
                                                     surface, state, type, source, confidence }] }

store.v2_segments_or_raw(session_id) -> [{speaker, text}]   # corrected segments (already feeds index_session)

vocab.get(user_id, surface)      -> VocabEntry | None
vocab.list_for_user(user_id)     -> [VocabEntry{ surface_norm, is_entity, type, canonical_id, provenance }]
```
**Semantic contract:**
- annotation `source="user"` + a `type` → **ground-truth entity** (trust it; don't re-derive).
- annotation `state="known"` → vocab-confirmed; `candidate`/`oov` → hints only.
- the per-user `vocab` is the **extraction prior** (known surfaces + types).
- **trigger:** `approve_and_build(session_id)` (Part 1) → `_build_kb` → `index_session`
  (already reads corrected v2) + `extract_session`. Part 2 plugs into `extract_session`.

If any of these shapes must change, update Part 2 + the C9 drift-guard together.

## 3. Scope — what Part 2 owns
1. **Entity extraction seeded by ground truth.** Feed the confirmed annotations +
   vocab into extraction/resolution so user-confirmed entities are authoritative
   and the LLM focuses on what's *not* tagged.
2. **The edges/`facts` write-path.** Build the entity↔entity relationship layer
   (the `facts` table has schema but no inserts). This is the biggest net-new.
3. **Collab signals.** "Who should talk to whom." Per the harvested findings
   (this branch: `transcripts/EVAL.md` §H2 + `scripts/eval/OPEN_ITEMS.md` OI-6):
   the lever is the **Stage-1 graph** (the judge can't manufacture matches the
   graph never surfaced); run the **Stage-2 LLM judge as batch/nightly
   enrichment, NOT on the live query path** (operator-blind thesis).
4. **Editable graph** (the ENTITY-CANON correction UI) + **workspace permissions**
   — later sub-phases.

## 4. What to reuse (existing code on this branch)
- `transcripts/kb_extract.py` — `extract_session` / `_run`: extract → merge →
  `resolve_entity` → importance → upsert. **The integration point** (make it
  consume v2 annotations + vocab).
- `transcripts/extract.py` — `extract_from_chunk` (per-chunk LLM extraction).
- `transcripts/entity_resolution.py` — `resolve_entity` (lexical-first +
  definition-embedding + LLM tiebreak; the OI-7 over-merge fix — keep it).
- `storage/kb_graph.py` — entity/obligation CRUD, `entities_for_er`, `category_of`,
  `save_source_embedding`. **Add `insert_fact` here** (the missing edge write-path).
- `alembic/versions/0007_entities_facts_obligations.py` — the `facts` table schema.
- `companion/personal_agent.py` — the read-only KB lens (entities/obligations/search).
- Harvested collab findings: `transcripts/EVAL.md` §H2, `OPEN_ITEMS.md` OI-6.
- Upstream/related: `CONCLAVE-CAPTURE-ARCHITECTURE.md` (capture), `ENTITY-CANON.md`
  (the self-cleaning canon/ledger — Part 2's editable-graph north star).

## 5. Open decisions (resolve early)
1. How exactly do confirmed annotations seed extraction — pre-insert as entities,
   or pass as a prior/allow-list to `extract_from_chunk`/`resolve_entity`?
2. `facts` extraction: LLM relation-extraction pass vs. derive from co-occurrence +
   confirmed types. (Note today's graph computes co-occurrence at read time.)
3. Collab Stage-1 tightening (the need↔entity link) — the actual quality lever.
4. Workspace-vs-per-user graph scope (Part 1 deferred this; see
   `transcript-refine.md` §12 + the global-entities-table reality).

## 6. Build increments (rough — decompose to sub-commit gates before building)
- **P2.1** consume v2: `extract_session` reads the approved v2's confirmed
  annotations + vocab as priors; user-typed entities become authoritative nodes.
- **P2.2** `facts` write-path: `kb_graph.insert_fact` + a relation pass; bi-temporal
  upsert per the 0007 schema.
- **P2.3** collab: tighten Stage-1; wire Stage-2 judge as batch enrichment.
- **P2.4** editable graph (ENTITY-CANON) + workspace permissions.
Each test-gated in the canonical venv (`personal/conclave/.venv`), same discipline
as Part 1.

## 7. Mechanics for the new worktree
- **Branch from** `feat/transcript-refine` (needs the v2/vocab models + seams),
  cut from the commit that has `test_part2_contract.py` (the pinned contract).
- **Disjoint file surfaces** keep the eventual merge clean: Part 1 owns
  transcript/editor/vocab (`store.py` v2 seams, `candidate.py`, `vocab.py`,
  `transcripts_routes` v2/approve); Part 2 owns `kb_extract.py`,
  `entity_resolution.py`, `kb_graph.py`, `facts`, `companion/` collab.
- **Never merge to `main`** until the full gate passes AND the user approves.
- Run the C9 drift-guard (`tests/test_part2_contract.py`) as a standing check —
  if it goes red, Part 1's contract moved; reconcile before continuing.
