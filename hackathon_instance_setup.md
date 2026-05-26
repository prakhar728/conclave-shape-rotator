# Conclave instance setup — Solana Frontier 2026

Copy-paste fields for the operator setup form at `/setup`. Each section
below maps to one input on the form.

> **Note on tracks:** the Solana Frontier Hackathon (Apr 6 – May 11, 2026,
> presented by Colosseum) doesn't publish thematic tracks — only prize
> categories (Grand Champion, Public Goods, University, 20 Standouts).
> The 6 tracks below are an organizer-imposed *thematic* framing on top
> of Frontier's open format, used so Conclave's track-alignment scoring
> has meaningful axes to score against. Replace or trim if running a
> different shape of hackathon.

---

## Hackathon name

```
Solana Frontier 2026
```

## End date

```
2026-05-11T23:59:00Z
```

## Evaluation frequency

For local testing, run frequent ticks so you can iterate fast:

```
30m
```

For a real instance, weekly is more appropriate:

```
1w
```

---

## Tracks

Six tracks. For each, paste the **Name** into the track-name field and
the **Description (markdown)** block into the description field.

---

### Track 1

**Name**

```
DeFi & Capital Markets
```

**Description (markdown)**

```markdown
# DeFi & Capital Markets

Projects that move on-chain capital: lending, borrowing, derivatives,
spot/perps DEXes, real-world asset markets, structured products,
prediction markets, and yield infrastructure.

## Strong fits
- Novel primitives that change the shape of who can lend/borrow/trade,
  not yet another fork of Aave or Uniswap.
- New asset classes brought on-chain (T-bills, private credit, RWAs,
  carbon, etc.) with a credible custody and settlement story.
- Capital-efficiency innovations (cross-margining, undercollateralized
  credit with verifiable income, intent-based execution).

## Weak fits / out of scope
- Memecoin launchers, copy-trading bots, or basic AMMs without a
  defensible thesis.
- Centralized OTC desks dressed up with a Solana frontend.

## What we look for
Originality of the financial primitive, defensibility of the moat,
realistic path to users, and Solana-native architecture (e.g.
parallelization, cheap blockspace, fast finality used as a feature).
```

---

### Track 2

**Name**

```
Infrastructure & Tooling
```

**Description (markdown)**

```markdown
# Infrastructure & Tooling

Layer-zero of the Solana stack: validators, RPC, indexing, devtools,
SDKs, debugging, security tooling, account abstraction, MEV
infrastructure, cross-chain messaging, and protocol research.

## Strong fits
- Tools that meaningfully shrink the time from "Solana newcomer" to
  "shipping app developer."
- Indexers, RPC patterns, or compute layers that unlock workloads not
  feasible today (zk verification, MEV redistribution, rollup data
  availability).
- Security-first contributions: formal verification, fuzzing, audit
  tooling, transaction simulators.

## Weak fits / out of scope
- Wrappers around existing tools that don't add new capability.
- General DevOps tooling not specific to Solana or crypto.

## What we look for
Whether the tool removes a real point of friction we hear developers
complain about; whether the team has the technical depth to maintain it;
whether other teams could plausibly depend on it post-hackathon.
```

---

### Track 3

**Name**

```
Consumer & Mobile
```

**Description (markdown)**

```markdown
# Consumer & Mobile

Apps a non-crypto-native user would want to use: wallets, social,
gaming, content, creator tools, marketplaces, identity, and payments
disguised as normal-feeling consumer flows.

## Strong fits
- Designs that hide the wallet entirely (passkeys, embedded wallets,
  abstracted gas).
- Mobile-first builds that earn day-2 retention through utility, not
  speculation.
- Novel social or content primitives that require Solana's cost/speed
  characteristics — a normal SaaS app doesn't qualify just because it
  emits a token.

## Weak fits / out of scope
- "Web2 app + token" without a real reason for the token.
- Generic NFT marketplaces or Twitter clones.

## What we look for
A clear "why crypto" answer that doesn't reduce to airdrops. UX
quality matters more here than technical novelty — a great UX with a
modest underlying mechanism beats a clever mechanism with hostile UX.
```

---

### Track 4

**Name**

```
DePIN & Real-World Assets
```

**Description (markdown)**

```markdown
# DePIN & Real-World Assets

Decentralized physical infrastructure: sensor networks, energy,
telecom, compute, storage, mobility, environmental monitoring, and
verifiable real-world data feeds. Also covers tokenized RWAs that need
verifiable proofs of off-chain state.

## Strong fits
- Hardware-backed protocols where on-chain incentives produce
  measurable real-world outputs (kWh generated, square meters mapped,
  PM2.5 readings collected).
- Designs that handle the verification problem honestly — anti-spoofing,
  cross-validation, signed sensor readings, TEE-attested measurement.
- RWA projects with credible custody, audit, and redemption pathways.

## Weak fits / out of scope
- "Map of nodes" without a working hardware spec or an incentive design
  beyond block rewards.
- Tokenized "real estate" without legal structuring or off-chain
  enforcement.

## What we look for
Evidence the hardware works (BOM, photos, telemetry from a single
node), a coherent reward/slashing economy, and at least one credible
data buyer or use case for the network's output.
```

---

### Track 5

**Name**

```
AI Agents & Automation
```

**Description (markdown)**

```markdown
# AI Agents & Automation

Autonomous agents transacting on-chain: agent payments, agent
identity, agent-to-agent commerce, intent execution, MEV agents, on-chain
ML inference, verifiable inference (zkML), and agent infrastructure.

## Strong fits
- Agents that own assets, sign transactions, and produce verifiable
  records of why a decision was made.
- Solana-as-substrate-for-agents arguments: the agent needs cheap
  compute, fast finality, or parallelism that other chains can't
  provide.
- zkML / TEE-attested model inference that lets a third party verify
  what model produced an output.

## Weak fits / out of scope
- "ChatGPT wrapper that mints an NFT."
- Off-chain agents that touch Solana incidentally as a payment rail.

## What we look for
Whether the agent's reasoning loop and actions are verifiable; whether
the project takes adversarial agent behavior (sybils, prompt injection,
manipulated inputs) seriously; whether there's a real economic loop the
agent participates in.
```

---

### Track 6

**Name**

```
Public Goods & Open Source
```

**Description (markdown)**

```markdown
# Public Goods & Open Source

Projects that primarily benefit the broader Solana / crypto ecosystem
rather than the team building them: open-source tooling, libraries,
educational resources, retroactive funding mechanisms, governance
research, and protocol-neutral infrastructure shipped under permissive
licenses.

## Strong fits
- Open-source code that other teams in the cohort could plausibly
  depend on within 90 days.
- New funding mechanisms (retro PGF, quadratic, attestation-based
  reputation) with on-chain enforcement.
- Educational / onboarding resources that materially lower the cost of
  shipping on Solana for a specific audience (e.g. mobile devs,
  university students, ML researchers).

## Weak fits / out of scope
- Closed-source projects that simply emit a token.
- Documentation rewrites of existing tools without new capability.

## What we look for
A permissive license, a credible maintenance plan, and evidence the
artifact is genuinely usable by parties other than the original team
(forks, dependents, docs that don't assume internal knowledge).
```

---

## Quick paste reference

If your operator UI takes one big JSON blob instead of per-field
inputs, here's the same content as a single payload (matches the
backend's `POST /instances` body):

```json
{
  "name": "Solana Frontier 2026",
  "end_date": "2026-05-11T23:59:00Z",
  "evaluation_frequency": "30m",
  "tracks": [
    { "name": "DeFi & Capital Markets",       "description_markdown": "..." },
    { "name": "Infrastructure & Tooling",     "description_markdown": "..." },
    { "name": "Consumer & Mobile",            "description_markdown": "..." },
    { "name": "DePIN & Real-World Assets",    "description_markdown": "..." },
    { "name": "AI Agents & Automation",       "description_markdown": "..." },
    { "name": "Public Goods & Open Source",   "description_markdown": "..." }
  ]
}
```

(Inline the markdown blocks above into each `description_markdown`
field.)
