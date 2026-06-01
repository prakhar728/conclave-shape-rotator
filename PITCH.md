# Conclave — Pitch

> Delivery script for the live pitch. Read top-to-bottom; each section is a
> beat with an approximate time budget. Supporting context, alternative
> framings, objection responses, and audience matrices live in
> `PITCH_CONTEXT.md` — pull from there as needed, but this file is what
> gets delivered.

---

## 0. Shape of the pitch (~7 min)

1. Team intro — 15s
2. One-line on Conclave — 20s
3. The journey: how we got here — 90s
4. Signals: what people use today — 45s
5. Pain points with each — 90s
6. Consent law as a wedge — 30s
7. Demo on Albi's VoxTerm transcripts — 2-3 min
8. Why this week, why this cohort — 30s

---

## 1. Team intro (15s)

> "We're the team behind **Conclave, Prakhar & Parth**."

Names only. Let the credibility sit; don't oversell.

---

## 2. What we're building (one line, ungimmicky)

> "We're building **Conclave — a privacy-preserving AI workflow that lets
> members of an organization sync asynchronously.** Instead of pinging a
> teammate for the minutes of a meeting you missed, you ask Conclave —
> and you can also query the knowledge base across every past meeting:
> *what have we been working on the last three weeks? what came up in
> the last three Friday syncs?*"

---

## 3. How we got here — the journey (60-90s)

A sequence of decisions, not a story arc:

1. **Started with the NDAI paper with Andru.** Built a POC for a problem
   we personally felt: uploading hackathon ideas in an enclave to compare ideas with other projects for novelty: to drive project development without leaking anything about our idea to others, i.e. validation of novelty and alignment to the hackathon. That's where the TEE substrate came in.
2. **From week one, we asked: what else does this confidentiality
   primitive unlock for a cohort?** Not just hackathon submissions —
   anywhere a team produces sensitive signal that should stay private
   but still be useful.
3. **We followed the data.** The juiciest, densest signal in any team
   isn't documents or Slack — it's **transcripts**. Meetings that run
   for years, people joining, leaving, zoning out, taking partial notes.
   That's where the institutional memory leaks.
4. **So we picked transcripts as the data source** and worked
   backwards: what would a team actually want from a queryable, private
   layer over every conversation they've ever had?
5. *(Optional, drop if running long)* **Confidentiality wasn't bolted
   on** — it's the thread that connects the NDAA work to this.

---

## 4. Signals: people are already trying to solve this (45s)

> "Before building, we looked at what people actually use today. We saw
> two camps."

- **Local / private-leaning:** Granola, VoxTerm
- **Cloud bots:** Read.ai, Otter, Fireflies, Gemini meeting notes,
  Notion AI notetaker

> "Both camps have real adoption. Neither solves the problem."

Tee up the pain-points section by previewing the killer feature:

> "And one feature none of these even attempts — which we'll come back
> to — is letting a participant opt out of being recorded, or have
> their name redacted, just by saying so."

---

## 5. Why each falls short — the pain points (90s)

| Tool | Gap |
|---|---|
| **Granola** | Markets itself as private, but transcription is offloaded to a third-party cloud API. Also: recordings are typically captured without the other participants knowing — no in-meeting consent bubble. |
| **VoxTerm** | Runs a real model locally — but that requires a Mac powerful enough to host it, and it's Mac-only. No mobile story, no team story. |
| **Read.ai / Otter / Fireflies / Gemini notes** | Centralized. Transcripts sit on vendor servers. Even when the AI is good, the privacy posture is "trust us." |
| **All of them** | Scope = one meeting. None build a **shared, queryable knowledge base for the whole team.** None let a teammate ask *"what did infra decide last week?"* across meetings. |
| **Missing feature nobody offers** | A participant should be able to **say "don't record me" or "redact my name"** and the system should honor it automatically. |

---

## 6. Consent law as a wedge (30s)

Recording a meeting without consent isn't a stylistic concern — it's
illegal in named jurisdictions. The landscape, briefly:

- **United States — federal:** one-party consent (18 U.S.C. § 2511).
- **U.S. all-party consent states:** California (Penal Code § 632),
  Florida, Illinois, Massachusetts, Maryland, Montana, New Hampshire,
  Pennsylvania, Washington, Connecticut. Recording a meeting where
  **any** participant is in one of these states without all
  participants consenting is criminal and creates civil liability.
- **EU / UK:** GDPR Art. 6 + Art. 7 — voice is personal data; explicit,
  informed consent required. UK adds the Investigatory Powers Act.
- **Canada:** Criminal Code § 184 federally; PIPEDA for commercial
  contexts.
- **Australia:** state-by-state Listening / Surveillance Devices Acts;
  most are all-party consent.

One line for the slide:

> *"In California, Illinois, Florida, the EU, the UK, and most of
> Australia, recording a meeting without every participant's consent is
> illegal. Most notetaker bots punt this to the user; Granola sidesteps
> the consent bubble entirely. Conclave makes per-speaker opt-out and
> name redaction a first-class feature."*

---

## 7. Demo (2-3 min)

> "Here's what's running today, built on real VoxTerm transcripts from
> **Albi**."

Walk through:

1. **Dashboard** — 12 sessions, generative glyphs, structured signals
   per card.
2. **Identity picker** — "demo stand-in for org SSO; signature of every
   API stays the same when real auth lands."
3. **Click a card → per-meeting detail** — action items, open
   questions, insights, entities with cohort-status chips, source
   quotes.
4. **The query bar** — *"what's open on attestation this week?"* →
   agent decides graph vs embeddings, returns grounded answers with
   citations. Show the trace; the *decision* is the demo.
5. **Personal queue** — every commitment across every session where
   you're the actor or addressee.
6. **Owner-only visibility toggle** — the per-speaker privacy primitive
   in action.

---

## 8. Why this week, why this cohort (30s)

> "We have a working demo on real cohort data. The Shape Rotator
> cohort is the ideal feedback loop — high meeting density, named
> people, named projects, real privacy stakes. One week of focused
> work here closes the gap between the demo and a system the cohort
> actually depends on."

Ask: *[design-partner status / time on cohort calendar / funding —
fill in based on audience].*

---

## Delivery notes

- **Drop the optional line in §3** ("confidentiality wasn't bolted on")
  unless the room is technical and asks "why TEEs." Tangent in a
  non-technical room; goldmine in a technical one.
- **Name redaction by voice is your most memorable single beat.** No
  competitor has it. The §4 tee-up + §5 callback + closing the demo on
  the visibility toggle makes the audience remember this one thing
  above everything else.
- **Vision before product.** Sections 2-6 are the vision and the
  market case. The demo (§7) substantiates it — it does not define it.
  Resist any urge to lead with "here's what we built."
- **Specifics over generalities.** "12 real cohort meetings," "Gemma 3
  27B via RedPill (Phala TEE)," "Albi's VoxTerm transcripts" — every
  proper noun is worth more than an adjective.

---

End of script. For audience-specific framings, objection responses,
and alternate one-liners, see `PITCH_CONTEXT.md`.
