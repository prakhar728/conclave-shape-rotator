# Conclave — Pitch Context

> **Purpose of this file.** Self-contained handoff for a chat that's
> writing pitch material (deck, narrative, landing page, investor memo,
> etc.). Read this end-to-end and you have everything you need without
> diving into the codebase. Not a spec; not a roadmap; a pitch primer.
>
> **Not committed.** Local-only working doc.

---

## 1. The name and the line

**Conclave.** *(noun — a private meeting of people with shared purpose; cf. the Catholic conclave that elects the Pope.)* The name carries: closed-door, in-group, confidential, decisive.

### One-liner candidates (pick one to lead with)

| Angle | Line | Best for |
|---|---|---|
| Compounding value | **Conclave turns your team's conversations into a private knowledge graph that compounds with every meeting.** | Cohort / investor pitch — "why bother" + "why this scales" in one go |
| Two-layer extraction | **A confidential intelligence layer over your team's conversations — structured per meeting, connected across them.** | Technical audience — pipeline-shape, engineers parse it immediately |
| Anti-positioning vs read.ai | **What read.ai is to one meeting, Conclave is to your team's entire history — confidentially.** | When read.ai is already in the conversation |

### Tagline (under-logo, 4 words)

> **Your team's compounding memory.**

### Working sub-line that ties product → mechanism → moat
> Conclave reads every conversation your team has, extracts the action items, open questions, and notable insights, links them to the people and projects they reference, and serves the result as a private, queryable layer that gets smarter with every meeting — all inside a hardware-enforced confidential compute enclave.

---

## 2. What Conclave is, in 3 sentences

1. **What:** A confidential intelligence layer for teams that turns past conversations (Zoom, Meet, in-person, VoxTerm, etc.) into a structured, queryable, connectable knowledge graph over the team's people and projects.
2. **Who:** Cohorts, accelerators, research groups, small companies, builder communities — anywhere a small group is doing focused work together over weeks-to-months and producing dozens of conversations whose collective context is the actual asset.
3. **Why:** Because the structured connections between meetings — who said what about whom, which projects intersect, where the open questions sit, who committed to what — is the asset that compounds across a team's lifetime. Per-meeting notes (read.ai, Gong) capture the leaves; Conclave grows the tree.

---

## 3. The problem

Every team produces a torrent of conversations:
- Stand-ups, design reviews, office hours, hangouts, 1-on-1s, demo sessions
- Each conversation contains commitments, open questions, technical decisions, named projects, named people
- Today these vanish into private notes, Slack scrollback, or per-meeting transcript files nobody opens twice

**The information exists; the structure doesn't.** A new member asks "what's been decided about X?" and the team has to remember. A founder prepping for a 1-on-1 with someone they last spoke to in March can't be reminded of what was committed then. A coordinator trying to match collaborators can't see who's hitting the same primitive across projects.

Read.ai-style tools improve the per-meeting artifact (cleaner summary, better action items). But they don't connect meetings to each other. They have no model of the team — its people, its projects, its technologies, its topics. The artifact is per-meeting prose, not a graph.

**Conclave is the connective tissue.** Same transcripts in; structured records + cross-meeting links out.

---

## 4. The product

### What's built today (Phase 1 — flashy MVP, demo-ready)

A dashboard the cohort opens, identifies themselves on, and immediately sees:

- **12 real cohort transcripts** ingested, enriched, and rendered.
- Per session: **summary** + **action items** + **open questions** + **insights** + **entities** (people / projects / technologies / concepts / orgs with cohort-status chips) + **topics**.
- Click any card → full per-meeting detail page (hash-routed SPA).
- **Identity picker** on first visit: select yourself from the roster (members + speakers across all sessions, deduped). Choice persists in localStorage; every API call threads `?viewer=<record_id>`.
- **Personal action-items queue** at `#/me/action-items` — every commitment where you're the actor or addressee, across every session you can see.
- **Permission layer** (Phase 1.5 demo-hardcoded): `visibility: cohort` (default, everyone sees) or `owner-only` (owner + speakers see). Owner can flip via in-dashboard toggle.
- **Stylized rendering**: shape-ui glyphs per session (cohort-specific theme, replaceable), dark editorial type, decision-led summary style, three color-coded signal sections.
- **Confidential by design** posture: runs inside a Phala CVM (TEE); LLM calls go to RedPill (Phala TEE-served Gemma 3 27B). Raw diarization is **write-once, never API-served** — the C10 raw-leak guard is a load-bearing privacy assertion enforced in tests.

### What's planned (Phase 2 — the connect payoff)

- **Cross-meeting relations** — shared-entity / shared-topic co-occurrence first; embedding similarity later. "Who else has been working on attestation across the cohort?" → graph of sessions linked by shared entities.
- **Meeting-prep briefs** — "before your meeting with X, here's the relevant context from past sessions." Single LLM pass over retrieved context.
- **Organizer NL query** — agentic loop. "Who's available to mentor confidential compute work next week?" → grounded answer with citations.
- **Collaboration matching** ⭐ — the cohort-orchestrator's headline. "X's project and Y's project converge on the attestation seam; they should talk." Hybrid tag + embedding matcher.
- **Real-time suggestions** (future vertical) — during a meeting, surface relevant past context as it's spoken.

### Open verticals (parallel, un-gated)
- **Personality + collaboration affinity** — modeling members along axes the team can self-report, not just behaviorally inferred.
- **Coachability and interview reflection** — assessing growth, not just output.

---

## 5. The unique angle vs everything else

### vs read.ai / Otter / Gong / Fireflies
| Dimension | Them | Conclave |
|---|---|---|
| Unit of value | One meeting | The team's entire history |
| Output shape | Prose summary + action items | Structured signals + entities + cross-meeting graph |
| Privacy model | Cloud SaaS; vendor sees raw | Hardware-enforced confidential compute; vendor never sees raw |
| Team model | None — just per-meeting + per-user | Explicit people/project graph; cohort_status; affiliation |
| Cross-meeting reasoning | None | The product |
| Connectivity | Slack/email integrations | Same + extensible graph layer for downstream agents |

### vs "I'll just dump transcripts into ChatGPT"
- ChatGPT has no model of the team. Conclave's `team_context.xml` carries 26+ projects, 28+ technologies, 30+ topics, 9 lesson-bearing few-shot examples — the cohort's domain prior, hand-curated.
- ChatGPT can't reason across sessions without re-uploading them. Conclave stores structured derived state and serves it via API; downstream agents query the graph, not the transcripts.
- ChatGPT leaks the transcript to OpenAI. Conclave runs in a TEE; raw never leaves the enclave.

### vs "we'll just build it ourselves on top of Whisper + an LLM"
- The schema is the hard part. Action_item vs decision vs insight definitions, said_by vs about_person discipline, source_quote audit trail, cohort_status / affiliation — these are months of iteration, captured.
- Anti-default prompt engineering. The model wants to default to "insight" on every signal; the prompt has to actively guard against that. Same for action_item triggers calibrated to actual cohort talk (exploratory, not transactional).
- Entity canonicalization + open-world extraction without anchor-list bias. The prompt has to encourage extracting unanchored entities (competitors, off-cohort tools, guest speakers' work) while still canonicalizing known ones.
- Re-enrichment / backfill semantics. Every prompt change has a version stamp; sessions tagged with older versions become "pending" on the next run. Forward and backward.

---

## 6. How it works (pitch-friendly)

```
  raw transcript files  →  ingest  →  identity-link  →  enrich (LLM in TEE)  →  store  →  dashboard / API
       (Zoom/Meet/                   (mock cohort-OS                                        ↓
        Otter/VoxTerm)                lookup; speaker →           ┌──────────────────────────┐
                                      record_id)                  │ structured records       │
                                                                  │ - summary                │
                                                                  │ - action_items (3-kind   │
                                                                  │ - open_questions          schema, v2.2)
                                                                  │ - insights                │
                                                                  │ - entities (cohort_status)│
                                                                  │ - topics                 │
                                                                  │ - source_quotes (audit)  │
                                                                  └──────────────────────────┘
                                                                              ↓
                                                              (Phase 2) cross-meeting graph
                                                              (Phase 2) meeting-prep briefs
                                                              (Phase 2) organizer NL query
```

**One LLM call per chunk; map-reduce when the transcript exceeds chunk budget.** Reducer merges only the summary; entity dedup, signal cap, topic dedup happen deterministically (no second LLM call).

**Storage = SQLite for Phase 1**, per the build plan's "small scale, hundreds of sessions per cohort" assumption. Vector index added alongside (not replacing) when embedding retrieval lands.

**Substrate**: Gemma 3 27B via RedPill (Phala TEE). ~$0.04 per 1M input tokens; the full 12-session cohort corpus enriches for ~$0.02. Cheap enough that re-enriching the whole corpus when the prompt changes is a feature, not a cost.

---

## 7. The confidentiality story

This is the pillar of differentiation, and the story has three layers:

1. **Hardware enclave (TEE).** The whole core runs inside a Phala CVM with TDX attestation. The substrate provides a hardware root of trust; the host machine operator cannot read process memory or storage.
2. **LLM calls stay in TEE.** RedPill is a Phala-affiliated TEE-served inference endpoint. The transcript text spliced into the prompt never leaves the enclave perimeter.
3. **Raw never API-served.** The `raw_diarization` field is write-once at ingest. Every API response strips it deterministically — there's a `tests/test_api_transcripts.py` regression assertion enforcing this. The dashboard receives `summary + signals + entities + topics` only; the full transcript text stays inside the enclave's storage.

**The PII boundary is the TEE boundary, not the API field surface.** `source_quote` (≤120-char verbatim spans anchoring each signal) IS served — they're audit aids on the dashboard. The bulk transcript never is.

---

## 8. The cohort GTM hypothesis

Conclave is purpose-built for **cohort-shaped groups**: accelerators, research collectives, founder programs, hackathon residencies. Why this slice first:

- **High conversational density** — cohorts produce 10+ recorded conversations per week per member.
- **Shared graph** — small group of named people working on a small set of named projects; the entity vocabulary is dense and reused.
- **Time-bounded but compounding** — a 3-month cohort produces ~200 hours of conversation; the value of cross-meeting connections grows fast and matters most by month 2-3.
- **Existing organizer pain** — cohort coordinators are full-time on "who should talk to whom" / "what's everyone working on" already; Conclave is leverage for that role.
- **Adopter-supplied team_context** — the `team_context.xml` priors file is hand-authored per team for v1 (deferred to a Cohort-OS connector later); cohorts are organized enough to have someone curate it. Read.ai is calibrated for "anyone with a meeting" — Conclave is calibrated for "a team with a graph."

**Reference deployment.** Active build is for the **Shape Rotator cohort** — a ~50-person research/builder accelerator working on confidential compute, AI agent infrastructure, attestation, and adjacent topics. The cohort-OS people/project graph (`external/shape-rotator-os/cohort-data/`) is the live source for `MOCK_DIRECTORY` and the team_context anchor lists.

---

## 9. Adopter path / "how do I get this for my team"

This isn't yet a polished SKU; calibrate the pitch to "first design partner" or "early access" framing.

1. **Provide a team_context XML** — known projects, technologies, topics, and ideally 6-9 hand-picked example extractions from your transcripts. (Future: auto-generated from a Cohort-OS connector.)
2. **Drop transcripts** — Otter, Whisper, Zoom export, VoxTerm. Any speaker-attributed transcript format is parseable; new formats need a 30-line adapter.
3. **Run ingest + enrich** — deterministic ingest, then one map-reduce LLM pass per session. ~$0.02 per 100 hours of transcripts.
4. **Open dashboard** — your team identifies themselves on first visit, then sees structured records of everything they've said.

Phase-1.5 work adds real auth on top of the demo-hardcoded picker. Phase 2 adds cross-meeting reasoning + prep briefs. Phase 3 ships as a generic platform layer.

---

## 10. What it is NOT (anti-positioning, defuses common pushback)

- **Not a transcription service.** It eats transcripts; it doesn't make them. Stays substrate-agnostic.
- **Not a meeting summarizer.** Summaries are one of seven outputs; the structured signals + entities are the real product.
- **Not a personal AI assistant.** It's a team-scoped intelligence layer. There is no "talk to Conclave" chat; the data is the deliverable, queryable by people OR downstream agents.
- **Not a CRM / project management tool.** It doesn't replace Linear or Notion; it complements them with the conversational layer no PM tool has.
- **Not real-time today.** Phase 1 is offline / batch on completed transcripts. Real-time during meetings is a future vertical, gated behind real-time vs batch architecture decisions we haven't taken yet.
- **Not "yet another GPT wrapper."** The schema, the prompt iteration, the cohort priors, the TEE substrate, the cross-meeting graph layer — all are infrastructure choices not derivable from "wrap an LLM."

---

## 11. Demo flow (what to walk a viewer through)

1. **Open the dashboard.** Cards for 12 real cohort meetings — each with a generative glyph, date, source, model, attendees.
2. **First-visit picker pops up.** Pick yourself from the roster. (Beat: "no password, no login — for the demo. Real Phase 1.5 swaps this for an auth callback; signature of every API stays identical.")
3. **Cards now show YOU as the viewer.** Topic chips, summary, top 2-3 most important signals (action items prioritized).
4. **Click into a card → detail page.** All sections rendered: action items (with conditional triggers preserved), open questions, insights, entities with cohort-status chips, topics.
5. **Open "my queue" in the masthead.** Every action_item across the cohort where you're implicated — said_by or about_person.
6. **(If owner of any session)** flip "hide from cohort" → "owner-only" and demonstrate the visibility change.
7. **End on the open question:** "this is per-meeting today. Phase 2 connects these across meetings — `shape-rotator-project-map` and `friday-shaw-greg` reference 'attestation' together. The graph layer makes those into a relationship."

---

## 12. Status of the build (honest)

### Shipped, demo-ready
- Phase 0 core: parse → enrich → store → CLI (12 commits, fully tested)
- v1 schema + team_context XML splice point + 9 lesson-bearing examples
- v2.1 prompt iterations (open-world entity rule, conditional action_items)
- v2.2 schema collapse (5 kinds → 3: action_item, open_question, insight)
- Phase 1d dashboard (read-only, stylized, hash-routed SPA)
- Phase 1.5 demo-hardcoded permission layer (identity picker + can_see + viewer threading + visibility toggle + personal action-items queue)
- C10 raw-leak guard (regression-tested)
- ~300 tests passing, suite stays green at every commit

### Live caveats
- **Open question recall regressed in v2.2** (from 6/12 sessions in v2.1 to 2/12 in v2.2) — known, fixable with a v2.3 prompt tweak (5 lines).
- **Phase 1.5 permissions are demo-hardcoded.** Real auth is a 1-function swap (`_resolve_viewer`) but hasn't shipped.
- **No cross-meeting reasoning yet** — Phase 2c work. The schema and storage are ready for it.
- **No connectors yet.** Transcripts are hand-provided via `sources.py`. VoxTerm / Google Meet / Zoom connectors are documented in the build plan but not built.

### Substrate
- Gemma 3 27B via RedPill (Phala TEE) — production default
- qwen2.5:7b via Ollama — dev iteration substrate (kept for offline work)
- SQLite Phase 1; vector index alongside SQLite in Phase 2

---

## 13. References (where the body of work lives)

- **`transcripts/BUILD_PLAN.md`** — canonical phases, architecture, assumptions, success criteria.
- **`transcripts/IMPLEMENTATION_PLAN.md`** — v1 → v2 → v2.1 → v2.2 detailed change-sets, with rationale.
- **`PITCH_CONTEXT.md`** — this file.
- **`external/shape-rotator-os/cohort-data/`** — reference cohort graph (people, projects).
- **`enriched-output-prompt-v2.2-comparison.md`** — head-to-head comparison of v2 / v2.1 / v2.2 prompt outputs across all 12 sessions (gitignored; local only).
- **GitHub:** `prakhar728/conclave-shape-rotator` (branch `transcripts-phase1`).

---

## 14. Audiences and what each cares about

| Audience | What lands | What scares them off |
|---|---|---|
| Cohort members | "I can finally see what I committed to across 12 meetings" | Anything that says "we read your transcripts" without confidentiality framing |
| Cohort organizers | "Cross-meeting collaboration matching" + "who's stuck on what" | Setup pain. The team_context XML curation step needs to feel like 30 min, not a week |
| Investors | Compounding moat ("each conversation makes the graph richer"); TEE/confidentiality story; cohort GTM as wedge to broader teams | "Just another notetaker"; lack of a measurable retention metric yet |
| Engineering adopters | The schema + prompt iteration discipline; TEE substrate; queryable structured output | "Magic LLM output" without versioning, eval, or audit story |
| Privacy-conscious enterprises | TEE + raw-stays-in-enclave + C10 raw-leak guard | Vendor lock-in fear; needs clear self-host story |

---

## 15. Compounding-value story (for closing slides / memo)

The first session enriched is just a structured summary. The 100th session is when the **cross-meeting graph** outperforms a manual coordinator. The 500th session is when the **cohort's institutional memory survives departures** — anyone joining can reconstruct context from the structured record. The 1000th session is when a downstream **agent can answer questions an organizer would otherwise field manually**.

This is the asymptote of the pitch: Conclave isn't a meeting tool; it's the team's brain, accumulating over its lifetime, kept private.

---

## 16. Risks / objections + responses

| Objection | Response |
|---|---|
| "GPT can already summarize meetings" | "Yes — for one meeting at a time, with no model of your team. Conclave is the connecting layer GPT doesn't build for you, and it stays inside a TEE." |
| "Won't people stop talking freely if they know they're being recorded?" | Cohorts already record their meetings on Otter / Zoom. The question is whether the recording produces a structured asset or evaporates. Confidentiality is hardware-enforced; the substrate operator can't read it. |
| "What if the LLM gets things wrong?" | Every signal carries a verbatim `source_quote` anchor and a `said_by` attribution. Errors are auditable, not opaque. Prompt versions are stamped per row, so a wrong-prompt era is identifiable and re-enrichable. |
| "Why a TEE, isn't that overkill?" | For one team, maybe. For a multi-tenant deployment serving multiple cohorts, the TEE is what lets us promise customers each other's data is inaccessible — including to us. |
| "We're a 5-person team, we don't need this" | Then you don't. Conclave's sweet spot is 20-100 person cohorts producing 10+ recorded conversations per week. Below that, the graph doesn't compound. |

---

## 17. Voice / tone notes

- **Not breathless.** No "revolutionary" / "AI-powered" / "supercharge". The product is concrete; let the demo do the work.
- **Specific over general.** "12 real cohort meetings" beats "many meetings". "Gemma 3 27B via RedPill (Phala TEE)" beats "advanced AI in a secure environment".
- **Per-meeting → cross-meeting → agentic** is the architectural arc. Don't pitch agentic first; you'll lose the audience on overpromise. Pitch the per-meeting wins, hint at cross-meeting payoff, gesture toward agentic as the asymptote.
- **Confidentiality as posture, not feature.** "Built confidential" not "with industry-leading encryption." TEE is the substrate, not a checkbox.
- **Honest about what's not built.** Phase 2c isn't real yet; say so. Builds trust.

---

End of context. Open a new chat with this doc, ask for "draft a 5-slide deck" or "draft a one-page narrative for adopter outreach" or "tighten the one-liner to 8 words" — it has everything needed.
