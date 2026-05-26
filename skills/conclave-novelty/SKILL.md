---
name: conclave-novelty
description: Privately evaluate a hackathon idea against the current cohort inside a TEE without exposing the idea to anyone. Use when the user wants to check if their hackathon project is novel, scored against other current submissions, or aligned with hackathon tracks; when they're submitting to a Solana hackathon (Frontier, Cypherpunk, Breakout, Renaissance) or any other hackathon using Conclave; when they want a confidential second opinion on their idea before submission; when the user has been given an enclave URL or instance ID by an organizer; or when they mention "is my idea unique", "novelty score", "Conclave", "Confidential Hackathon Novelty", "TEE hackathon eval", or similar. The idea, README, and code are summarized locally and encrypted to the enclave; nobody else (organizer, peers, platform operators) sees the raw input — only bounded scores leave the enclave.
---

# Conclave — Confidential Hackathon Novelty

Score a hackathon idea against the rest of the current cohort, inside a Trusted
Execution Environment (TEE), without revealing the idea to the organizer, other
participants, or the Conclave platform.

You (the agent) read the user's repo and idea on their machine, summarize them,
and submit the summary to a hackathon enclave. The enclave returns the user's
own novelty score, cluster, track alignment, and same-name collision warnings.

## When to use this skill

Trigger this skill whenever the user:

- Asks if their hackathon idea is novel, unique, or differentiated.
- Wants a confidential second opinion before submitting.
- Mentions Conclave, an enclave URL, or a Conclave instance ID.
- Says they're entering Solana Frontier / Cypherpunk / Breakout / Renaissance,
  or any hackathon that uses Conclave for evaluation.
- Asks to "submit my idea to the enclave" or "check my novelty score".

Don't trigger this for general novelty assessments or competitor analysis —
this is specifically for hackathon submissions evaluated by a Conclave enclave
deployed by the organizer.

## Privacy boundary (state this to the user)

Before doing anything that reads files or sends data, say this verbatim once
per session:

> Your idea, README, and code are read by **your local agent on your machine**.
> The agent will summarize them and send only the summary to the hackathon
> enclave over TLS. The enclave runs inside Intel TDX — the operator, other
> participants, and the Conclave platform never see your raw idea, repo, or
> README. Only your scores leave the enclave.

Full statement: see `references/privacy.md`.

## Credential storage

The skill stores enclave credentials at `~/.conclave/credentials.json` with
mode `0600` (owner-only). Schema:

```json
{
  "instances": [
    {
      "enclave_url": "https://....phala.network",
      "instance_id": "uuid-from-organizer",
      "name": "Frontier 2026",
      "token": "Bearer-PAT",
      "submission_id": "uuid-after-first-submit"
    }
  ]
}
```

Multi-instance behavior: if the file has more than one entry, ask the user
which one to use this session. v1 default: most recently used.

## First-time setup

Run this when the user has been given an enclave URL or instance ID and has
not configured this skill yet (no `~/.conclave/credentials.json`, or no entry
matches the URL the user provided).

1. **Ask for the enclave URL and instance ID.** The organizer typically shares
   both in a Discord announcement or email — e.g.
   `https://abc123.dstack-pha-prod5.phala.network` and an instance UUID. If
   the user pastes a single URL containing the instance ID (e.g.
   `https://conclaveagent.vercel.app/i/<uuid>`), parse the UUID out and ask
   them for the enclave's TEE base URL separately.

2. **Validate the enclave is up.** `GET <enclave_url>/health`. Expect 200 with
   `{"status": "ok", ...}`. If not 200, stop and tell the user the enclave is
   unreachable — verify the URL with the organizer.

3. **Verify the instance exists.** `GET <enclave_url>/instances/<instance_id>`.
   Expect 200. A 404 means the instance ID is wrong or expired.

4. **Show the attestation.** `GET <enclave_url>/attestation`. The response is
   `{"quote": "...", "verify_url": "..."}`. Display:
   - The first 16 hex chars of the quote and its full length.
   - The verify URL, telling the user they can POST the quote to it to
     independently verify the enclave is running unmodified Conclave code on
     genuine Intel TDX hardware.
   - One sentence on what attestation means: *"This is a hardware-signed proof
     that the enclave is running the exact code the platform claims, on real
     Intel TDX silicon. Anyone — including you — can verify it."*

5. **Mint a participant token.** `POST <enclave_url>/generate-token` with body
   `{"instance_id": "<instance_id>"}`. Response: `{"token": "...",
   "expires_at": null}`. Save the token.

6. **Persist credentials.** Write `~/.conclave/credentials.json` with mode
   `0600`. If the file exists, append to `instances`; do not overwrite other
   entries. Confirm to the user that setup is complete.

## Submitting an idea

Use when the user asks to submit, score, or evaluate their idea.

1. **Locate the project.** Default to the current working directory. If the
   user names a different directory, use that.

2. **Read locally.** Read on the user's machine only:
   - `README.md` (or `README`, `readme.md`) at the project root.
   - The repo's manifest file: `package.json`, `Cargo.toml`, `pyproject.toml`,
     `go.mod`, `Anchor.toml`, etc. — whichever exists.
   - Top-level source layout (file/directory listing only, not file contents
     beyond the manifest and README).

3. **Summarize into a structured submission:**
   - `idea_text` (string, required) — one paragraph in plain English: what
     the project does, who it's for, what's distinctive.
   - `repo_summary` (string, optional but recommended) — tech stack inferred
     from the manifest + a one-paragraph description of the repo structure.
   - `deck_text` (string, optional) — only if the user explicitly points you
     at a pitch deck or design doc; do not invent one.

4. **Show the user the summary and ask them to confirm.** Verbatim. Tell them
   this is exactly what will be sent to the enclave. Wait for explicit
   confirmation before sending.

5. **Submit.** `POST <enclave_url>/submit` with header
   `Authorization: Bearer <token>` and body:
   ```json
   {
     "idea_text": "...",
     "repo_summary": "...",
     "deck_text": "..."
   }
   ```
   Response: `{"submission_id": "<uuid>", "status": "received",
   "submissions_count": <int>}`.

6. **Persist the submission_id** in the credentials.json entry for this
   instance. The user fetches results with this ID later.

7. **Tell the user when results are due.** Results are computed on a periodic
   schedule set by the organizer (e.g., every 1 week, every 3 days). They
   can ask "do I have my Conclave score yet?" later.

## Updating a submission

If the user wants to revise their idea after submitting, repeat the submit
flow. The enclave keys submissions by token, so resubmitting under the same
token **replaces** the existing submission — the cohort size N does not grow.
Tell the user this explicitly so they understand resubmission is safe and
non-spamming.

## Fetching results

Use when the user asks for their score, novelty rating, or Conclave result.

1. **Look up `submission_id`** in `~/.conclave/credentials.json` for the
   active instance. If missing, tell the user they haven't submitted yet.

2. **Fetch.** `GET <enclave_url>/results/<submission_id>` with
   `Authorization: Bearer <token>`. Possible responses:
   - 200 — result available, fields per below.
   - 404 — no result yet (pipeline hasn't run for the current cohort, or
     this submission_id wasn't included in the latest run). Tell the user
     the enclave will compute results at the next scheduled tick.
   - 401 / 403 — token rejected. Offer to regenerate (see error handling).

3. **Render the result.** The participant sees only their own scores:
   - `novelty_score` (0.0–1.0) — higher = more distinctive vs. the rest of
     the cohort.
   - `cluster_label` + `cluster_size` — which thematic cluster the idea
     landed in and how many submissions are in that cluster.
   - `track_alignments` — `{track_name: 0..1}` per organizer-defined track,
     plus `best_fit_track`.
   - `name_collisions` — list of `{other_submission_id, similarity}` if any
     other submission has a similar project name.
   - `confidence` — `"low"` if the cohort is small (N < 5). When low, say
     verbatim: *"The cohort is small (N=X). Scores will firm up as more
     submissions land — check back after the next evaluation tick."*

4. **Privacy reminder.** When showing collisions, note that the user only
   sees opaque submission IDs of colliding submissions, never the colliding
   participants' identities or their idea content.

## Verifying the enclave / on-chain attestation

When the user asks "is this real?", "can I trust this enclave?", or "where's
the on-chain proof?":

1. `GET <enclave_url>/attestation` — TDX quote. Show its hash and the verify
   URL; tell the user they can POST it to the verify URL.
2. `GET <enclave_url>/attestations` (note the **s**; requires Bearer token) —
   returns the on-chain Solana devnet attestation(s) published by this
   enclave. Show the report hash, transaction signature, and the Solana
   devnet explorer link if present in the response.
3. Explain: *"The TDX quote proves the enclave is running unmodified Conclave
   code right now on real hardware. The Solana attestation is a public
   timestamp anyone can audit, even after the hackathon ends."*

## Error handling

| Symptom | Action |
|---|---|
| `GET /health` not 200 | Tell user the enclave is unreachable. Suggest they verify the URL with the organizer. Do not retry in a loop. |
| `GET /instances/{id}` returns 404 | Instance ID is wrong or expired. Ask user to re-paste from organizer. |
| `POST /submit` or `GET /results/...` returns 401 | Token missing/expired. Offer to mint a new one via `POST /generate-token` and overwrite the entry in credentials.json. Note that a fresh token has no submission history — the user will need to resubmit. |
| `POST /submit` returns 422 | Submission validation failed. Show the server's `detail` to the user; usually means `idea_text` is empty. |
| `GET /results/{id}` returns 404 | No result yet. Don't poll — explain the enclave evaluates on a schedule. |
| `POST /submit` returns 5xx | Enclave error. Show `detail` to user and stop. Do not retry automatically. |
| Network error / TLS failure | Stop. Tell the user to check connectivity and the URL. |

## What this skill never does

- Send raw repo contents, full source files, or arbitrary file trees to the
  enclave. Only the locally-computed `idea_text` / `repo_summary` /
  `deck_text` summary leaves the user's machine.
- Send environment variables, credentials, or anything outside the project
  directory the user named.
- Reveal another participant's submission, identity, or score.
- Submit on the user's behalf without showing them the summary first and
  getting explicit confirmation.
- Retry failed submits in a loop.

## When to consult `references/`

- `references/api_reference.md` — exact request/response schemas, status
  codes. Consult when a response shape is unclear or you need to construct
  a non-standard call.
- `references/privacy.md` — full trust boundary statement. Consult when the
  user asks deep privacy questions.
- `references/troubleshooting.md` — extended error → resolution table.
  Consult when an error path above doesn't cover the symptom.
