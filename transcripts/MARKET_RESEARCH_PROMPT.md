# Strategic Market Scan — Cohort Context Intelligence

> Copy everything below the line into a fresh chat. It's self-contained: context, constraints, and the ask.

---

You are a pattern-recognition specialist. Decade of analyzing thousands of companies + investment theses. You're sharp at distinguishing fundamentals from hype, naming specific products instead of categories, and surfacing contrarian takes. Your output reads like a partner memo, not a McKinsey deck.

## THE BRIEF (our context — locked)

**What we're building:** "**cohort context intelligence**" infrastructure. We ingest a team's past conversations (meeting transcripts, 1-on-1s, workshops), enrich each into structured signal (summary + key bullets + entities), and — Phase 2 — connect them to the team's people/project graph to surface cross-meeting insights and **collaboration matches** ("who should talk to whom, and why").

**Design partner:** the Shape Rotator cohort (in-person AI/crypto accelerator, ~60 people, 10 weeks). First demo: per-meeting summary + bullets dashboard over ~13 real workshop transcripts. Headline value arrives in Phase 2: cross-meeting connections + meeting-prep briefs + organizer NL queries.

**Hard constraints (load-bearing — protect these):**
- **Confidential by design.** Core runs inside a TEE (Phala / NearAI confidential compute); raw transcripts never leave the enclave; only bounded/derived/confirmed data exits.
- **Declared-only graph.** No surveillance / inferred edges. Insight surfaces as "confirm-to-declare" suggestions to the person, never auto-created edges.
- **Core-vs-skin generalizable.** Cohort-specific stuff (graph source, ingest source, transport, theme) lives behind adapters. The core works for any team/org with meetings and a roster.

**Anti-positioning (we are explicitly NOT):**
- a generic meeting note-taker (Otter, Fireflies, Granola)
- a CRM or sales-pipeline tool
- a real-time / in-meeting assistant
- a personality / hiring evaluation tool

**Differentiators (working hypotheses, challenge them):** TEE/confidential posture · declared-edge consent model · cohort/team-scoped rather than personal · integration with an existing manually-curated people/project graph · generative visual identity surface.

**Current state:** Layer-1 transcript pipeline built (parse → enrich → store, 7 tests green). Phase 1 = stylized dashboard over real cohort transcripts. Phase 2 = entity→graph matching, cross-meeting relations, collaboration suggestions.

## YOUR JOB — TWO PASSES, IN ORDER

### PASS 1 · Competitive / adjacent landscape (name names, not categories)

For each segment below, give me **5–15 specific products** with: *who · what (1 sentence) · business model · traction signals (funding, users, GH stars where public) · what they do well · structural weakness · one-line differentiator we have against them.*

1. **Transcript intelligence / meeting summarization** — Otter, Fireflies, Granola, Read.ai, Fathom, Tactiq, Modjo, Sembly, Avoma, Gong, Chorus, Spinach, Krisp Notes, …
2. **Team/org knowledge graphs over conversations** — Glean, Mem, Reflect, Heyday, Personal.ai, Notion AI, Coda Brain, …
3. **Collaboration / serendipity / "who-should-talk-to-whom"** — Donut, Lunchclub, Hatch, FlowerWork, internal-tool patterns (Linear's "who to ping"), Tandem, academic work on team formation, OpenAI's people-finder experiments, …
4. **Confidential AI / TEE document processing** — Apple Private Cloud Compute, Anthropic Constellation, Edgeless, Decentriq, Opaque Systems, Phala/Oasis/Marlin offerings, NearAI, Cape Privacy, …
5. **Cohort/accelerator OS** — YC Bookface, On Deck tools, Recurse Center pairing stream, Antler, EF, a16z platforms, university accelerators' bespoke stacks, …
6. **Voice/audio capture-to-graph (the wearables wave)** — VoxTerm itself, Plaud, Bee, Friend.com, Limitless, Rabbit, Tab, Heyday Memory Capsule, WhisperKit-based local tools, …
7. **Agent context engines / personal-memory infra** — Letta, Mem0, LangMem, Zep, MCP-based personal AI patterns, Pinecone Agent, AgentOps, …

If you have web search, use it — note sources. If you don't, lean on what's verifiable from training and flag confidence.

### PASS 2 · STEEP scan (12–36 month horizon, scoped to OUR slice)

For each dimension, give 3–5 **megatrends**, each broken into **subtrends** scored **Impact 1–5 · Time {Now / Next 12-24mo / Novel 24+mo} · Confidence {H/M/L}** with 2–3 pieces of evidence each.

- **SOCIAL** — always-recording norms vs. backlash; AI fatigue; consent / privacy expectations; how cohort + team behavior is shifting.
- **TECHNOLOGICAL** — local/edge LLM cost curves; confidential GPU TEE maturity; embedding inversion / privacy attacks; MCP & agent protocols; voice diarization advances; long-context windows.
- **ECONOMIC** — where capital is flowing in this slice (AI meeting tools, knowledge-graph startups, TEE infra); business models commoditizing vs. defensible; per-seat ⇄ per-org ⇄ infra plays.
- **ENVIRONMENTAL** — skip unless something genuinely matters here.
- **POLITICAL** — EU AI Act for ambient capture; biometric-data rules (voiceprints); US/state recording-consent law; emerging AI-act enforcement; data-residency.

## DELIVERABLES

1. **Landscape map** — table: segments × products × one-line "vs us" differentiator.
2. **Top 10 deep-dive briefs** — the products closest to us. Each: *why-now · evidence · customer impact · what they do well · structural weakness · what makes us different · what we'd steal from them.*
3. **STEEP trend radar** — table sorted by impact × time, with the **5 trends that most shape *our* play.**
4. **Honest positioning audit:**
   - Where we're *uniquely* positioned (moat candidates).
   - Where we're *vulnerable* / who could eat us (incumbents with distribution, OS-vendors going local-first, etc.).
   - **3 contrarian takes** — what would make our entire thesis wrong.
5. **30/60/90-day test plan** — 5 concrete experiments against real cohort users to validate (or *kill*) parts of the thesis. Each with *hypothesis · method · success metric · kill criterion.*

## QUALITY BAR

- **Specific products by name**, not categories. "Otter / Fireflies / Granola" beats "AI meeting tools."
- **Evidence:** URLs, funding amounts, user counts, GH stars — where you have them. Flag confidence otherwise.
- **Distinguish fundamentals from hype.** Vendor marketing claims ≠ traction.
- **Flag where we're behind**, not just ahead. The honest assessment is the valuable one.
- **No "AI is important"** — analyze the slice, not the planet.
- **Match recommendations to time horizon.** A Novel trend is a watch, not a build.
- **State the contrarian.** For every "we should…" surface a "but actually maybe…"

## GO

Pass 1 first (landscape + top-10 deep dives). Then Pass 2 (STEEP). Then synthesis (positioning audit + tests).

Don't pad with strategy fluff. If a section's honest answer is short, keep it short.
