# Troubleshooting — Conclave Hackathon Novelty

Resolutions for common failure modes the skill encounters.

## Setup

**`/health` not 200, or connection refused.**
The enclave URL is wrong or the enclave is down. Ask the user to re-paste
the URL the organizer shared. Don't retry in a loop. If the URL is
correct, the enclave may be redeploying — ask the user to wait a few
minutes.

**`/instances/<id>` returns 404.**
The instance ID is wrong, or the operator deleted the instance. Ask the
user to re-paste the instance ID from the organizer's announcement.

**`/generate-token` returns 404.**
Same root cause as above — the instance ID in the request body doesn't
match an existing instance. Verify the ID is being sent correctly in the
JSON body, not the URL.

**TLS / certificate error.**
The enclave host's certificate is invalid or expired. Stop. Tell the user
this is a serious red flag — a real Conclave enclave should always have
a valid certificate. Suggest they confirm the URL with the organizer
through a second channel (e.g., direct message vs. a Discord post).

## Submission

**`/submit` returns 401.**
The Bearer token is missing or invalid. Most common cause: the token in
`~/.conclave/credentials.json` was minted for a different instance, or
the credentials file was corrupted.

Resolution:
1. Confirm the active credentials entry's `instance_id` matches the
   enclave you're submitting to.
2. If it matches, mint a new token via `POST /generate-token` and
   overwrite the entry. Note: a fresh token has no submission history; if
   the user had a prior submission_id, it remains in the cohort but the
   user can no longer fetch its result. They will need to resubmit under
   the new token.

**`/submit` returns 422.**
Validation error. Read the `detail` field. The most common cause is an
empty or whitespace-only `idea_text`. Ask the user to give you a
description.

**`/submit` returns 5xx.**
Enclave-side error. Show the `detail` to the user and stop. Do not retry
automatically — the enclave may be in a bad state and retrying could
double-submit on success-after-error.

**Network timeout during submit.**
Possible the request reached the enclave but the response was lost. Ask
the user before retrying. If they want to retry, do `GET /my-submissions`
first — if a new `submission_id` appears that you don't have locally,
the original submit succeeded and you should adopt that ID instead of
resubmitting.

## Results

**`/results/<id>` returns 404.**
No result yet for this submission. The enclave evaluates on the
operator's schedule (e.g., every 1w / 3d). Tell the user to check back
after the next evaluation tick. Do not poll.

**`/results/<id>` returns 403.**
The token does not own this submission_id. Likely a stale credentials
entry — either the user's local file got desynced or they're using a
freshly-minted token to fetch an older submission. Use `GET
/my-submissions` to find what this token actually owns.

**`confidence: "low"` in the result.**
Cohort is small (N < 5). Tell the user verbatim: *"The cohort is small
(N=X). Scores will firm up as more submissions land — check back after
the next evaluation tick."* This is not an error — the enclave is being
honest about scoring thinness.

**Result has empty `track_alignments`.**
The operator did not configure tracks for this instance. Show novelty
score + cluster only and tell the user this hackathon doesn't use
track-alignment scoring.

## Attestation

**`/attestation` returns a non-200 or empty quote.**
The enclave is not running on real TDX hardware (e.g., a local dev
deploy). Stop. Tell the user this enclave is not providing the privacy
guarantee the skill assumes. Do not proceed with submission unless they
explicitly understand the risk.

**`/attestations` returns an empty list.**
Normal before the hackathon's `end_date`. The enclave publishes the
on-chain attestation only at the final evaluation tick. Tell the user to
re-check after the hackathon ends.

## Credentials file

**`~/.conclave/credentials.json` corrupted or unparseable.**
Back it up to `~/.conclave/credentials.json.bak.<timestamp>` and start a
fresh setup. Do not silently overwrite — the user may want to recover
the old token via support channels.

**Multiple instances in `instances` array.**
Ask the user which one they want to use this session before doing
anything. v1 default if user doesn't choose: most recently used (last in
the array).

**File mode is not 0600.**
Tell the user the file holds a sensitive PAT. Offer to `chmod 600` it.
