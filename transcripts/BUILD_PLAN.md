# Build Plan — Cohort Context Intelligence

> **Status:** Layer 1 core built (Phase 0 ✅). Canonical plan.
> **Mode:** **Offline / batch, prep-oriented.** We process *completed past transcripts* to summarize meetings and (later) surface cross-meeting connections that help prep for upcoming ones. Real-time is a future vertical.
> **Home:** `conclave-shape-rotator/transcripts/` for now; standalone-repo extraction is an Open Question.
> **One line:** Turn a team's past conversations into a queryable, connectable intelligence layer over their people/project graph — confidential by design.

---

## 0. Operating principles

- **Viable-minimal, not naive.** Everything deferred ships a *working* minimal version now (e.g. chunk→map-reduce, not "truncate to 4k") with a clear upgrade path. Deferral is about sophistication, never about working at all. See List B.
- **Show, then iterate (flashy-first).** This is for a cohort. Get something stylized on screen *fast* — "we finally put your transcripts to use" — then deepen. Phase 1 optimizes for a good-looking visible demo; intelligence depth comes after the wow.
- **Core-vs-skin.** Keep the core domain cohort-blind; push cohort quirks (graph source, vocab, transport, visual theme, permission policy) behind adapters/config. Test per feature: *"drop it into another org next month — what changes?"* Adapter/config = core-safe; rewrite logic = a leak.
- **Confidential by design.** Core runs in a TEE (Phala CVM); we add **no centralized plaintext exposure** beyond the already-consented/public inputs. LLM calls go to NearAI (TEE-served).

---

## 1. Architecture

Ports & adapters. The core never imports a cohort/source-specific type — only adapters do.

```
        ┌──────────── OWNED CORE (generic, cohort-blind) ────────────┐
        │  Ingest → Intelligence (read/store/compare/fetch) → Surface │
        └─────────────────────────────────────────────────────────────┘
 inbound ▲              graph ▲                       outbound ▼
 ┌───────┴────────┐  ┌────────┴──────────┐  ┌──────────┴───────────┐
 │ provided files  │  │ SROS graph adapter │  │ Dashboard / Suggestion│
 │ (sources.py)    │  │ (cohort-surface.json│  │ / Matrix             │
 │ VoxTerm: future │  │  / swf-node /graph) │  │                      │
 └─────────────────┘  └────────────────────┘  └──────────────────────┘
        └────── communication layer (cohort-specific, swappable) ──────┘
```

Built (Phase 0): `models.py`, `parse.py` (generic), `enrich.py` (1 LLM call), `store.py` + `storage/sqlite.py` (`transcript_sessions`), `cli.py`. 7 tests green. **Invariant:** `raw_diarization` written once; stages write only `metadata`/`derived`. (Holds cleanly because we ingest *completed* transcripts — no streaming.)

**Immediate input:** hand-provided transcript files via a single `sources.py` reader; identity to Cohort OS is mock-linked (`identity.resolve_identity`). VoxTerm/Gemini/Matrix connections are *future* — they plug into the same ingest seam (see `IMPLEMENTATION_PLAN.md` §K Extension points).

---

## 2. Compute model — where LLM / agentic / reasoning / TEE

Default to the cheapest tier; climb only when a stage earns it:
`deterministic < embeddings/ML < single-prompt LLM < reasoning model < agentic (tool-loop)`

- **Tier A — single prompt everywhere (now).** One `config.get_llm()` call per LLM stage. Proves the pipeline.
- **Tier B — specialize.** Embeddings for matching; structured output; a reasoning model only where quality pays (signal extraction, query synthesis).
- **Tier C — agentic.** Only organizer-query + multi-hop relations graduate to tool-loops (cf. `skills/hackathon_novelty/agent.py`).

**TEE rule:** any stage touching raw transcript content runs in the enclave; LLM calls go to NearAI.

| Stage | Layer | Now | Target | TEE |
|---|---|---|---|---|
| Parse/normalize | 1 | deterministic | deterministic | yes |
| Enrich (summary/signals/entities) | 1 | 1 prompt + chunking | reasoning (B) | yes |
| Store | 1 | deterministic | deterministic | yes |
| Dashboard render (shape-ui) | 1 | client, no LLM | — | no |
| Speaker identity | 2 | source passthrough / minimal infer | + embeddings | yes |
| Entity→node match | 2 | exact/tag | embeddings + LLM-on-ambiguous (B) | partial |
| Cross-transcript relations | 2 | co-occurrence | embeddings → LLM describe; agentic (C) | yes |
| Meeting-prep brief | 2 | 1 prompt over retrieved context | reasoning (B) | yes |
| Organizer NL query | 2 | 1 prompt | agentic (C) | yes |

---

## 3. List A — Assumptions taken (awareness only; no action now)

| # | Assumption | Breaks when |
|---|---|---|
| A1 | Transcripts are consented + public across the cohort ✅ | a different org → consent becomes per-org config |
| A2 | Offline/batch on completed transcripts (not real-time) | real-time vertical (future) |
| A3 | Names come from the provided transcript; identity is mock-linked to Cohort OS (`resolve_identity`) | real Cohort-OS lookup; `Speaker N` unresolved cases |
| A4 | **Speakers ≈ participants for now; membership added later** | silent attendees matter (permission layer, 1.5) |
| A5 | Scale is small (one cohort, hundreds of sessions) | multi-cohort / long horizon |
| A6 | Everyone-with-access-sees-all until permissions (1.5) | private meetings enter |
| A7 | NearAI/TEE is the LLM substrate (backend swappable) | provider outage/cost (we hit it) |
| A8 | SROS graph is complete/accurate enough to match against | stale/sparse profiles |
| A9 | "Summary + bullets" is empirically useful enough to demo | **needs research — validate on real transcripts** |
| A10 | Steady transcript supply; `shape-ui` is liftable | data stops / license-coupling surprises |

---

## 4. List B — Minimal-now implementations (and upgrade path)

| Area | Naive (avoid) | Viable-minimal NOW | Improve later |
|---|---|---|---|
| Long-transcript summary | truncate | chunk by turn-window + overlap → summarize → merge (map-reduce), tuned empirically | hierarchical/recursive, salience-aware |
| Relation handling | none | shared-entity + shared-tag co-occurrence → "related meetings/people" | embedding similarity, typed relations, multi-hop |
| LLM JSON reliability | parse-or-empty | bracket-parse + 1 repair re-prompt + light schema check | function-calling / constrained decoding |
| LLM access/cost | crash on 402 | backend switch (NearAI⇄Ollama) + budget/error guard | multi-provider failover, budget monitor |
| Speaker identity | ignore who-said-what | **mock name→Cohort-OS ID** (`resolve_identity`); `Speaker N` unresolved | real cohort lookup, voiceprint-UUID carryover, voice clustering |
| Entity→node match | raw strings | exact/alias name + `skill_areas` match | embeddings rank + LLM disambiguation |
| Retrieval/vectors | full vector DB now | tags/keywords + SQL filter; numpy cosine when needed | FAISS / confidential vector DB |
| Permissions (1.5) | everyone sees all, no field | **speaker-keyed** `public-to-cohort` vs `owner-only` + owner field, behind a small seam | **membership(attendee)-keyed** + role override + surface/depth layers |
| Re-enrichment/backfill | manual re-run | script: reprocess where `pipeline_version` < current, write only `derived` | incremental, diff-aware |
| Eval | eyeball once | 5–10 hand-labeled golden set + simple metrics + regression check | LLM-as-judge, larger set, CI gate |
| Embedding model | unpinned | pin `all-MiniLM-L6-v2`, local/in-TEE | domain model + re-embed migration |
| Dashboard | raw JSON dump | stylized read-only summaries+bullets per meeting, shape-ui glyphs | cross-relations viz, personality vertical, live |

---

## 5. Phases & deliverables (flashy-first, gated)

**Phase 0 — Layer 1 core ✅** Parse → enrich → store → CLI.

**Phase 1 — "Show something" (flashy MVP)**
> **Deliverable:** stylized, read-only dashboard of accurate per-meeting **summaries + key bullets** from *real cohort transcripts*.
- **1a Batch ingest** — import **hand-provided transcript files** via `sources.py` → sessions (idempotent by `session_id`). *Done when: N transcripts stored.*
- **1a.5 Mock identity** — link names → mock Cohort-OS IDs (`resolve_identity` seam); `Speaker N` stays unresolved. *Done when: known speakers show resolved names.*
- **1b Enrichment that survives length** — chunk→map-reduce + JSON repair-retry + LLM access fixed (NearAI top-up / Ollama). *Done when: a long real transcript yields coherent summary+bullets.*
- **1c Eval golden-set** — manual labeled set + metric. *Done when: a number moves on a prompt change.*
- **1d Stylized dashboard ⭐** — per-meeting summary+bullets, shape-ui glyphs, nice type/motion. *Done when: a member opens it, sees their real meetings, looks flashy.* ← demo moment.

**Phase 1.5 — Permission layer (build once, stable after)**
> **Deliverable:** coarse visibility (speaker-keyed now → membership-keyed later) + role override. *Done when: a user sees only what they're allowed to.*

**Phase 2 — Intelligence (connect + the prep payoff = true value)**
- **2a Speaker identity** — passthrough + minimal infer. *Done when: named sources attribute correctly.*
- **2b Entity→node matching** — exact/tag first. *Done when: entities link to SROS `record_id`s.*
- **2c Cross-transcript relations ⭐** — co-occurrence. *Done when: "related meetings/people" surface and beat a tag-only baseline.*
- **2d Meeting-prep brief ⭐** — "before your meeting with X, here's relevant context from past sessions." *Done when: a member judges a prep brief useful.*
- **2e Organizer NL query** — agentic. *Done when: held-out questions answered with citations.*

**Open verticals (parallel, un-gated):** personality extraction; real-time suggestions.

**Phase 3 — Generalize/extract.** *Done when: a second org lights up the dashboard with only adapters + config changed.*

---

## 6. Connector roadmap

| Connector | Kind | Priority | Status |
|---|---|---|---|
| Hand-provided transcript files (`sources.py`) | ingest | **now (1st)** | the only Phase-1 source |
| Mock Cohort-OS identity (`identity.py`) | graph link | **now** | mock IDs; real lookup later |
| VoxTerm (exports / hivemind sink) | ingest | future | new `sources` reader + sink endpoint (§K) |
| Gemini / generic ASR | ingest | future | new `sources` reader |
| SROS graph (`cohort-surface.json` / swf-node `/graph`) | graph match | Layer 2 | real identity + entity matching |
| Dashboard | outbound | 1st surface | not started |
| Matrix / Calendar | ingest+outbound | later | not started |

---

## 7. Open questions (still genuinely open)

- **Repo home:** standalone vs in-workspace vs stay. (undecided)
- **Working name / brand.**
- **Communication transport:** swf-node vs own API + Matrix bot vs both.
- **Embedding specifics** (which NearAI/local models per stage) — decided at Tier B.

*(Resolved this round: consent ✅, real-time-vs-offline ✅ offline, dashboard v1 scope ✅, speakers-now/membership-later ✅, edge policy = consumer's concern ✅, all no-minimal holes now have a minimal ✅.)*

---

## 8. Success criterion

The asset that survives the cohort: **accumulated, structured, queryable context + the engine that produces it.** Flash MVP proves we used the transcripts; the *true value* is cross-meeting connections (2c/2d). If, a month after graduation, we point the same core at a different org with only adapters + config — and the dashboard lights up — the plan worked.

> **Current blocker:** LLM access — NearAI hit the $15 credit cap. Top up or set `CONCLAVE_LLM_BACKEND=ollama` before any enrichment (incl. the eval set) can run.
