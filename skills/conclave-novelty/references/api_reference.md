# API reference — Conclave enclave

REST endpoints exposed by a Conclave hackathon enclave. The skill calls
these directly over HTTPS. Base URL is the enclave URL the organizer
shares (e.g. `https://abc123.dstack-pha-prod5.phala.network`).

## Auth

Two header conventions are accepted:

- `Authorization: Bearer <token>` — canonical for the agent skill.
- `X-Instance-Token: <token>` — legacy, used by the operator web UI.

Use Bearer everywhere from the skill.

Token roles:

- `admin` — issued once at instance creation; the operator's dashboard
  token. The skill never holds an admin token.
- `user` — issued by `POST /generate-token`; one per participant. The
  skill stores this in `~/.conclave/credentials.json`.

---

## `GET /health`

No auth. Liveness check.

**Response 200**
```json
{
  "status": "ok",
  "instances": 3,
  "submissions": 47,
  "skills": ["hackathon_novelty"]
}
```

---

## `GET /instances/{instance_id}`

No auth. Verifies an instance ID is valid before the user mints a token.

**Response 200**
```json
{
  "instance_id": "uuid",
  "skill_name": "hackathon_novelty",
  "triggered": false,
  "submissions": 12,
  "threshold": 999999
}
```

**Response 404** — instance not found.

---

## `GET /attestation?nonce=<optional>`

No auth. Returns the TDX hardware attestation for the enclave.

**Response 200**
```json
{
  "quote": "<hex-encoded TDX quote>",
  "verify_url": "https://cloud-api.phala.network/api/v1/attestations/verify"
}
```

The skill should display the first 16 hex chars of the quote and the
verify URL. The user can independently POST the quote to `verify_url`.

---

## `POST /generate-token`

No auth (URL + instance ID is the access control). Mints a participant
token bound to one instance.

**Request body**
```json
{ "instance_id": "uuid" }
```

**Response 200**
```json
{ "token": "k8s9f...", "expires_at": null }
```

**Response 404** — instance not found.

---

## `POST /submit`

Bearer required. Idempotent per token: same token resubmitting **updates**
the existing submission rather than creating a new one. Cohort N does not
grow on update.

**Request body** (HackathonSubmission)
```json
{
  "idea_text": "One-paragraph description.",
  "repo_summary": "Tech stack + structure summary.",
  "deck_text": "Optional pitch deck text"
}
```

`submission_id` is auto-generated server-side if omitted.

**Response 200**
```json
{
  "submission_id": "uuid",
  "status": "received",
  "submissions_count": 13
}
```

**Response 401** — missing/invalid Bearer token.
**Response 422** — validation error (e.g. empty `idea_text`). Body has
`{"detail": "Submission validation failed: ..."}`.

---

## `GET /my-submissions`

Bearer required. Returns the submission IDs owned by the calling token —
useful for recovering after losing the local credentials file.

**Response 200**
```json
{ "submission_ids": ["uuid1", "uuid2"] }
```

---

## `GET /results/{submission_id}`

Bearer required. Participant-scoped: the token must own the submission.

**Response 200** (participant view, filtered to user_output_keys)
```json
{
  "submission_id": "uuid",
  "novelty_score": 0.82,
  "track_alignments": { "Infra": 0.71, "Consumer": 0.34 },
  "best_fit_track": "Infra",
  "cluster_label": "embedded-payments",
  "cluster_size": 4,
  "confidence": "high",
  "name_collisions": [
    { "other_submission_id": "uuid", "similarity": 0.91 }
  ]
}
```

**Response 403** — token does not own this submission_id.
**Response 404** — no result yet (pipeline hasn't run for the current
cohort).

---

## `GET /attestations`

Bearer required. Returns Solana devnet attestation records published by
this enclave instance.

**Response 200**
```json
{
  "attestations": [
    {
      "report_hash": "0x...",
      "tx_sig": "5...",
      "devnet_explorer_url": "https://explorer.solana.com/tx/...?cluster=devnet",
      "timestamp": "2026-05-11T18:00:00Z"
    }
  ]
}
```

Empty list before end_date is normal.

---

## Endpoints the skill does NOT call

These exist for the operator UI and should never be invoked from the
participant-side skill:

- `POST /instances` — operator creates instance.
- `POST /trigger` — admin-only manual evaluation.
- `GET /submissions`, `GET /results`, `GET /cohort/aggregates`,
  `GET /cohort/timeline` — operator dashboard endpoints.
- `POST /attestations/publish` — admin-only force-publish.
- `POST /fetch-repo` — server-side repo fetch (used by the operator UI;
  the skill reads the user's local repo instead and never sends a URL).

---

## Status codes summary

| Code | Meaning | Skill action |
|------|---------|--------------|
| 200 | Success | Continue. |
| 401 | Missing/invalid token | Offer to mint a new token; user will need to resubmit. |
| 403 | Wrong role or wrong token for this submission | Stop; explain. |
| 404 | Not found (instance/result) | Stop; explain. Don't poll. |
| 422 | Validation error | Show server `detail` to user. |
| 5xx | Enclave error | Stop; show `detail`. Do not retry. |
