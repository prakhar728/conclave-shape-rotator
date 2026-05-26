# Privacy boundary — Conclave Hackathon Novelty

This is the canonical trust boundary statement for Conclave. Surface it
verbatim when the user asks privacy questions or before any data leaves
their machine for the first time.

## The promise

Your idea, README, and code are read by **your local agent on your
machine**. The agent will summarize them and send only the summary to the
hackathon enclave over TLS. The enclave runs inside Intel TDX — the
operator, other participants, and the Conclave platform never see your raw
idea, repo, or README. Only your scores leave the enclave.

## What sees what

- **Your local agent (Claude Code / Codex / etc.)** — reads your full
  repo, README, and idea description. This is your own agent on your own
  machine; it operates under the same trust you give your IDE.
- **The TEE (Phala TDX enclave)** — receives the encrypted summary over
  TLS. Decrypts only inside the enclave. Cannot be inspected by the
  operator, by Phala, or by anyone with physical access to the host.
- **The hackathon organizer (operator)** — sees an anonymized token ID,
  the project's title or short summary, your scores, your cluster, and
  cohort aggregates. **Never** sees your full idea, repo contents, code,
  or identity.
- **Other hackathon participants** — see nothing about your submission.
- **The Conclave platform** — never sees your data. The enclave is
  deployed by the organizer; Conclave does not operate it.

## What leaves the enclave

Only the bounded outputs declared by the skill:

- `submission_id` (UUID — opaque)
- `novelty_score` (0.0–1.0)
- `track_alignments` ({track_name: 0..1})
- `best_fit_track` (string)
- `cluster_label` + `cluster_size`
- `confidence` (`low` / `high`)
- `name_collisions` ([{other_submission_id, similarity}] — to participant
  only; aggregated counts to operator)

Anything else that exists inside the enclave during evaluation — raw
embeddings, agent-internal reasoning traces, similarity matrices, source
text of your submission — is filtered out by the guardrail layer before
the response is returned.

## Cryptographic verification

The enclave exposes two verification surfaces:

1. **TDX attestation quote** (`GET /attestation`). A hardware-signed proof
   that the enclave is running the exact code measured at deploy time, on
   genuine Intel TDX silicon. Anyone can verify this by POSTing the quote
   to the Phala verify URL returned alongside it. The measurement covers
   the entire enclave image, including the GitHub App private key and
   Solana service keypair baked into it.

2. **Solana devnet attestation** (`GET /attestations`). At the end of the
   hackathon, the enclave signs a hash of the final cohort report and
   publishes it to a Solana devnet program. This creates a public,
   timestamped record anyone can audit, even years after the hackathon
   ends. Returns `{report_hash, tx_sig, devnet_explorer_url, timestamp}`.

## Known limitations (v1)

- **No sybil prevention.** Anyone with the enclave URL + instance ID can
  mint a token. Operator's distribution channel (Discord, email
  announcement) is the cohort-integrity mechanism in v1.
- **Single hackathon per credentials file.** The schema supports multiple
  instances, but the v1 skill flow defaults to the most recently used
  one.
- **No post-evaluation deletion.** Submissions persist inside the enclave
  for the lifetime of the hackathon instance. The enclave operator can
  destroy the instance (and all its data) at end_date, but cannot
  selectively delete one submission without breaking cohort integrity.

## What to tell the user

Before the user's idea ever leaves their machine, surface a short version
of this statement and require confirmation. The skill body in `SKILL.md`
specifies the exact wording.
