# ENTITY-CANON — the single, user-correctable source of truth for entities, speakers & terms

> **Status:** planning doc (2026-06-10). NOT scheduled. Cross-cutting — touches
> ingest, entity-resolution, the graph, search, and Connections. Revisit when
> we pick up the Connections Stage-1 tightening; the two reinforce each other.
>
> This is the productionized superset of the "terminology ledger / personal
> vocabulary" idea — written up here because it became a real architecture, not
> a side feature.

---

## 1. Why this exists (the problem)

Transcription mangles exactly the words that matter most — names, products,
jargon, acronyms: `DStack` → `Dstack` / "the stack" / "dee stack"; `Albiona`
→ "Albunia". That noise:

- **splits one real entity into many** (`DStack`-the-tool vs `Dstack`-the-project
  are two rows today),
- **has no fix path** — there is currently **no way for a user to edit an
  entity or a speaker name**,
- **propagates downstream** — bad/duplicate entities degrade **search**, the
  **graph**, and the **Connections matcher** (we saw it produce *coincidental*
  matches partly because the join key was noisy).

What we need:
1. Users can **edit** terms / entities / speakers (`dstack` → `DStack`, merge
   duplicates, fix a misattributed speaker).
2. Edits **back-propagate** — the change appears everywhere (graph, search,
   entities list, connections), from **one source of truth**.
3. Corrections **persist as rules** so *future* transcripts are auto-normalized
   (the learning ledger / flywheel).

---

## 2. The core architectural decision (do this first, it shapes everything)

**The entity tables ARE the single source of truth. The graph is derived from
them live — do NOT persist the graph.**

Verified in the codebase:
- There is **no graph/nodes/edges table** anywhere (checked all migrations).
- `/graph` (`api/kb_routes.py::workspace_graph`, ~line 279) **computes** nodes
  and edges from `entities` + `entity_mentions` + sessions **on every request**.
  The front-end only *renders* what the backend computes.

Consequences:
- The single source of truth **already exists**: `entities`, `entity_mentions`,
  `obligations` (+ the derived `resolved_speakers` for speakers).
- **An edit written to those tables propagates everywhere automatically** —
  graph, search, entities list, and the Connections matcher all derive from
  them, so they reflect the change on the next read. No sync code.
- **Persisting the graph would be an anti-pattern here** — it would create a
  *second* source of truth that can drift from the entity tables, the exact
  opposite of the goal. (No perf need: graph is ~7ms. No snapshot need:
  bi-temporal "as of date" already works via obligation `valid_to` windows.)

So the work is **an edit layer + a ledger**, *not* a graph store.

---

## 3. The three components

### A. Editable canonical entities & speakers  *(net-new; no edit endpoints exist today)*
User-facing operations, each writing to the **source-of-truth tables**:
- **rename / correct spelling** — update an entity's `canonical_name` (and/or
  push the old form into its variant set).
- **merge** — fold entity B into entity A (re-point B's `entity_mentions` to A).
  Conservative: **false merges are unrecoverable** (the stated philosophy in
  `transcripts/entity_resolution.py`), so every merge is logged + reversible.
- **split / re-type** — separate a wrongly-merged entity; fix `type`
  (tool/project/topic/person/company).
- **speaker correction** — reassign / rename a speaker. Writes to the **derived**
  `resolved_speakers` (in `SessionMetadata`, owned by `transcripts/identity.py`)
  — **the raw diarization stays immutable**.

Reuse: `storage/kb_graph.py` already has `insert_entity`, `add_mentions`,
`find_entity`, `merge_mentions_into_entity`, `entities_for_sessions`. The
edit endpoints are a thin write layer over these + a new audit/provenance log.

### B. The vocabulary ledger  *(the persistent memory)*
A provenance-weighted store: `canonical ↔ variants`, with `type`, `scope`,
`source`, `confidence`. Trust by source:
`explicit user correction` (highest) · `roster` (authoritative) ·
`uploaded-doc vocab` (candidate) · `system-proposed` (low).

The ledger becomes the **memory that `entity_resolution.py` reads and writes**:
- **read:** consult the ledger *first* → known variants merge **deterministically**
  (no LLM call, no cosine gamble) → fall back to cosine + LLM tiebreak for
  unknowns. Cheaper *and* more accurate for the terms that matter.
- **write:** new high-confidence resolution decisions flow back as ledger entries
  / proposals. (Rhymes with the existing Mem0-style upsert in the pipeline.)

### C. Active discovery loop  *(the flywheel — decided: active, not passive)*
The system proposes candidate variants, doesn't just store explicit ones:
- **discover** via fuzzy/phonetic clustering (Metaphone / edit-distance:
  Albiona/Albunia) + **contextual co-occurrence** (variants with the same
  neighbors are likelier the same) + **roster anchoring** (garbles of known
  names) + an **in-TEE LLM judge** for ambiguous clusters.
- **confirm** one-tap → high-confidence entry. **Reject also teaches** — a
  "NOT the same" negative entry stops re-proposing and sharpens future
  suggestions.
- Same **propose → judge → confirm** shape as the Connections feature.

---

## 4. Back-propagation semantics (the heart of "one source of truth")

A single user edit does **two** things:
1. **Apply now** to existing data — rename/merge across all `entity_mentions`
   → the graph, search, entities list, and Connections reflect it on next read
   (because they all derive from the entity tables).
2. **Record a rule** in the ledger → **future** ingests normalize the variant
   automatically (no re-edit needed).

One action, both effects. That's what makes it a single source of truth *and*
a compounding system.

---

## 5. How it integrates with what's already built
- **Graph** (`api/kb_routes.py`): derives from entities → reflects edits for free.
- **Search** (`storage/kb.py` FTS + vec): entity-aware results improve as
  entities de-dup; query path unchanged.
- **Connections** (`companion/collab_match.py`): the join key X gets cleaner →
  fewer coincidental matches. **This feature retroactively improves the thing
  we just built.**
- **Entity resolution** (`transcripts/entity_resolution.py`): gains a
  deterministic, human-curated layer (consult-ledger-first).
- **Speaker identity** (`transcripts/identity.py`): edits feed the
  roster/alias resolution; corrections become aliases.

---

## 6. Confidentiality & immutability fit (non-negotiable — core thesis)
- **Discovery + LLM judging** run at **ingest/batch, in-TEE** (where LLM work
  already lives). The **application** is a deterministic lookup → **the live
  query path stays LLM-free**, so "operator can't read your data" holds.
- **Edits touch the DERIVED layer** (entities / mentions / `resolved_speakers`);
  the **raw transcript stays immutable** (the pipeline's raw-write-once rule).
- The ledger is confidential org vocabulary → same SQLite, **no external service**.

---

## 7. What needs building (net-new)
- Entity/speaker **edit endpoints** (rename / merge / split / re-type / reassign)
  + an **edit-audit / provenance log** (the thing worth persisting — NOT a graph).
- **Ledger table(s)** (`canonical`, `variant`, `type`, `scope`, `source`,
  `confidence`, `created_by`) + negative entries.
- **`entity_resolution` consult-ledger-first** hook.
- **Discovery job** (fuzzy/phonetic + context + roster + in-TEE LLM) producing
  ranked proposals; a **confirm UI**.
- **NO graph store. NO new raw mutation. NO LLM on the query path.**

---

## 8. Open decisions (resolve when scheduled)
- **Scope:** workspace-shared ledger (names, products) vs a personal overlay
  (idiosyncratic shorthand) — ties into the `PersonalMemory` permission model.
- **Auto-apply threshold:** how confident before a ledger entry merges without
  a confirm (bias conservative — false merges unrecoverable).
- **Merge reversibility model:** snapshot-before-merge vs append-only re-point
  log.
- **Speaker identity:** how the ledger interacts with `identity.py`'s
  roster/voice-ID-later strategy.
- **Bootstrapping cadence:** how/when discovery runs over existing data.

---

## 9. Highest-value starting wedge (when revived)
Run the discovery clustering over the **existing `entities` table** → surface
current duplicates (`DStack`/`Dstack`, `Andrew`/`Andrew Miller`) as a
"confirm these N pairs?" list. **Immediate cleanup that retroactively improves
the Connections matcher + search** — and proves the discovery→confirm loop on
real data before building intake. Then add live correction/upload intake.

---

## 10. Relationship to other docs
- `transcripts/EVAL.md` — eval decision records (incl. extraction F1 0.62, the
  noise this fixes).
- `scripts/eval/OPEN_ITEMS.md` — running backlog (Connections, dense leg, etc.).
- The Connections feature (`companion/collab_match.py`, `connect_reason.py`) —
  the primary downstream beneficiary.
