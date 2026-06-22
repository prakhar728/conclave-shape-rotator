# Test Plan — Part 1: Transcript Refinement (ground-truth capture layer)

> Branch: `feat/transcript-refine` · Spec: `docs/plans/transcript-refine.md` (§1–§15)
> Status of feature: DESIGN, no code yet. This plan is handoff-ready: each test below is implementable mechanically from its row.
> Canonical venv: `personal/conclave/.venv` (needs `sqlite_vec` + `alembic`; **also needs `spacy` + `en_core_web_sm` + `wordfreq` for area 10 — confirmed NOT yet installed, see spaCy infra note**).

## How to read this plan

Every test row carries: **ID · name · level · target file · fixtures/mocks · exact assertions · live-or-mock (+marker) · gold-sensitive?**

Levels: **unit** (pure function, no DB), **store** (real temp SQLite via conftest, no HTTP), **integration** (multi-stage in-process, real store + mocked LLM/spaCy seams), **API** (FastAPI `TestClient`), **frontend** (Vitest/RTL or Playwright), **e2e**.

"Gold-sensitive?" = does the assertion depend on LLM/embedding/spaCy *output quality* (non-deterministic) rather than mechanics? Gold-sensitive tests must be `@pytest.mark.live`/`requires_spacy` or use frozen fixtures; never assert exact LLM/NER content in the default gate.

### Harness conventions to mirror (load-bearing)
- `tests/conftest.py` isolates each test to a temp SQLite DB and runs alembic to head **at import time**. **Any new table/column added by Part 1 MUST ship an alembic migration** or every schema-touching test ERRORs at collection. Single biggest blocking dependency.
- Markers defined: `@pytest.mark.live` (skips w/o `CONCLAVE_NEARAI_API_KEY`), `@pytest.mark.requires_ollama` (auto-skip if Ollama down). **Add a new `requires_spacy` marker.**
- Store-unit → mirror `tests/test_reresolve.py`. API → mirror `tests/test_tag_speaker.py` (`_login`/`_wsid`, FPM stub). Pipeline-gating → mirror `tests/test_kb_extract_pipeline.py` (`ENABLE_KB_PIPELINE`, monkeypatch LLM seams, assert row counts).
- Immutability mechanism: `storage/sqlite.py:save_transcript_session` does `INSERT ... ON CONFLICT(session_id) DO UPDATE SET metadata, derived, updated_at` — `raw_diarization`/`source`/`session_date` are write-once. v2 MUST land so re-save never rewrites `raw_diarization`.

### Proposed new test files
```
tests/test_v2_model.py · test_staged_gate.py · test_ground_truth_writes.py
tests/test_speaker_suggestions.py · test_insights_stale.py · test_trust_state.py
tests/test_per_user_isolation.py · test_cold_start.py · test_part2_contract.py
tests/test_candidate_detection.py   (real spaCy, requires_spacy)
tests/test_candidate_annotation.py  (deterministic fake spaCy — default gate)
tests/test_migrations_v2.py
frontend/__tests__/transcript-editor.test.tsx
```

---

## Area 0 — Migration & schema bedrock (BLOCKING — implement first)
conftest runs alembic to head at import, so the migration must exist before any Part 1 test can be collected.

| ID | name | level | target file | fixtures/mocks | exact assertions |
|----|------|-------|-------------|----------------|------------------|
| M-1 | migration_applies_to_head | store | test_migrations_v2.py | throwaway DB (mirror `test_migrations_kb.py` `alembic_db`) | `upgrade(head)` no raise; new v2 table/col + vocab table + trust-state col exist |
| M-2 | migration_downgrades_clean | store | same | same | `downgrade(-1)` removes exactly the new objects; up/down idempotent |
| M-3 | conftest_head_has_v2_tables | store | same | conftest DB | v2 table + vocab table + trust-state col all exist at head |

> §12 #1/#2 OPEN — assert the *named objects the build introduces* exist; keep names in an `EXPECTED_V2_OBJECTS` constant so tightening is one edit.

---

## Area 1 — `v2` model + draft→approved; raw immutability
| ID | name | level | file | fixtures | assertions |
|----|------|-------|------|----------|------------|
| V2-1 | v2_created_in_draft | store | test_v2_model.py | `Session` in-test; `create_v2_draft` | status=="draft"; v2 text == raw text at creation |
| V2-2 | approve_transitions_status | store | same | approve_v2 | status=="approved"; approved_at non-null |
| V2-3 | only_legal_forward_transition | store | same | approve twice | idempotent OR defined error; status ∈ {draft,approved} only |
| V2-4 | word_edit_writes_v2_not_raw | store | same | edit a word | raw_diarization byte-identical; v2 reflects edit |
| V2-5 | raw_immutable_under_all_edits | store | same | edit+tag+speaker+approve | raw_diarization/source/session_date unchanged |
| V2-6 | span_annotation_roundtrips | store | same | add `{span,surface,state,type,source}` | reload yields same annotation set |
| V2-7 | v2_speaker_assignment_independent_of_raw | store | same | assign confirmed speaker | raw `.speaker` label unchanged (C3); v2 carries name separately |
| V2-8 | reload_after_approve_preserves | store | same | edit+approve, reload | annotations + speaker + corrected text survive |

> §12 #1 OPEN: assert span round-trips to same surface; don't pin char-range vs token yet.

---

## Area 2 — Staged-pipeline GATE
Refactors atomic `_enrich_in_background` → `ingest → enrich(draft) → [GATE] → index+extract`.

| ID | name | level | file | fixtures | assertions |
|----|------|-------|------|----------|------------|
| G-1 | draft_runs_enrich_only | integration | test_staged_gate.py | spy index_session+extract_session; mock enrich | enrich 1×; index NOT called; extract NOT called |
| G-2 | nothing_in_graph_pre_approval | integration | same | real store; ENABLE_KB_PIPELINE=1 | entities/mentions/obligations COUNT==0 before approve |
| G-3 | approve_opens_gate | integration | same | spies; approve | index 1×; extract 1× |
| G-4 | respects_flag_off | integration | same | delenv ENABLE_KB_PIPELINE; approve | extract no-op; entities COUNT==0 |
| G-5 | gate_reads_v2_not_raw | integration | same | edit word; capture chunk-text arg | indexing/extraction input reflects v2 correction |
| G-6 | opens_on_authoritative | integration | same | provisional→authoritative resolved_speakers before draft | v2 speaker seed == authoritative |
| G-7 | re_approve_idempotent | integration | same | approve twice; spies | extract count==1; entities stable |
| G-8 | enrich_failure_recoverable | integration | same | enrich raises LLMUnavailable | no crash; stays draft; graph empty; re-run works |
| G-9 | gate_e2e_via_api | API | same | client; ingest route; spies | ingest→draft; graph empty; approve→200, status flips, index/extract fire |

---

## Area 3 — Ground-truth writes (vocab + personal memory; type override)
| ID | name | level | file | assertions |
|----|------|-------|------|------------|
| GT-1 | entity_span_writes_vocab | store | test_ground_truth_writes.py | vocab[norm("dstack protocol")]={is_entity, type:project, provenance} |
| GT-2 | new_vocab_capture | store | same | OOV tag → vocab gains normalized surface |
| GT-3 | human_type_overrides_llm | store | same | user type beats nlp; final type==user value; source=="user" |
| GT-4 | personal_memory_seed_on_approve | integration | same | approve → personal-memory seed for U |
| GT-5 | grammar_fix_not_in_vocab | store | same | "their"→"there" → vocab unchanged (cross CD-11) |
| GT-6 | vocab_per_user_keyed | store | same | U1 type ≠ U2 type; no shared row |
| GT-7 | retag_updates_entry | store | same | single entry, type updated, no dup |

> §12 #2 OPEN: access via `vocab.get(user,surface)`/`vocab.put`; assert the hashmap contract, not SQL columns.

---

## Area 4 — Speaker tagging (VFTEE) + suggestions (cold vs warm)
| ID | name | level | file | assertions |
|----|------|-------|------|------------|
| SP-1 | untagged_gets_suggestions | API | test_speaker_suggestions.py | suggestions non-empty, seeded from invitees |
| SP-2 | cold_from_invitees | unit/store | same | cold source == invitees; no warm entries |
| SP-3 | cold_from_mentions | unit | same | mentioned name in cold suggestions (deterministic) |
| SP-4 | warm_from_voiceprint | API | same | FPM stub; warm candidate ranked above cold |
| SP-5 | confirmed_tag_reresolves | API | same | name flips both meetings; raw label unchanged; v2 reflects |
| SP-6 | pending_tag_no_flip | API | same | name stays None; v2 not finalized |
| SP-7 | empty_account_valid | API | same | suggestions==[] (not 500); manual entry allowed |
| SP-8 | warm_over_cold_ranking | unit | same | warm precedes cold in ordering |

---

## Area 5 — Insights v1 immediate; STALE-on-edit (latency guard); re-derive on approve
| ID | name | level | file | assertions |
|----|------|-------|------|------------|
| IN-1 | v1_present_on_draft | integration | test_insights_stale.py | draft exposes v1 insights immediately (mock enrich) |
| IN-2 | edit_marks_stale | store | same | stale==true after edit; prior content still readable |
| IN-3 | **edit_fires_NO_llm** | integration | same | spy ALL LLM/embed seams; word edit + span tag + speaker tag → each spy count==0 |
| IN-4 | approve_rederives | integration | same | re-derive 1× on approve; stale cleared |
| IN-5 | v2_detailed_out_of_scope | integration | same | Part-2 detailed entrypoint spy==0 on Part-1 approve |
| IN-6 | multi_edit_single_stale | integration | same | 5 edits → LLM spies==0; stale stays true |

> §12 #5 OPEN: backend `stale` boolean + single re-derive fully assertable now; UI surfacing → FE-3 soft contract.

---

## Area 6 — Ramp-up trust state
| ID | name | level | file | assertions |
|----|------|-------|------|------------|
| TS-1 | new_defaults_gated | store | test_trust_state.py | state=="gated" |
| TS-2 | gated_requires_approval | integration | same | extract/index NOT called until approve |
| TS-3 | graduated_auto_builds | integration | same | auto user → index/extract fire without approve |
| TS-4 | graduates_at_threshold | store | same | after Nth approval → gated→auto |
| TS-5 | no_graduate_below_threshold | store | same | N-1 → stays gated |
| TS-6 | per_user_not_global | store | same | U1 auto, U2 gated independently |

> §12 #3 OPEN: gate behind `trust.should_graduate()` seam with injected threshold; assert below→gated / at→auto.

---

## Area 7 — Per-user isolation
| ID | name | level | file | assertions |
|----|------|-------|------|------------|
| IS-1 | vocab_isolated | store | test_per_user_isolation.py | get(U2,"dstack")==None; get(U1,...) present |
| IS-2 | memory_isolated | store | same | U2 memory empty; U1 has seed |
| IS-3 | suggestions_no_cross_user | API | same | U2 suggestions exclude U1 vocab |
| IS-4 | trust_isolated | store | same | per-user trust independent |
| IS-5 | identity_ws_scoped_vocab_user_scoped | store | same | identity shared at workspace; vocab per-user (§14 split) |

---

## Area 8 — Cold-start
| ID | name | level | file | assertions |
|----|------|-------|------|------------|
| CS-1 | no_suggestions_except_invitees_mentions | API | test_cold_start.py | suggestions==(invitees∪mentions); vocab-derived==empty |
| CS-2 | calendar_text_only_insight_seed | integration | same | insight seed input == calendar/raw_intent text |
| CS-3 | no_warm_path | store | same | warm source empty; only cold active |
| CS-4 | warming_progress_signal | API | same | progress field exists, reflects 0 approved |

---

## Area 9 — Part 1 → Part 2 contract + drift guard
| ID | name | level | file | assertions |
|----|------|-------|------|------------|
| C9-1 | approved_v2_shape | store | test_part2_contract.py | exposes corrected text + span annotations + speaker assignments + status=="approved" |
| C9-2 | vocab_shape | store | same | each entry {is_entity,type,canonical_id?,provenance}; type ∈ allowed set |
| C9-3 | **drift_guard_schema** | store | same | EXPECTED_V2_FIELDS/EXPECTED_VOCAB_FIELDS == actual keys; FAILS LOUD on drift |
| C9-4 | candidate_annotation_contract | store | same | keys {span,surface,state,type?,source,confidence?}; state∈{known,candidate,oov}; source∈{nlp,correction,user} |
| C9-5 | part2_not_reach_into_editor | integration | same | Part-2 entrypoint consumes only approved v2 + vocab + memory; editor-mutation spy==0 |

---

## Area 10 — Candidate detection (§15) — FIRST-CLASS

### 10a — Real-spaCy unit (`tests/test_candidate_detection.py`, all `@pytest.mark.requires_spacy`)
| ID | name | assertions | gold? |
|----|------|------------|-------|
| CD-1 | noun_chunks_become_candidates | "the DStack protocol" → ONE candidate | mild |
| CD-2 | multiword_stays_one | "the consent plane" → one span all tokens | mild |
| CD-3 | pronoun_only_dropped | "it"/"that thing" → no candidate | mild |
| CD-4 | function_word_no_candidate | the/and/of never standalone candidates | mild |
| CD-5 | oov_proper_noun_flagged | coined token ("Recato") → state oov | mild |
| CD-6 | known_from_vocab | vocab hit → state known | no |
| CD-7 | candidate_when_not_in_vocab | dict NP not in vocab → state candidate | mild |
| CD-8 | v0_NER_dormant | v0 → NO type auto-assigned (type None) | no |
| CD-9 | v1_NER_pretypes | v1 → type set from ent.label_ (don't pin exact label) | yes |
| CD-10 | correction_NOUN_PROPN_promotes | NOUN/PROPN/OOV re-parse → promote + vocab write | mild |
| CD-11 | correction_grammar_text_only | "their"→"there" → text-only, NOT promoted | mild |
| CD-12 | correction_POS_filter_precision | table of cases routes promote vs text-only | yes |

### 10b — Deterministic fake (`tests/test_candidate_annotation.py`, default gate, NO model)
Monkeypatch `candidate.spacy_pass` → fixed `(span,surface,pos)` tuples.
| ID | name | assertions |
|----|------|------------|
| CD-20 | state_assignment | 3 spans → known/candidate/oov deterministically |
| CD-21 | vocab_O1_normalized | "DStack Protocol" & "dstack protocol" hit same key |
| CD-22 | **pass_runs_once_at_draft** | spaCy-pass spy==1 across draft+3 edits (NOT per edit) |
| CD-23 | correction_reparses_one_token | per-token re-parse called once with only edited token |
| CD-24 | annotation_shape | persisted keys {span,surface,state,source}+opt type/confidence; source=="nlp" on draft |
| CD-25 | annotations_on_draft | candidates on v2 status=="draft"; raw untouched |
| CD-26 | user_source_beats_nlp | user confirm → source=="user", user type |
| CD-27 | oov_two_payoffs | ASR-garble oov + real-entity oov both state oov, no premature classify |

### Frontend (blocked on §12 #4/#5)
| ID | name | assertions |
|----|------|------------|
| FE-1 | renders_preannotated | known tinted; candidate→suggest-type; oov→needs-review; plain non-interactive |
| FE-2 | local_first_no_network_per_keystroke | network calls==0 during edit |
| FE-3 | stale_indicator | stale:true → indicator shown (soft) |
| FE-4 | speaker_suggestions_not_blank | untagged → suggestion chips |
| FE-5 | one_tap_confirm | tap → tag endpoint with vocab type, optimistic |

> §12 #4 OPEN: write against DOM roles; if no component runner, downgrade to Playwright e2e or skip w/ TODO. Don't block Tier-0 on FE-*.

---

## Tests blocked/softened by §12 STILL-OPEN
| §12 | blocks | assert NOW | tighten when locked |
|-----|--------|-----------|----------------------|
| #1 v2 span encoding | V2-6, CD-24, C9-3/4, M-1/3 | span round-trips to surface; names in EXPECTED_V2_* constants | exact offset/token + table/col names |
| #2 vocab schema | GT-*, IS-1/3, C9-2, CD-20/21 | `vocab.get/put` seam + hashmap contract | pin SQL columns + index |
| #3 graduation rule | TS-4, TS-5 | `should_graduate()` seam + injected threshold | swap count for locked signal |
| #4 editor primitive | FE-1..5 | DOM-role behavior; skip if no runner | pin to chosen primitive |
| #5 stale-insight UI | IN-2 (ok), FE-3 | backend stale boolean + single re-derive | exact UI + what re-derives |

Backend areas 1,2,3,5,6,7,8,9,10b are **fully assertable now** via stable seams; only frontend (#4/#5) and exact-encoding pins (#1/#2/#3) wait.

---

## spaCy test infra note
**Confirmed:** `spacy`, `en_core_web_sm`, `wordfreq` are **NOT installed** in the canonical venv — net-new deps for Part 1.

1. **Add a `requires_spacy` marker** in conftest (mirror `requires_ollama`): `pytest_configure` adds the marker; `_spacy_ready()` tries `import spacy; spacy.load("en_core_web_sm")`; `pytest_collection_modifyitems` skips when not ready. Model is OPTIONAL for the default gate.
2. **Two-tier strategy:**
   - 10a = real spaCy, `requires_spacy`, structural assertions only (never pin exact `ent.label_`). Load model ONCE via module-scoped fixture.
   - 10b = deterministic fake (monkeypatch `candidate.spacy_pass`) — runs in default CI gate with NO model; covers state assignment, O(1) vocab + normalization, run-once timing (CD-22), single-token re-parse (CD-23), annotation shape, source precedence.
3. **Design seam requirement (the implementer MUST follow):** isolate spaCy behind one module — `transcripts/candidate.py` with `spacy_pass(text) -> list[CandidateSpan]` and `reparse_token(token) -> POS`. 10b monkeypatches that one function; 10a calls it for real. Without this seam, the deterministic tier is impossible and CI hard-depends on the 15 MB model.
4. **Default gate (10b + all backend areas) runs green without spaCy/Ollama/NearAI.** Document `python -m spacy download en_core_web_sm` in venv setup like `sqlite_vec`.

---

## Prioritized tiers

### Tier 0 — Acceptance gate (must be green)
M-1, M-3 · V2-4, V2-5 (raw immutability) · V2-1, V2-2, V2-8 · G-1, G-2, G-3, G-4, G-5 · IN-3, IN-6, CD-22, CD-23 (latency guard) · GT-1, GT-3, GT-5 · IS-1, IS-2 · CD-20, CD-24, CD-25, CD-26, C9-4 · C9-1, C9-3.

### Tier 1 — Ship-with
M-2, V2-3, V2-6, V2-7 · G-6..G-9 · GT-2, GT-4, GT-6, GT-7 · SP-1, SP-5, SP-6, SP-2, SP-4 · IN-1, IN-2, IN-4, IN-5 · TS-1, TS-2, TS-3 · IS-3, IS-5 · CS-1, CS-2 · CD-1, CD-2, CD-3, CD-5, CD-10, CD-11 · C9-2, C9-5, CD-21, CD-27.

### Tier 2 — Later
SP-3, SP-7, SP-8 · TS-4, TS-5, TS-6 · CS-3, CS-4 · CD-4, CD-6, CD-7, CD-8, CD-9, CD-12 (v1 NER) · FE-1..FE-5 (promote when §12 #4 locks) · gate/insight edge cases.

---

### Critical files for implementation
- `transcripts/models.py` — v2/candidate-span/status; drift-guard target.
- `transcripts/store.py` + `storage/sqlite.py` — `save_transcript_session` write-once; v2/vocab persistence.
- `api/transcripts_routes.py` — `_enrich_in_background` (~line 743) → split into the gate; approve endpoint.
- `transcripts/candidate.py` (NEW) — the spaCy seam (`spacy_pass`, `reparse_token`).
- `tests/conftest.py` — add `requires_spacy` + `_spacy_ready()`.
- `tests/test_kb_extract_pipeline.py`, `tests/test_tag_speaker.py` — gating-spy + API-client patterns to mirror.
