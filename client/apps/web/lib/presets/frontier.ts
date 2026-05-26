/**
 * Solana Frontier 2026 prefill — copy of the fields documented in
 * /hackathon_instance_setup.md. Used by the dev-only "Prefill" button on
 * /setup so the operator-creation flow can be exercised end-to-end without
 * pasting six long markdown blocks every time.
 */
import type { TrackConfig } from "@/lib/types"

export interface FrontierPreset {
  name: string
  end_date: string  // datetime-local format (YYYY-MM-DDTHH:mm)
  evaluation_frequency: string
  tracks: TrackConfig[]
}

const FRONTIER_END_DATE_LOCAL = "2026-05-11T23:59"

export const FRONTIER_TRACKS: TrackConfig[] = [
  {
    name: "DeFi & Capital Markets",
    description_markdown: `# DeFi & Capital Markets

Projects that move on-chain capital: lending, borrowing, derivatives, spot/perps DEXes, real-world asset markets, structured products, prediction markets, and yield infrastructure.

## Strong fits
- Novel primitives that change the shape of who can lend/borrow/trade, not yet another fork of Aave or Uniswap.
- New asset classes brought on-chain (T-bills, private credit, RWAs, carbon, etc.) with a credible custody and settlement story.
- Capital-efficiency innovations (cross-margining, undercollateralized credit with verifiable income, intent-based execution).

## Weak fits / out of scope
- Memecoin launchers, copy-trading bots, or basic AMMs without a defensible thesis.
- Centralized OTC desks dressed up with a Solana frontend.

## What we look for
Originality of the financial primitive, defensibility of the moat, realistic path to users, and Solana-native architecture (e.g. parallelization, cheap blockspace, fast finality used as a feature).`,
  },
  {
    name: "Infrastructure & Tooling",
    description_markdown: `# Infrastructure & Tooling

Layer-zero of the Solana stack: validators, RPC, indexing, devtools, SDKs, debugging, security tooling, account abstraction, MEV infrastructure, cross-chain messaging, and protocol research.

## Strong fits
- Tools that meaningfully shrink the time from "Solana newcomer" to "shipping app developer."
- Indexers, RPC patterns, or compute layers that unlock workloads not feasible today (zk verification, MEV redistribution, rollup data availability).
- Security-first contributions: formal verification, fuzzing, audit tooling, transaction simulators.

## Weak fits / out of scope
- Wrappers around existing tools that don't add new capability.
- General DevOps tooling not specific to Solana or crypto.

## What we look for
Whether the tool removes a real point of friction we hear developers complain about; whether the team has the technical depth to maintain it; whether other teams could plausibly depend on it post-hackathon.`,
  },
  {
    name: "Consumer & Mobile",
    description_markdown: `# Consumer & Mobile

Apps a non-crypto-native user would want to use: wallets, social, gaming, content, creator tools, marketplaces, identity, and payments disguised as normal-feeling consumer flows.

## Strong fits
- Designs that hide the wallet entirely (passkeys, embedded wallets, abstracted gas).
- Mobile-first builds that earn day-2 retention through utility, not speculation.
- Novel social or content primitives that require Solana's cost/speed characteristics — a normal SaaS app doesn't qualify just because it emits a token.

## Weak fits / out of scope
- "Web2 app + token" without a real reason for the token.
- Generic NFT marketplaces or Twitter clones.

## What we look for
A clear "why crypto" answer that doesn't reduce to airdrops. UX quality matters more here than technical novelty — a great UX with a modest underlying mechanism beats a clever mechanism with hostile UX.`,
  },
  {
    name: "DePIN & Real-World Assets",
    description_markdown: `# DePIN & Real-World Assets

Decentralized physical infrastructure: sensor networks, energy, telecom, compute, storage, mobility, environmental monitoring, and verifiable real-world data feeds. Also covers tokenized RWAs that need verifiable proofs of off-chain state.

## Strong fits
- Hardware-backed protocols where on-chain incentives produce measurable real-world outputs (kWh generated, square meters mapped, PM2.5 readings collected).
- Designs that handle the verification problem honestly — anti-spoofing, cross-validation, signed sensor readings, TEE-attested measurement.
- RWA projects with credible custody, audit, and redemption pathways.

## Weak fits / out of scope
- "Map of nodes" without a working hardware spec or an incentive design beyond block rewards.
- Tokenized "real estate" without legal structuring or off-chain enforcement.

## What we look for
Evidence the hardware works (BOM, photos, telemetry from a single node), a coherent reward/slashing economy, and at least one credible data buyer or use case for the network's output.`,
  },
  {
    name: "AI Agents & Automation",
    description_markdown: `# AI Agents & Automation

Autonomous agents transacting on-chain: agent payments, agent identity, agent-to-agent commerce, intent execution, MEV agents, on-chain ML inference, verifiable inference (zkML), and agent infrastructure.

## Strong fits
- Agents that own assets, sign transactions, and produce verifiable records of why a decision was made.
- Solana-as-substrate-for-agents arguments: the agent needs cheap compute, fast finality, or parallelism that other chains can't provide.
- zkML / TEE-attested model inference that lets a third party verify what model produced an output.

## Weak fits / out of scope
- "ChatGPT wrapper that mints an NFT."
- Off-chain agents that touch Solana incidentally as a payment rail.

## What we look for
Whether the agent's reasoning loop and actions are verifiable; whether the project takes adversarial agent behavior (sybils, prompt injection, manipulated inputs) seriously; whether there's a real economic loop the agent participates in.`,
  },
  {
    name: "Public Goods & Open Source",
    description_markdown: `# Public Goods & Open Source

Projects that primarily benefit the broader Solana / crypto ecosystem rather than the team building them: open-source tooling, libraries, educational resources, retroactive funding mechanisms, governance research, and protocol-neutral infrastructure shipped under permissive licenses.

## Strong fits
- Open-source code that other teams in the cohort could plausibly depend on within 90 days.
- New funding mechanisms (retro PGF, quadratic, attestation-based reputation) with on-chain enforcement.
- Educational / onboarding resources that materially lower the cost of shipping on Solana for a specific audience (e.g. mobile devs, university students, ML researchers).

## Weak fits / out of scope
- Closed-source projects that simply emit a token.
- Documentation rewrites of existing tools without new capability.

## What we look for
A permissive license, a credible maintenance plan, and evidence the artifact is genuinely usable by parties other than the original team (forks, dependents, docs that don't assume internal knowledge).`,
  },
]

export const FRONTIER_PRESET: FrontierPreset = {
  name: "Solana Frontier 2026",
  end_date: FRONTIER_END_DATE_LOCAL,
  evaluation_frequency: "30m",
  tracks: FRONTIER_TRACKS,
}
