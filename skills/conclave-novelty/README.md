# conclave-novelty

> The NDA you don't have to sign — for hackathon submissions.

Privately evaluate a hackathon idea against the rest of the current cohort,
inside a TEE, without revealing it to the organizer, other participants, or
the platform. Distributed as an agent skill for Claude Code, Codex, Cursor,
Gemini CLI, GitHub Copilot CLI, and Antigravity.

## Install

```
npx skills add prakhar728/conclave
```

The CLI auto-discovers `skills/conclave-novelty/SKILL.md` in this repo and
installs to `~/.claude/skills/` and/or `~/.codex/skills/` depending on the
agents detected on your machine.

## Quick demo (participant)

The hackathon organizer shares an enclave URL + instance ID with you (Discord,
email, etc.). Then, in your coding agent:

```
You: Is my hackathon idea novel? The organizer gave me
     https://abc123.dstack-pha-prod5.phala.network and instance ID
     8ed7d18f-fdda-430d-843e-c8b42a92cdb0. My project is in this directory.
```

The agent will:

1. Verify the enclave is up and show you the TDX hardware attestation.
2. Mint a participant token bound to that instance.
3. Read your repo locally, summarize it, and **show you the summary first**.
4. After you confirm, encrypt the summary to the enclave over TLS.
5. Periodically (on the organizer's schedule), fetch your novelty score,
   cluster, track alignment, and same-name collision warnings.

You can also ask later:

- *"What's my Conclave score?"* — fetches results.
- *"Update my submission."* — resubmits; replaces the prior submission.
- *"Verify the Conclave enclave."* — shows the TDX quote and any Solana
  devnet attestations published by the enclave.

## Privacy

Your idea, README, and code are read by **your local agent on your machine**.
Only the summary leaves your machine, encrypted to the enclave over TLS. The
enclave runs inside Intel TDX — the operator, other participants, and the
Conclave platform never see your raw idea, repo, or README. Only your scores
leave the enclave.

Full statement: [`references/privacy.md`](references/privacy.md).

## What the operator sees

- Anonymized token IDs (never your identity).
- The project's title or short summary.
- Your novelty score, cluster, track alignment.
- Cohort aggregates (cluster sizes, track distribution, name-collision counts).

The operator never sees your full idea text, repo contents, code, or identity.

## Cryptographic verification

Two independent verification surfaces:

- **TDX attestation** — `GET <enclave_url>/attestation` returns a hardware
  signed proof that the enclave is running unmodified Conclave code on
  genuine Intel TDX silicon. POST it to the Phala verify URL to check.
- **Solana devnet attestation** — at hackathon end_date, the enclave
  publishes a hash of the final cohort report to Solana devnet. Public,
  timestamped, auditable forever.

## For organizers

Deploy your own Conclave enclave for your hackathon at
[conclaveagent.vercel.app](https://conclaveagent.vercel.app) → "Set up an
instance". You'll get an enclave URL and admin token. Share the URL +
instance ID with participants through your usual announcement channel.

## Open source

This skill, the enclave backend, and the operator UI are open source —
shipped as a public good for the hackathon ecosystem. Repo:
[prakhar728/conclave](https://github.com/prakhar728/conclave).

## License

MIT.
