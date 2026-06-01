# Conclave — Demo Page Script

> 60-70s walkthrough for the demo page. Three beats: intro → pipeline →
> dashboard tour. For the full live pitch (~7 min) see `PITCH.md`; for
> supporting context and audience framings see `PITCH_CONTEXT.md`.

---

## Time budget

| Beat | Time | Lands |
|---|---|---|
| 1. What Conclave is (2 lines) | 8s | Problem + product in one breath |
| 2. Pipeline — transcript → signals → knowledge base | 32s | The vision arc: extract today, query/derive/agentify tomorrow |
| 3. Dashboard tour | 22-30s | Cards → personal queue (skip detail page if tight) |

Total: ~62-70s. Plan for 60s of script + a few seconds of breathing room.

---

## Beat 1 — Intro (8s)

> "Conclave is a privacy-preserving knowledge base for async teams.
> Drop in any meeting transcript and your team can query everything
> that's ever been said — without the transcripts ever leaving a
> hardware enclave."

Names the wedge (async + private), the input (transcript), the output
(queryable KB), and the moat (enclave) — in one breath.

---

## Beat 2 — Pipeline (32s)

> "Here's what happens. A local transcript — from VoxTerm, Otter,
> Zoom, anything speaker-attributed — gets dropped in. Inside a Phala
> TEE, an AI workflow pulls out action items, open questions, insights,
> the people and projects mentioned, and short verbatim quotes
> anchoring each one. Those signals don't just render to the dashboard
> — they get written into a private knowledge base that grows with
> every meeting. Your team can query it later, derive new metrics from
> it, and let agents reason across it. The raw transcript stays in
> the enclave the whole time; only the structured signals ever come
> out."

### What the on-screen diagram should show during this beat

```
   ┌────────── inside the Phala TEE ──────────┐
   │                                          │
   │  transcript ─► [ AI workflow ] ─► signals│──► dashboard
   │  (VoxTerm,         │              │      │
   │   Otter,           ▼              ▼      │
   │   Zoom…)     ┌──────────────────────┐    │
   │              │  knowledge base      │    │──► future:
   │              │  (grows per meeting) │    │     · queries
   │              └──────────────────────┘    │     · metrics
   │                                          │     · agents
   └──────────────────────────────────────────┘
       raw never leaves        only structured signals out
```

Four labelled regions: input on the left, AI workflow in the middle,
knowledge base + dashboard outputs on the right, TEE boundary
wrapping the whole thing. The viewer's eye follows the script.

---

## Beat 3 — Dashboard tour (22-30s)

Three clicks, no more.

1. **Cards view** (8s) — *"12 real cohort meetings. Each card surfaces
   the top signals at a glance."*
2. **Click a card → detail page** (12s, optional) — *"Per meeting:
   summary, action items with who committed, open questions, insights,
   entities tagged cohort-known or external. Every signal carries a
   source quote."*
3. **Click "my queue"** (10s) — *"Across every meeting, every
   commitment where I'm implicated. You don't re-watch — you query."*

Close on the queue. The queue is the *"I want this for my team"*
moment for adopters; the cross-meeting graph is the moat for
investors. For a 60s demo page targeted at adopters, end on the queue.

### What to skip on the demo page

These are real Phase-1.5 features but each costs ~10s you don't have.
Save them for the live pitch:

- Identity picker on first visit
- Owner-only / cohort visibility toggle
- The query bar + agent trace

---

## Voiceover delivery notes

- **Normal speaking pace, not rushed.** If you can't say it in 60s
  without speeding up, cut a sentence — don't compress the delivery.
- **The pipeline beat is the load-bearing one.** The intro hooks, the
  dashboard substantiates, but the pipeline beat is where the *vision*
  lands — extract today, knowledge base tomorrow, agents next. Don't
  drop the "query later, derive new metrics, let agents reason across
  it" line. That's the whole arc.
- **Specifics over generalities.** "VoxTerm, Otter, Zoom" beats "any
  transcription tool." "12 real cohort meetings" beats "real data."
  Names earn trust.
- **Match the on-screen visual to the spoken word.** When you say
  "knowledge base that grows with every meeting," the diagram's KB
  box should highlight. When you say "raw stays in the enclave," the
  boundary should pulse. The viewer's pattern-matching does the work.

---

End of demo script.
