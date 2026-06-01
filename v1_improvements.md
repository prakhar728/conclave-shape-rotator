# v1 Improvements — Post-PoC

> Minimal-change, maximum-impact lift to Phase 1 extraction quality, between the current PoC (commits up to `e8140b3`) and Phase 1.5 (permissions). Adds a per-team **context XML** for few-shot grounding, small additive schema fixes, and a tightened prompt. No architectural reshuffle.
>
> **Companion docs:** `METHODOLOGY_SURVEY.md` (literature), `DECISION_INPUTS.md` (empirical inputs), `BUILD_PLAN.md` (strategy), `IMPLEMENTATION_PLAN.md` (execution). This doc enriches the last two — see top instructions below for the merge protocol.

---

## Instructions for the receiving Claude session

> **You're being handed this document by a human teammate.** They are a courier, not the executor — your job is to read this fully, think it through against the current repo state, raise inconsistencies, and only then merge. The document contains TWO discrete change-sets you will apply to other docs in this repo:
>
> **Change-set A → `transcripts/IMPLEMENTATION_PLAN.md`.** Sections §1 through §9 of this document describe v1 improvements. Append them as a single new section titled `## v1 Improvements — Post-PoC` at the END of `transcripts/IMPLEMENTATION_PLAN.md`, after the existing §M. Do not modify anything above the append point.
>
> **Change-set B → `transcripts/BUILD_PLAN.md`.** Section §10 of this document lists targeted edits to existing sections of `transcripts/BUILD_PLAN.md` (architecture, compute model, list B, phases & deliverables, connector roadmap, open questions). Apply each in place per the §10 spec.
>
> **Workflow — DO NOT MERGE FIRST.** Before applying either change-set:
>
> 1. **Read** the current `transcripts/IMPLEMENTATION_PLAN.md` and `transcripts/BUILD_PLAN.md` end-to-end. Understand existing numbering, section structure, phrasing conventions, scope claims.
> 2. **Think it through thoroughly.** Specifically check for:
>    - **Section-number overlap** — does `BUILD_PLAN §5` already define a `Phase 1.1`? Does any existing section number collide with what §10 asks you to insert?
>    - **Scope conflicts** — does `BUILD_PLAN §6 Connector roadmap` already have a Cohort-OS / team-context row? Does anything in `§7 Open questions` overlap with what §10 asks you to add?
>    - **State mismatches** — does this doc's "current Phase 1 ships parse → enrich → store → API → dashboard" match the actual codebase and `git log` on this branch? Has anything moved past `e8140b3`?
>    - **Technical claims** — does the model name (qwen2.5:7b), the prompt version (v1), the entity enum (`person | project | concept | org`), the signal kind enum (`decision | insight | impactful_point | action_item | open_question`) still match the current `transcripts/models.py`, `transcripts/enrich.py`, `transcripts/prompts.py`? Surface anything that doesn't.
>    - **C1-C11 test gates** — would any change-set §3 schema addition break an existing test (`test_transcript_pipeline.py`, `test_enrich_mapreduce.py`, `test_api_transcripts.py`)?
> 3. **Flag every inconsistency** you find as a numbered list to the user. Don't paper over, don't auto-resolve.
> 4. **Discuss** with the user until every flagged item is explicitly resolved. Wait for explicit confirmation per item.
> 5. **Then merge** — Change-set A first (append to `IMPLEMENTATION_PLAN.md`), Change-set B second (in-place edits to `BUILD_PLAN.md`). Commit each separately, project commit style (lowercase area prefix + em-dash sub-clause, e.g. `transcripts: improvements — append v1 spec to implementation plan`). **No `Co-Authored-By` trailer.**
>
> If nothing surfaces in step 2, still pause and confirm with the user before merging: *"Here is exactly what I'd append / edit, confirm to proceed."*

---

## 1. Why v1 — the diagnosis

The Phase 1 PoC ships end-to-end (parse → enrich → store → API → dashboard, C1-C11 done). It works as a demo. But signal quality is mediocre, traced to four root causes visible in real enriched outputs at `transcripts/enriched-output/`:

- **Model cap.** `qwen2.5:7b` (per `cf40f73`) is the smallest viable model. Switching to `qwen2.5:14b` may help, but is not a v1 lever — we improve the prompt and schema FIRST so the cap, when raised, raises on a clean baseline.
- **Zero-shot prompt.** `prompts.py` asks for "3-8 signals" with no examples and no contrast. The model converges on the safe default (`kind=insight`) — observed in `office-hours-transcript.txt` and `project-intros-agents-day-3-transcript-may-21.txt` where nearly every extracted signal is `insight` despite obvious decisions and action items in the source.
- **Generic entity taxonomy.** Current `Entity.type ∈ {person | project | concept | org}` has no `technology` bucket, so TDX / SGX / RATLS / Opus 4.0 / Whisper / Matrix all collapse to `concept`. The "concept" type becomes meaningless.
- **No team priors.** The model has no anchor list of what projects, technologies, or topics this cohort actually works on, so it can't tell "EZTE" is a project worth canonicalizing, "Make OSI" needs the spelling fix, or "Flashbots" and "Flash Bots" are the same thing.

**Strategy.** v1 fixes all four cheaply: a per-team XML of priors + few-shot examples (§2), additive schema fields (§3), a tightened prompt (§4), and tighter identity / dedup (§5-§6). Versioning + backfill (§7) lets us iterate. Verification (§8) is by side-by-side spot check, not formal eval — per the no-mass-annotation constraint in `DECISION_INPUTS.md` §C and §H.

**What's NOT in v1.** Vector store, FTS5, graph layer, bi-temporal facts, cross-meeting connections — all Phase 2. The bright line is per-meeting extraction quality (v1) vs. cross-meeting intelligence (Phase 2). v1 doesn't add a single table; everything is additive JSON.

---

## 2. The team-context XML — the load-bearing change

The single most impactful change in v1: a per-team file giving the model domain priors and few-shot examples that it can't infer from a transcript alone. **For v1 the file is hand-authored as if it were exported from a future cohort-OS ingestion connector.** The connector itself is deferred (§9). The core pipeline doesn't care where the file came from; it reads it from a path.

### 2.1 What's in the file

```xml
<team_context>
  <team>
    <name>Shape Rotator Cohort</name>
    <domain>confidential AI infrastructure</domain>
  </team>

  <known_projects>
    <project name="Conclave" aliases="conclave">
      Cohort context intelligence layer running in TEE.
    </project>
    <project name="Phala" aliases="phala network,phala">
      Confidential compute network providing CVM (TEE) execution.
    </project>
    <project name="DStack" aliases="D-Stack,dstack">
      Stack for running TDX workloads.
    </project>
    <!-- … -->
  </known_projects>

  <known_technologies>
    <tech name="TDX" kind="standard">Intel Trust Domain Extensions</tech>
    <tech name="SGX" kind="standard">Intel Software Guard Extensions</tech>
    <tech name="TEE" kind="concept">Trusted Execution Environment</tech>
    <tech name="RATLS" kind="protocol">Remote Attestation TLS</tech>
    <tech name="MCP" kind="protocol">Model Context Protocol</tech>
    <!-- … -->
  </known_technologies>

  <known_topics>
    <topic>attestation</topic>
    <topic>reproducible builds</topic>
    <topic>context management</topic>
    <topic>cohort programs</topic>
    <!-- … -->
  </known_topics>

  <extraction_examples>
    <example>
      <chunk>
[Hang] Yeah, we want to get rid of TPM.
[Alex] OK, this also supports backwards compatibility for that.
[Hang] Right, we should remove the TPM dependency from the GCP variant.
      </chunk>
      <expected>
        {
          "summary": "Team decided to remove TPM dependency from the GCP variant, with backwards compatibility preserved.",
          "signals": [
            {"kind": "decision",
             "text": "Remove TPM dependency from the GCP variant",
             "source_quote": "we should remove the TPM dependency from the GCP variant",
             "said_by": ["Hang"],
             "about_person": []}
          ],
          "entities": [
            {"name": "TPM", "type": "technology", "evidence": "explicit removal target"},
            {"name": "GCP", "type": "org", "evidence": "deployment target for the variant being modified"}
          ],
          "topics": ["attestation", "platform compatibility"]
        }
      </expected>
    </example>
    <!-- 2-3 more examples, varied in shape: one action_item, one open_question, one with a Speaker N anonymous label -->
  </extraction_examples>

  <style_guide>
    <kind name="decision">A course of action the group agreed on. Past or present tense ("we decided", "let's go with").</kind>
    <kind name="action_item">A concrete next step someone agreed to do. Often "I'll send", "you handle", "can you".</kind>
    <kind name="open_question">A question raised in this chunk that is NOT answered within the same chunk.</kind>
    <kind name="insight">A non-obvious observation or learning. Use sparingly — prefer a more specific kind when one fits.</kind>
    <kind name="impactful_point">A consequential statement that doesn't fit decision/action/question but matters for prep. Use rarely.</kind>
  </style_guide>

  <open_world_note>
    The lists above are NON-EXHAUSTIVE. New projects, technologies, people (including guests joining a single meeting), and topics WILL appear in transcripts and must be extracted faithfully even when not listed here. Treat the lists as ANCHORS for known entities, not as a closed vocabulary.
  </open_world_note>
</team_context>
```

### 2.2 How it's consumed

- **New module:** `transcripts/team_context.py` — loads the XML once at process start, renders it to a single string fragment for splicing into prompts.
- **Path:** resolved from `CONCLAVE_TEAM_CONTEXT` env var. Default points to a worked example shipped at `transcripts/team_context.example.xml` (Shape-Rotator-cohort flavored) so the demo works out of the box.
- **Splice point:** between the security data-injection guard and the JSON contract in both `SINGLE_SYSTEM` and `CHUNK_SYSTEM` in `transcripts/prompts.py`. Format is roughly what the model sees — adopters reading the XML can predict what's in the prompt. Transparency = adoption.
- **Cached:** loaded once per process; `enrich_pending` doesn't re-read it per session.

### 2.3 Boundary commitment

The XML is a **STATIC curation artifact** the adopter maintains. It is NOT a snapshot of dynamic cohort-OS graph state, NOT a feed of "who's working on what right now," NOT a pull from a live API. The bright line:

- **OK to include** (and what the file is for): project names, technology vocab, topic taxonomy, style examples, open-world note. Facts the adopter explicitly hands the system as "this is what we work on."
- **NOT OK to include** (would break portability): current standings, recent decisions made in OTHER meetings, live progress trackers, individual status. That's Phase 2 graph-traversal territory and leaking it back into per-meeting extraction couples Phase 1 and Phase 2 in a way that breaks the "works for every team" property.

This boundary is what makes v1 portable: a new adopter writes their own XML, points `CONCLAVE_TEAM_CONTEXT` at it, and the system works. No code changes, no connector setup, no cohort-OS API binding.

### 2.4 Token budget

For `qwen2.5:7b` at `num_ctx=8192`:

- Team context priming: ~800 tokens (lists + 3 examples + style guide)
- System prompt + JSON contract: ~700 tokens
- Total priming: ~1.5K tokens
- Available for chunk: ~6K tokens

Matches existing `CHUNK_MAX_TOKENS=6000` in `transcripts/config.py` — no chunk-budget retuning required.

### 2.5 Multi-pass alternative — considered, deferred

Two-call extraction (entities first, signals second, with entities-from-pass-1 fed to pass-2) is a known pattern from Itext2KG (see `METHODOLOGY_SURVEY.md` §5). For our config it would push effective chunk budget below 4K per turn (carrying both the original chunk AND the previous output), and quality would likely regress. Defer unless rich single-pass plateaus.

---

## 3. Schema additions

All additive. JSON column on `transcript_sessions` already holds `metadata` and `derived` as serialized JSON, so no SQL migration required (per `IMPLEMENTATION_PLAN.md §D` and `§E`). Bump `ENRICH_PROMPT_VERSION` (see §7) so backfill picks up the new fields automatically via `enrich_pending`.

| Field | Where | Why |
|---|---|---|
| `Entity.type ∈ {... , "technology"}` | `transcripts/models.py` `Entity.type` + `transcripts/enrich.py` `_VALID_ENTITY_TYPES` + prompt entity-type vocabulary | Recovers an entire entity class currently dumped into `concept`. Observed misclassifications: TDX, SGX, RATLS, Opus 4.0, Whisper, Matrix, MCP, ATLS all tagged `concept` in real outputs. |
| `Signal.source_quote: Optional[str]` | `transcripts/models.py` `Signal` + prompt requirement + `transcripts/enrich.py` `_to_derived` + `_dedup_signals` | **Backend-only grounding.** Stored on Signal in v1 for simplicity. Never API-served (the C10 raw-leak guard in `tests/test_api_transcripts.py` still holds — `source_quote` is treated as raw-adjacent and gated alongside `raw_diarization`). Used for: dev-time spot-check ("does this extraction map to real text?"), eval QA, future debugging. **Sunset path:** future iteration will move `source_quote` (and raw-transcript references) into a separate evidence store linked to Signals by unique ID with time-bound retention so they auto-expire. See §9 for the forward design. |
| `Signal.said_by: list[str]` + `Signal.about_person: list[str]` (REPLACES `Signal.speakers`) | `transcripts/models.py` + prompt + `_to_derived` + `_dedup_signals` + `cli.render_markdown` + `api/transcripts_routes.py` `to_card` | Disambiguates "who spoke this turn" (`said_by`, speaker labels verbatim) from "who's the subject of the extracted point" (`about_person`, can be empty). Fixes the observed speaker-attribution drift in `tee-dstack-easytee-phala-transcript.txt` ("Alex flashbots will discuss with Kevin" attributed to `Hang` because Hang said the sentence). |
| `Entity.cohort_status: Literal["member", "external", "unknown"]` | `transcripts/models.py` `Entity` + `transcripts/enrich.py` `_dedup_entities` post-process (only for `type=person`) | Derived deterministically from `MOCK_DIRECTORY` (no LLM call) AFTER the dedup pass. `member` = matched roster; `external` = Person extracted but not in roster (Kevin, Alex from Flashbots, Hang); `unknown` = ambiguous parenthetical that didn't resolve. Powers dashboard chip styling (green / amber / grey) without runtime lookups. |
| `Entity.affiliation: Optional[str]` | `transcripts/models.py` `Entity` + `transcripts/identity.py` parenthetical handling + `_dedup_entities` | Captured from parenthetical labels ("Alex (flashbots?)" → `affiliation="flashbots"`) when the base name doesn't resolve to the roster. Useful for the dashboard: "external — flashbots". |
| `Derived.topics: Optional[list[str]]` | `transcripts/models.py` `Derived` + prompt extracts 3-6 per chunk + `transcripts/enrich._reduce` deterministic dedup (no LLM) | Separate from entities — topics are themes/areas ("attestation", "context management", "RAG"), entities are named things ("Phala", "Conclave"). Distinct in nature AND in dashboard role: topics filter the meeting list; entities populate chips on a meeting card. Reduce step: concat → lowercase → dedup → cap at 8. |

**Schema seam preserved.** All additions live in the JSON `metadata` / `derived` columns. The Phase-1.5 `visibility` / `owner` fields (already present per `IMPLEMENTATION_PLAN.md §D`) are unaffected. The bi-temporal / graph-edge shapes flagged in `METHODOLOGY_SURVEY.md §9` for Phase 2 are NOT added in v1.

---

## 4. Prompt overhaul

The current `transcripts/prompts.py` has good security and language guards but is zero-shot and loose on counts. v1 tightens:

- **Few-shot examples per signal kind.** 4 examples in `CHUNK_SYSTEM` covering decision / action_item / open_question / insight with the SAME speaker pattern so the model learns the CONTRAST, not just the labels. Comes from the `<extraction_examples>` block in the team context XML.
- **Decision-led summary style example.** Replace the current generic "what was actually discussed and decided" guidance with one concrete contrast — show one good summary ("Team decided to switch from RATLS to ATLS; agreed to use EZTE for reproducible builds; open question on Kubernetes migration") vs. one bland summary ("The conversation covered various topics including X, Y, Z") and label the latter as the anti-pattern to avoid.
- **Anti-hallucination rule.** Explicit: "If you are not confident about a person's name, term, or attribution, OMIT the entire item rather than guess. Never emit placeholder text like `<NAME>` or invent names not present in the transcript." Kills the observed `<NAME> (person)` placeholder in `dstack-hangout` and invented entities like `Tita (person)` and `near credits (person)`.
- **Transcription-fix policy.** "Only correct an obvious transcription error (e.g. 'Optus 4.0' → 'Opus 4.0') if the corrected term appears in `<known_technologies>` or `<known_projects>`. Otherwise preserve the surface form as-is." Avoids the model freelancing corrections.
- **One-line semantic definitions per entity type.** In the prompt:
  - `person` — an individual human
  - `project` — a named ongoing effort (codebase, product, initiative)
  - `technology` — a tool / library / protocol / standard / framework
  - `org` — a company or organization
  - `concept` — anything else (use sparingly)
- **Tighter signal-count guidance.** "Emit AT MOST 6 signals per chunk; prefer fewer high-quality ones over many bland ones."
- **Source-quote requirement on every signal.** "Every signal MUST include a `source_quote` field containing the verbatim text span (≤120 chars) from the chunk that the signal is extracted from. If you can't point to a specific span, don't emit the signal."

`REDUCE_SYSTEM` stays simple — summary-only merge as today, no change.

---

## 5. Identity layer fixes

`transcripts/identity.py` currently resolves only verbatim or simple-normalized matches against `MOCK_DIRECTORY`. Observed failures: Alex (flashbots?) → missed; Hang → missed; Wiki → missed; "Andrew Hang" (an invented merge of "Andrew Miller" + "Hang") → not caught downstream.

Three fixes:

- **Parenthetical handling.** `_normalize_name` strips parentheticals BEFORE roster lookup ("Alex (flashbots?)" → "Alex" → try roster). If no match on the base name, the parenthetical content is retained as an **affiliation hint** stored on the resulting Person entity (`affiliation="flashbots"`, see §3) so external mentions carry context.
- **External-person tracking.** When the LLM extracts a Person whose name doesn't match the roster:
  - Currently: silently kept in the entity list with no status.
  - v1: stamped `cohort_status="external"` post-dedup. Affiliation preserved if available. The dashboard can render external mentions distinctly (grey chip vs. green).
- **Speaker-label ↔ Person-entity linkage.** When a Person entity's name matches a session's speaker label (verbatim OR after `_normalize_name`), link them: populate `said_by` on signals where this Person appears as the subject, so the dashboard can chip-link "Alex said this" → speaker turn.

`MOCK_DIRECTORY` loading from `external/shape-rotator-os/cohort-data/people/*.md` stays as-is (per `IMPLEMENTATION_PLAN.md §G2`).

---

## 6. Dedup tightening

`transcripts/enrich.py` `_normalize_for_dedup` is currently `" ".join(s.lower().split())` — whitespace-collapse only. Observed failure: `Flashbots (org)` and `Flash Bots (org)` both stored, no merge.

Extended normalization:

- Lowercase + whitespace-collapse (current)
- PLUS strip internal spaces ("Flash Bots" → "flashbots")
- PLUS strip light punctuation (`.`, `,`, `'`, `"`)
- Optional Levenshtein-1 merge gated behind `STRICT_DEDUP=false` env (off by default to avoid surprise merges of legitimate distinct entities like "Sam" / "Sami")

When duplicates collapse, the `evidence` strings from all surface forms are joined with `"; "` (current behavior, kept).

When `cohort_status` differs across duplicates (e.g., one says `external`, another says `unknown`), the more specific value wins (`member` > `external` > `unknown`).

---

## 7. Versioning + backfill

- **Bump `ENRICH_PROMPT_VERSION`** in `transcripts/prompts.py`: `"v1"` → `"v2"`. `enrich_pending` already keys backfill off this field via `store.list_pending(current_prompt_version)` (per `IMPLEMENTATION_PLAN.md §G7`). All previously-enriched sessions are now considered stale and will be re-enriched on the next `enrich --all` or `enrich --pending` run.
- **New `metadata.team_context_version: Optional[str]`** in `transcripts/models.py` `SessionMetadata`. Stamped by `enrich_session` with a short SHA-256 prefix (first 8 chars) of the loaded team_context XML body. Lets us A/B different XML versions across enrichment runs without conflating with prompt changes — answers DECISION_INPUTS open question §3 "team context versioning."
- **Re-run.** Once v2 prompts + XML are in place: `transcripts.cli enrich --all` over the existing 11 stored sessions to populate v2 derived. (Or `enrich --pending` if `only_stale=True` is sufficient.)

No model swap in v1 — `qwen2.5:7b` stays the default. If after re-enrichment quality still feels small, the next move is `qwen2.5:14b-instruct` (per the previous `bfd236b` ollama setup), but ON the new prompt + schema baseline so we can measure the model-swap delta cleanly.

---

## 8. Verification (no formal eval)

Per the **no-mass-annotation constraint** (1-2 transcripts max for ground truth) from `DECISION_INPUTS.md` §C and §H. v1 ships without an F1 eval set. Verification is side-by-side spot-check:

1. **Re-enrich** all 11 stored sessions with `transcripts.cli enrich --all`.
2. **Side-by-side compare** old-vs-new on 3 representative outputs (already in `transcripts/enriched-output/`):
   - `dstack-hangout-alex-shaw-lsdan-andrew.txt` — small / 1-chunk / discussion
   - `tee-dstack-easytee-phala-transcript.txt` — medium / 4-chunk / technical
   - `project-intros-agents-day-3-transcript-may-21.txt` — large / 5-chunk / project intros
3. **Pass/fail signals** (qualitative, all on the 3 above):
   - Signal `kind` distribution diversifies — not every signal is `insight`. Concrete target: at least 2 distinct kinds per session.
   - `Entity.type=technology` is populated for TDX / SGX / RATLS / similar tech terms.
   - `Entity.cohort_status` is populated for every Person entity.
   - No `<NAME>` placeholder, no invented entities like `Tita` or `near credits`.
   - No `Flashbots`/`Flash Bots` (or other same-name-different-spacing) duplicate pairs in entities.
   - `Signal.source_quote` is populated and anchors to actual transcript text.
   - `Signal.said_by` vs `about_person` are visibly distinct on attribution-shifted signals.
   - `Derived.topics` is populated with 2-6 sensible topic tags.
4. **Dashboard visual check.** Re-run `transcripts.cli serve` and confirm the dashboard renders the new fields cleanly — cohort_status as chips, topics as tags, source_quote NOT visible (backend-only per §3).
5. **Regression net.** `CONCLAVE_DISABLE_SCHEDULER=1 .venv/bin/python -m pytest -q --ignore=external --ignore=tests/test_interview_reflection_mcp.py` stays green. In particular:
   - `tests/test_transcript_pipeline.py` 7 legacy tests still pass (behavior preservation).
   - `tests/test_api_transcripts.py` raw-leak guard still passes — confirm `source_quote` is treated the same as `raw_diarization` and never appears in API responses.

If all five gates pass: v1 ships. If a regression appears, fix it in place (this whole section is one logical change — no commit-per-fix splitting required given v1 is already a single appended block).

---

## 9. What's deliberately OUT of v1

Reaffirms anti-scope from `BUILD_PLAN §L` plus this round's specific deferrals:

- **sqlite-vec, FTS5 retrieval, graph tables** — Phase 2. v1 doesn't add a single SQL table.
- **Cross-meeting entity dedup, entity canonicalization across sessions** — Phase 2. v1 dedups WITHIN a session only.
- **Real connector for `team_context.xml`** — v1 mocks the file. The future connector (cohort-OS export → XML) is a separate feature on the `§6 Connector roadmap` (per Change-set B §10 below).
- **Public exposure of `source_quote`** — backend-only in v1. Surfaced to the frontend only via an explicit future feature toggle, never implicitly.
- **The future evidence-store separation.** Forward-declared here, NOT built in v1:
  - **Shape:** `source_quote` and raw-transcript references move out of `Signal` (inline today) into a separate store, linked by unique ID. Probably a new `signal_evidence(signal_id, source_quote, raw_segment_ids[], retained_until)` table once we get there.
  - **Time-bound retention:** evidence rows carry a `retained_until` timestamp; a sweeper expires them on a configurable window.
  - **Three balanced properties:** (a) **non-permanent** — they sunset on a schedule, (b) **hidden by default** — not exposed in production UI/API, gated behind a feature flag, (c) **available for eval / QA / "prove the extraction isn't bogus" workflows** during the retention window.
  - **Migration plan, not a v1 design driver:** v1 schemas stay tight and inline. Richness pressure (e.g. expanding `Signal.text` to multi-sentence so insights survive evidence deletion) comes only when we actually tackle separation+retention as its own task. Until then, don't pre-bloat the schema.
- **Per-meeting-type variation in `team_context.xml`.** v1 uses ONE XML for the team across all meeting types (project-intros, workshops, 1-on-1s, hangouts). Split only if quality differs sharply by type after §8 verification.
- **Multi-pass extraction.** Deferred per §2.5.
- **Auto-promotion of frequently-seen new entities into the XML.** Hand-maintained for v1. Auto-promotion risks teaching the model its own past mistakes; defer until there's a clean eval loop.

---

## 10. Change-set B — targeted edits to `BUILD_PLAN.md`

> **Receiving Claude session:** apply these only AFTER completing the read → think → flag → discuss workflow in the top instructions block. Each row below is a targeted edit against the existing `BUILD_PLAN.md`. Flag any conflict (e.g. an existing `Phase 1.1`, an existing Cohort-OS connector row) before merging.

| Target | What to change |
|---|---|
| `BUILD_PLAN §1 Architecture` | Add the **team-context XML** as a new "skin" adapter alongside the existing graph adapter and source adapter in the architecture diagram. Treat it as an inbound *configuration* channel (not an ingest channel — distinguished from `sources.py` which is per-transcript). One additional ASCII box on the inbound-skin row, label something like "team_context.xml (adopter-supplied)". One-line caption: "domain priors + few-shot examples per team; preserves cohort-blind core." |
| `BUILD_PLAN §2 Compute model` | Add one line under "Tier A — single prompt everywhere (now)": "Team-context priming (no LLM) is spliced into the system prompt before the chunk — adds ~1.5K priming tokens, no extra LLM call." Make explicit that this is grounding, not a second pass. |
| `BUILD_PLAN §4 List B` | Add a new row (or extend existing ones): "Entity→node match: **viable-minimal NOW** = team_context.xml `<known_projects>` + `<known_technologies>` anchored via in-prompt list (auto-canonicalizes known entities, falls back to LLM extraction for unknown). Improve later = embeddings + LLM disambiguation per the existing Phase-2 plan." Also extend the "Speaker identity" row: "+ team_context.xml affiliation hints for parenthetical labels". |
| `BUILD_PLAN §5 Phases & deliverables` | Insert a new phase **between `Phase 1` and `Phase 1.5`** titled `Phase 1.1 — extraction-quality lift`. Scope = §3 / §4 / §5 / §6 / §7 of this v1 spec. "Done when: re-enriched sessions show diversified signal kinds, populated `technology` and `cohort_status`, no hallucinated placeholders, and the dashboard reads materially cleaner on the 3 reference transcripts (see §8 verification)." Do NOT renumber any existing phases. |
| `BUILD_PLAN §6 Connector roadmap` | Add a new row: \| Cohort-OS → team_context.xml export \| ingest \| future (after Phase 1.1) \| not started — adopter-supplied XML used as the mock \|. Place it logically (probably near the existing graph-match Cohort-OS row). |
| `BUILD_PLAN §7 Open questions` | Add two new open questions: (1) "team_context.xml refresh cadence — hand-maintained vs auto-promotion of frequently-seen new entities." (2) "Per-meeting-type variation — one XML or one per meeting type (project-intros vs workshop vs 1-on-1)?" |

That's the entire Change-set B. Six surgical edits across six sections.

---

## 11. Sources informing this v1 spec

This document is enriched by the prior two docs in the sequence:

- **From `METHODOLOGY_SURVEY.md`:**
  - **Itext2KG schema-guided extraction** (§5) informs the team-context-as-schema approach — known-ontology prompting beats open extraction at small scale.
  - **Anthropic Contextual Retrieval** (§4, candidate #7) informs the `source_quote` grounding pattern — anchor LLM output to source spans to reduce vague output and hallucination.
  - **D17 (skip GraphRAG community detection)** — still respected; cohort is too small for community summarization to be meaningful.
  - **D5 (stay SQLite)** — still respected; v1 adds zero tables.
  - **D14 (single-prompt over per-type)** — confirmed by the qwen2.5:7b context-budget math in §2.4.
- **From `DECISION_INPUTS.md`:**
  - **Most empirical-input categories sidestepped for v1:**
    - Categories A/B (data + roster audit) sidestepped because we're not over-tuning on the 13 transcripts — explicit constraint from the product owner.
    - Categories D/E (LLM capability + schema validation) reduced to 2-3 hand-authored worked examples in `<extraction_examples>` — respects the "no mass annotation" constraint.
    - Category F2 (cross-meeting entity recurrence) moot for v1 — we're not connecting yet.
    - Category C (user interviews) acknowledged as still-unfulfilled but doesn't gate v1 — the dashboard demo can move forward on extraction quality alone; user-interview-driven schema decisions come at Phase 2 design time.
  - **The "no mass annotation" constraint** shaped §8 verification (side-by-side spot-check, not F1 vs ground truth) and §2 (XML examples are hand-written but ONLY 2-3 of them).

---

> End of v1 improvements. Receiving Claude session: confirm you've completed the workflow at the top before merging Change-set A and Change-set B.
