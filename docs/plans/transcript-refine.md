# Part 1 — Transcript Refinement (the ground-truth capture layer)

> Status: DESIGN (no code yet). Branch: `feat/transcript-refine`.
> This doc is the spec the Part 1 implementation builds against, and the
> contract the future Part 2 (graph synthesis) consumes. Part 2 is NOT in scope
> here.

## 1. Why this exists (the moat)

Post-meeting, the user sees a diarized draft and corrects it. **Every correction
is a human-confirmed ground-truth label** — strictly better than the LLM's guess.
Those labels (corrected words, speaker tags, entity+type tags, new vocab) feed a
per-user **vocab** and **personal memory**, which power suggestions, which reduce
future corrections — a flywheel. When we've learned enough from a user's
corrections, we *graduate* them from "approve-before-build" to auto-build. The
capture of ground truth as a byproduct of the user simply reading their
transcript is the partial moat.

## 2. The boundary (Part 1 vs Part 2)

- **Part 1 (this) = ground-truth CAPTURE.** A low-latency editable transcript
  whose edits produce confirmed labels → per-user vocab + personal memory.
  Produces an **approved `v2`** transcript. Per-user only.
- **Part 2 (later) = graph SYNTHESIS.** Consumes the approved `v2` + vocab to
  build the entity graph + signals, makes the *graph itself* editable, and adds
  workspace permission levels.

Part 1 produces **labels**; Part 2 turns labels into a **graph**.

## 3. Current state (from the 2026-06-19 read-only analysis of `main`)

- The pipeline is **one atomic background pass** with **no human gate**:
  `_enrich_in_background(session_id)` (`api/transcripts_routes.py:743`) runs
  enrich → index → extract end-to-end, async, immediately on ingest.
- `raw_diarization` is **write-once immutable** (`transcripts/store.py`). Today's
  only post-ingest mutation is name-flip via voiceprint
  (`store.reresolve_voiceprint`), gated on an existing `voiceprint_id`.
- Frontend `transcript-panel.tsx` allows **speaker name tagging only** (owner-
  only, blank-input form) — no text edit, no entity tagging, no suggestions.
- Entities today are extracted **LLM-only**, stored in **one global table**
  (unique on `(type, canonical_name)`); "personal view" is a read-time filter.
  There is **no manual entity add/confirm path**.
- KB reads the transcript as `{speaker: opaque-label, text}` and extracts
  entities **semantically from text** — it never reads speaker identity. So
  Part 1 (speaker/identity) and Part 2 (KB) are already cleanly decoupled.

**Implication:** the editor, the suggestion infra, the per-user vocab, the
approval gate, and the trust/ramp-up state are essentially **net-new**. The
individual pipeline stages (`enrich`, `index_session`, `extract_session`) are
already separately callable — the gate is an *orchestration* change, not a
rewrite.

## 4. Core data model — the `v2` span-annotated document

The seam everything hangs on. **Raw stays immutable; edits live on a `v2` layer.**

- `raw_diarization` (unchanged): provenance — "what was heard".
- **`v2` (new): the corrected, span-annotated document** — "what the user
  confirmed". Conceptually:
  - corrected text (word edits diverge from raw)
  - per-span annotations: `{entity, type}`, `{new_vocab}`, `{speaker}`
  - speaker assignment per segment (label → confirmed identity/name)
  - a `status`: `draft` → `approved`
- The KB build (Part 2) and the vocab/personal-memory writes read from **`v2`,
  not raw**. This reconciles word-editing with the immutability contract.

Open: exact representation (char-range spans vs token model), and whether `v2`
is a new table/column on `transcript_sessions` or a sibling store. Keep it the
**simplest thing that supports span tags + low-latency editing** (see §5).

## 5. The editor (Part 1's heart)

A **smart, low-latency, span-taggable** transcript editor. Capabilities:

1. **Speaker tagging — VFTEE-assisted.** Suggest from meeting invitees / explicit
   mentions / known voiceprints; builds on the existing `tag-speaker` → FPM
   consent binding (`api/record_routes.py:357`). Untagged speakers get
   suggestions, not a blank field.
2. **Word/text correction — suggestion-assisted.** Fix mis-transcribed words.
3. **Entity + TYPE tagging.** Tag a span as an entity and set/correct its type
   (person vs project vs …) — human-overridable, becomes ground truth.
4. **New-vocab capture.** A token not in the dictionary and never seen before →
   trivially taggable so it enters the vocab.

**Hard constraint: least-laggy.** The heavy work (LLM, embeddings, graph) stays
**out of the edit loop** — edits are local-first; ground-truth sync is async; the
expensive pipeline only fires on **approve**. This is the same seam as the gate.

Out of scope for Part 1: editing the *graph* itself (that's Part 2).

## 6. Ground-truth stores (per-user)

Edits populate two per-user stores:

- **Vocab / KB** — known terms, entities + types, speakers, new vocab. This is
  the **suggestion-engine substrate** (autocomplete for speakers/entities/words
  draws from it). Kept **separate from the global entity graph** so Part 1 stays
  decoupled and per-user.
- **Personal memory** — the user-level memory that, over time, seeds insights.

The flywheel: corrections → vocab grows → better suggestions → fewer corrections
→ graduation.

### Cold start (empty account)
On a fresh account there is **nothing**. The only seeds:
- **Speakers (bootstrap):** only meeting **invitees** (calendar) + people
  **explicitly mentioned** — used *before* any voiceprints exist. Once the user
  tags people, the VFT workspace-voiceprint feedback loop (§14) becomes the
  *warm* suggestion source.
- **Insights direction:** the **calendar event text**, since user memory is
  empty. (Calendar integration already exists on `main`.)
The ramp-up must **visibly show progress** — the account "warming up".

## 7. Insights

- **v1 (immediate):** lightweight insights shown with the draft (today's
  `derived.signals` via `enrich.py`).
- **On edit:** insights are **marked stale**, NOT live-recomputed (live LLM per
  keystroke would reintroduce the lag we're killing).
- **v2 (detailed):** richer insights regenerated **after approval**. The detailed
  signal/graph extraction is **Part 2**; Part 1 owns v1 + stale-marking + the
  re-derive-on-approve trigger.

## 8. The approval gate + ramp-up trust state

- **Gate:** for new users, the background KB build is **paused** until the user
  **approves** the draft. Nothing is extracted/enriched into the graph before
  approval. The gate opens on the **post-meeting authoritative** transcript
  (after the capture pipeline's DiariZen re-cluster + VFT re-identify — §14), so
  the user corrects the best automated guess, not the live provisional tags.
- **Trust state (new per-user concept):** `new → gated`, `graduated → auto`.
  Graduation after enough approved transcripts and/or measured confidence —
  framed as "we've learned enough from your corrections to trust the pipeline".
- **Progress UX:** make the flywheel visible ("N more reviewed meetings → auto").

## 9. Scope & deferrals

- **Per-user only.** Workspace-level graphs/entities and **permission levels** →
  Part 2. "Tag something for someone specifically" → Part 2.
- Vocab + personal memory are per-user; no cross-user leakage by construction.

## 10. The staged-pipeline refactor (the gate, mechanically)

Break the atomic `_enrich_in_background` into stages with a gate:

```
ingest → enrich (v1 insights, draft)  →  [HUMAN GATE: edit + approve]  →  v2 → (Part 2: index + extract + graph)
```

The stages (`enrich_pending`, `index_session`, `extract_session`) are already
individually callable; what's new is the orchestration + the `draft/approved`
state on the session, and gating index/extract behind approval (respecting the
existing `ENABLE_KB_PIPELINE` flag).

## 11. The Part 1 → Part 2 contract (what Part 2 will consume)

Pin this; it's the seam:
- **Approved `v2`** document (corrected text + span annotations + speaker
  assignments + `status=approved`).
- **Per-user vocab** (confirmed entities + types + new vocab).
- **Personal memory** seed.
Part 2 reads these; it does not reach back into Part 1's editor.

## 12. Decisions

### LOCKED (see §15)
- **Candidate unit = noun phrases** (spaCy `noun_chunks`).
- **Typing = phased** — v0 flags candidates + highlights OOV; v1 adds NER
  pre-typing (`ent.label_`, same model).
- **Engine = spaCy `en_core_web_sm`** (~15 MB, CPU, TEE-friendly), run once at
  draft time.

### LOCKED — data-foundation decisions (2026-06-19)
- **#1 v2 encoding:** v2 = structured **segments mirroring raw**; each span anchor
  is `(segment_id, token_start, token_end)` — **token/segment-relative, NOT flat
  char-ranges** (survives length-changing edits → passes V2-9). v2 persisted in a
  **new table keyed by `session_id`**; `raw_diarization` stays write-once.
- **#2 vocab schema:** per-user table
  `vocab(user_id, surface_norm, is_entity, type, canonical_id, provenance,
  created_at)` with `UNIQUE(user_id, surface_norm)`; accessed ONLY via a
  `vocab.get(user, surface) / vocab.put(...)` seam.
- **#6 personal memory:** for Part 1, personal memory **== per-user vocab +
  confirmed-speaker roster** (NO separate store). Richer per-user profile/recall
  is deferred to Part 2. (Collapses the ghost; GT-4/IS-2 assert vs vocab+roster.)

### STILL OPEN (resolve before that slice)
3. Graduation rule specifics (count threshold? confidence metric? which signal?)
   — needed for the trust-state slice.
4. Editor tech: which frontend editor primitive gives span-level tags at low
   latency (Next version constraint in `frontend/AGENTS.md`) — frontend slice.
5. How "stale insights" is surfaced in the UI and what exactly re-derives on
   approve — frontend slice (backend `stale` boolean is settled).
7. **Graduated/"auto" user behavior:** editable draft that also builds, or skip
   correction entirely? — trust-state slice.

## 13. Build order within Part 1 (proposed)

1. `v2` data model + `draft/approved` status + the staged-pipeline gate (opens
   on the post-meeting authoritative transcript — §14).
2. The editor shell (read draft, span selection) — low-latency baseline.
3. Speaker tagging (VFTEE-assisted) + suggestions from invitees/mentions.
4. Word edit + entity/type tagging + new-vocab → write to `v2` + per-user vocab.
5. Suggestion engine over vocab (the flywheel) + cold-start calendar seed.
6. v1 insights + stale-on-edit + re-derive-on-approve.
7. Ramp-up trust state + progress UX.

(Each step lands test-gated on `feat/transcript-refine`; nothing touches `main`
until reviewed — per project branch discipline.)

## 14. Upstream dependency — Capture / Diarization / Identity

Part 1 is the *downstream* of the capture pipeline. The authoritative source for
how the diarized transcript + speaker tags are produced and land in Conclave is:

> **`CONCLAVE-CAPTURE-ARCHITECTURE.md`** — at the workspace root (above this repo,
> currently untracked). Covers the capture microservice + diarization service +
> DiariZen GPU batch + VFTE identity, P0–P6.

This is a **pointer, not a copy** — do not duplicate that doc's content here. It
keeps this file merge-clean (no drift if the capture doc changes) and self-
contained on `feat/transcript-refine`. What Part 1 depends on from it:

- **Where Part 1 begins:** Part 1 opens on the **post-meeting authoritative**
  transcript — *after* DiariZen re-cluster + VFT re-identify have overridden the
  live provisional tags (capture P3/P4). The user corrects the best automated
  guess, not the live one. (The capture doc already requires the UI to handle a
  label changing post-meeting; our gate opens after that reconciliation.)
- **Shared, already-consistent mechanisms (no conflict):** raw stays immutable +
  `resolved_speakers` overlay (= our §4 `v2` model); the VFT manual-tag feedback
  loop ("tag → workspace voiceprint → next meeting auto-recognizes") = our §5
  VFTEE tagging and the *warm* path of our §6 speaker suggestions.
- **Scope planes differ — do not conflate:** speaker **identity** is
  **workspace-scoped** (VFT, `workspace_id` on every call, FAR ~1/N), owned
  upstream; Part 1's **vocab + personal memory** is **per-user**. Identity = who
  is speaking (workspace); vocab = what words/entities mean (per-user).

## 15. Candidate detection — the word-state model (LOCKED)

Resolves how "every word becomes a dictionary key" *feasibly*. A transcript is
NOT a list of word-keys; it is mostly plain text with a minority of **candidate
spans** that carry state. The expensive NLP runs **once at draft creation, never
per keystroke** (the §5 latency rule).

### Token tiers
- **plain** (~85%): function words + ordinary content. No state, not interactive.
- **candidate**: a noun phrase the detector flagged. Carries state, interactive.
- **confirmed**: a candidate the user (or a prior) tagged as a typed entity.

### Candidate unit = noun phrases (LOCKED)
Use spaCy `doc.noun_chunks` as candidate spans, so multi-word entities
("DStack protocol", "the consent plane") stay **one** candidate. Drop chunks that
are entirely function/pronoun ("it", "that thing") via POS.

### Engine = spaCy `en_core_web_sm` (LOCKED)
~15 MB, CPU-only, TEE-friendly. Loaded once at draft time. **v0** uses
tagger + parser (`token.pos_`, `doc.noun_chunks`). **NER ships dormant and is
turned on in v1** by reading `ent.label_` for pre-typing — *same model, zero new
dependency*. (This is why NER-later is "just an addition".)

### Candidate states (what the editor renders)
- `known` — normalized surface ∈ per-user vocab → render type-tinted, one-tap
  confirm.
- `candidate` — flagged NP not in vocab → "suggest a type" affordance.
- `oov` — not in the English dictionary AND not in vocab → highlight "needs
  review" (a likely ASR error OR a novel entity — one mechanism, two payoffs).
- (plain → nothing.)

### The dictionary (per-user vocab) — lookup is cheap
vocab = a hashmap `normalized-surface → {is_entity, type, canonical_id,
provenance}`. Lookup is O(1); running it for every candidate is trivial. The cost
we avoid is per-word **NLP** + per-word **interactive render**, NOT the lookup.

### Corrections = highest-precision candidate prior (POS-filtered)
On a word edit, re-run ONLY that token through spaCy:
- NOUN / PROPN / OOV → **promote** to candidate + write to vocab (high chance
  it's a mis-heard proper noun = graph-worthy entity).
- function/grammar fix ("their"→"there") → **text correction only**; do NOT add
  to vocab/graph (keeps the graph clean).

### Where it runs in the pipeline
The candidate pass is a step in the **draft-creation stage, before the gate**:
```
authoritative transcript
  → spaCy pass (noun_chunks + pos + English-dict/vocab lookup)
  → candidate spans + states annotated on v2 (status=draft)
  → editor renders pre-annotated doc   (NO NLP in the edit loop)
```
v1 adds `ent.label_` → pre-typed candidates. Same stage, same model.

### OOV dictionary source
English wordlist (bundled wordlist / `wordfreq`) ∪ per-user vocab (∪ a names
gazetteer later). OOV = in neither. Proper nouns/jargon naturally fall out as OOV
→ exactly the entity candidates.

### Data added to the v2 contract
Each candidate-span annotation:
`{span, surface, state: known|candidate|oov, type?: <entity-type>,
source: nlp|correction|user, confidence?}`.
(Exact span encoding still tied to §12 #1.)

## 16. Air-tightness notes — implementation must-dos (2026-06-19 review)

Gaps found reviewing this plan; resolve during build (tracked here so they
aren't lost). The two *decisions* live in §12 (#6 personal memory, #7 auto-user).

- **N1 — all THREE ingest paths must route through the gate.** `_enrich_in_background`
  is called from the ingest webhook, the Recato webhook, AND upload (per the
  analysis). The staged-gate refactor must cover all three, or a path leaks to
  the KB pre-approval. Test: G-10 (each entry point → draft, graph empty until
  approve).
- **N2 — span re-anchoring after length-changing edits.** A word edit that
  changes text length shifts every downstream candidate offset. The v2 encoding
  (§12 #1) MUST keep span anchors valid across edits. Test: V2-9. This is the
  highest-risk correctness bug in the editor — decide the encoding with this in
  mind (a token/segment-relative anchor survives edits better than a flat
  char-range).
- **N3 — frontend test infra is net-new.** No FE test runner exists in the repo.
  Standing up Vitest/RTL (or Playwright) is a prerequisite for FE-* — an explicit
  task, not just blocked on §12 #4.
- **N4 — upstream dependency (sequencing).** "Gate opens on the post-meeting
  authoritative transcript" (§8/§14) assumes the capture pipeline's P3/P4
  (DiariZen re-cluster + VFT re-identify), which is NOT built yet
  (`CONCLAVE-CAPTURE-ARCHITECTURE.md` P0–P6). **Near-term: the gate opens on the
  current ingest output**; the post-authoritative alignment lands when upstream
  does. Do not block Part 1 on it.
- **N5 — re-derive on approve reads v2, not raw.** Insight re-derivation on
  approve must run over the *corrected* v2 text, not `raw_diarization`. Tighten
  test IN-4 to assert the input is the v2 corrected text.
- **N6 — pin how Part 2 consumes vocab.** The §11 contract says Part 2 reads the
  per-user vocab; specify *how* (extraction priors / seed known-entities) so the
  seam can't drift. Part 2 implements it, but the contract names the shape.
- **N7 — verify the calendar→insight-seed link.** Cold-start (§6, test CS-2)
  assumes calendar event text lands in `metadata.raw_intent`. Confirm calendar
  events actually populate that field before relying on it as the only seed.

## 17. Build increments (commit-level)

Each code increment = code + its tests → green in the canonical venv → commit →
then the next. Done so far on `feat/transcript-refine`:
`1a` migration 0015 · `1b` v2 model + store seams · `1c` vocab seam · `2` staged
gate (`CONCLAVE_REFINE_GATE`, default off; all 5 ingest paths).

Remaining, in order:
- **3 — KB build reads approved v2** (`store.v2_segments_or_raw`; `index_session`
  sources it). G-5 + fallback.
- **4 — approve + v2-read API endpoints** (`POST /sessions/{id}/approve`,
  `GET /sessions/{id}/v2`). G-9 + 401/403.
- **5 — candidate detection** (deps dev-only): 5a marker+`candidate.py` seam ·
  5b noun_chunks/OOV/state · 5c POS correction-filter + wire into draft. CD-*.
- **6 — ground-truth writes** (`ground_truth.py` → `vocab.put`; type override;
  grammar-fix filtered). GT-1..7.
- **7 — suggestion engine + cold-start** (`suggest.py`). SP-*, CS-*.
- **8 — insights stale-on-edit + re-derive-on-approve** (incl. G-11). IN-1..6.
- **9 — trust state** — BLOCKED on §12 #3/#7.
- **F0–F3 — frontend** (test-runner is net-new) — BLOCKED on §12 #4/#5.
