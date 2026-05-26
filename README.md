# Conclave

Confidential live-cohort evaluation for hackathons.

Conclave is a TEE-backed product for the current **Solana Frontier Hackathon** branch of this repo. It helps hackathon organizers and participants answer a question that Colosseum Copilot does not directly answer:

**How novel is this project relative to the teams building right now in the active cohort, without exposing the raw idea to organizers or other teams?**

This branch is intentionally narrower than the older Conclave framework. The broader confidential-protocol direction is preserved on backup branches. The current branch is focused on a single product:

- **Confidential Hackathon Novelty**

## Why this exists

[Colosseum Copilot](https://docs.colosseum.com/copilot/introduction) is a strong research tool for historical landscape analysis: prior hackathon submissions, archive documents, competitive context, and current web research.

Conclave complements that by operating on the **live cohort inside the active hackathon**:

- Copilot helps answer: "What has been built before?"
- Conclave helps answer: "How do I compare to the teams building right now?"

That matters because many teams do not want to reveal raw ideas, README content, or code summaries to organizers or peers just to get novelty feedback.

## Research grounding

Conclave is inspired by **NDAI Agreements** by Matthew Stephenson, Andrew Miller, Xyn Sun, Bhargav Annem, and Rohan Parikh:

- [arXiv:2502.07924](https://arxiv.org/abs/2502.07924)

The paper studies the disclosure paradox around information goods: to evaluate an idea, someone often needs disclosure; but disclosure itself creates expropriation risk. The paper argues that **trusted execution environments (TEEs) plus AI agents** can mitigate that problem and act like an "ironclad NDA."

Conclave applies that logic to live hackathon evaluation.

## Product in one paragraph

An organizer creates a Conclave enclave for a hackathon, sets an end date and evaluation cadence, and defines track descriptions. Participants submit their idea through an agent skill that reads their repo locally and sends only the submission into the enclave. On each scheduled tick, the enclave evaluates the full accumulated cohort and returns bounded outputs such as novelty, best-fit track, cluster, and name-collision warnings. The organizer gets anonymized cohort-level visibility and attestation-backed reporting without seeing raw participant submissions.

## Current branch scope

This branch is optimized for the **Frontier / Public Goods** pitch, not for the older generic framework story.

What is in scope here:

- live-cohort hackathon novelty evaluation
- periodic re-evaluation until the hackathon end date
- participant-facing agent skill install flow
- operator setup UI and dashboard
- TDX attestation checks
- optional final Solana devnet attestation of the cohort report hash

What is not the main story on this branch:

- generic multi-protocol marketplace positioning
- confidential dataset procurement as the hero demo
- multi-skill gallery UX
- participant web submission flows

## What Conclave evaluates

The deterministic and agentic pipeline currently produces these participant-facing outputs:

- `novelty_score`
- `track_alignments`
- `best_fit_track`
- `cluster_label`
- `cluster_size`
- `confidence`
- `name_collisions`

Admin-facing results additionally include:

- `aligned`
- `criteria_scores`
- `status`
- `analysis_depth`
- `duplicate_of`

The operator dashboard also computes cohort-level summaries:

- cohort size
- last evaluation time
- cluster distribution
- track distribution
- name-collision pair count
- evaluation timeline
- attestations

## How the scoring works

Conclave is not a thin chat wrapper over hackathon submissions. The backend mixes deterministic methods with agentic evaluation.

### 1. Ingestion

`skills/hackathon_novelty/ingest.py`

- normalizes plain text, markdown, or docx submissions
- summarizes long submissions before comparison
- now degrades gracefully offline by falling back to raw `idea_text`

### 2. Deterministic layer

`skills/hackathon_novelty/deterministic.py`

- sentence-transformer embeddings
- offline hashed-embedding fallback when no local model weights are available
- pairwise cosine similarity
- novelty score = `1 - max(similarity to any other submission)`
- percentile calculation
- KMeans clustering
- readable cluster labels based on representative submission titles
- name-collision detection with `SequenceMatcher` plus substring checks
- track alignment by similarity to organizer-defined track names

### 3. Agent layer

`skills/hackathon_novelty/agent.py`

- triage step decides `score` vs `duplicate`
- judges whether a submission is aligned with the hackathon/theme
- score step evaluates criteria using raw submission content inside the enclave
- if the online LLM path is unavailable, the pipeline now falls back to deterministic outputs plus neutral agent defaults

### 4. Guardrails

`skills/hackathon_novelty/guardrails.py`

- allowed output-key whitelist
- numeric clamping
- raw-substring leakage detection before outputs leave the pipeline

## Scheduler and lifecycle

Conclave is periodic and stateful.

`infra/scheduler.py`

- one async task per instance
- wakes up on `evaluation_frequency_seconds`
- re-evaluates the full current cohort
- runs a final evaluation at `end_date`
- optionally publishes the final cohort report hash to Solana devnet

Supported cadences include values like:

- `30m`
- `1h`
- `6h`
- `1d`
- `3d`
- `1w`
- `2w`

## User flow

### Organizer

1. Open `/setup`
2. Verify the TDX seal
3. Create an instance with:
   - hackathon name
   - end date
   - evaluation cadence
   - track descriptions
4. Receive:
   - `instance_id`
   - `admin_token`
   - `enclave_url`
5. Share the participant install snippet

### Participant

Participants are meant to use the skill in `skills/conclave-novelty/` rather than the web UI.

Install path:

```bash
npx skills add prakhar728/conclave
```

The skill then:

1. verifies the enclave
2. mints a participant token with `/generate-token`
3. summarizes the local repo and idea
4. submits to `/submit`
5. fetches results from `/results/{submission_id}`

## Trust boundary

Conclave's intended privacy model is:

- the participant's local agent sees their local repo and README
- the enclave sees the submitted content inside Intel TDX
- the organizer sees only bounded outputs and anonymized submission summaries
- other participants see nothing about other teams

This is why the product is useful for live hackathon evaluation. Teams can get current-cohort signals without broadcasting their raw work-in-progress ideas.

## Attestation model

There are two attestation surfaces in the current branch:

### TDX quote

`GET /attestation`

- fetched from the dstack agent when running in TEE
- surfaced in the frontend attestation widget
- verified through Phala's attestation verification endpoint

### Final cohort report hash

`infra/solana.py`

- deterministic SHA-256 hash of the final results set
- published to Solana devnet via the Memo program when `CONCLAVE_SOLANA_KEYPAIR` is configured
- falls back to `local_only` mode when Solana credentials are absent

## UI and styling

The frontend is not generic SaaS. The visual system is intentional and is part of the product identity.

Theme:

- Roman tribunal / arena / sealed deliberation

Core design choices:

- typography: `Cinzel` for display, `EB Garamond` for body, `IBM Plex Mono` for hashes and system text
- palette: travertine cream, weathered stone, porphyry purple, arena ochre, basalt
- motifs: laurel wreaths, SPQR-style seal, arch dividers, plaque surfaces
- language: "Convene a Conclave," "Enter the lists," "The Imperial Seal," "The Conclave deliberates"

Reference files:

- `client/apps/web/app/page.tsx`
- `client/apps/web/app/setup/page.tsx`
- `client/apps/web/app/dashboard/[id]/page.tsx`
- `client/apps/web/app/style/page.tsx`
- `client/packages/ui/src/styles/globals.css`

The `/style` page is effectively an in-repo visual spec for the current UI language.

## Repo map

```text
main.py                              FastAPI entrypoint
api/routes.py                        REST API and role-gated endpoints
storage/sqlite.py                    Persistent SQLite state
infra/scheduler.py                   Periodic evaluation loop
infra/enclave.py                     TDX attestation integration
infra/solana.py                      Final report hash publication
skills/hackathon_novelty/            Live evaluation pipeline
skills/conclave-novelty/             Participant agent skill
client/apps/web/                     Operator-facing Next.js app
plans/                               Product and implementation planning docs
```

## Local development

### Backend

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend default:

- `http://localhost:8000`

### Frontend

From the monorepo frontend root:

```bash
cd client
pnpm install
pnpm --filter web dev
```

Frontend default:

- `http://localhost:3000`

Set `NEXT_PUBLIC_TEE_URL` in the frontend environment if your API is not on the default local backend URL.

### Docker / enclave-style deployment

```bash
docker-compose up
```

Notable environment variables:

- `CONCLAVE_NEARAI_API_KEY`
- `CONCLAVE_DEFAULT_MODEL`
- `CONCLAVE_SUPABASE_URL`
- `CONCLAVE_SUPABASE_ANON_KEY`
- `CONCLAVE_SOLANA_KEYPAIR`
- `CONCLAVE_SOLANA_RPC_URL`
- `CONCLAVE_PUBLIC_URL`
- `IN_TEE`

See:

- `.env.example`
- `docker-compose.yml`

## Testing

Run:

```bash
pytest tests -q
```

Current status on this branch after the latest fixes:

- `74 passed`

The latest fixes make the pipeline degrade more gracefully when the online LLM path is unavailable, which matters for offline CI and local development.

## Known limitations

- track alignment currently embeds **track names**, not full markdown track descriptions
- the typed `/instances` flow currently hardcodes criteria weights internally to originality + feasibility
- participant-facing submission is skill-first; the web UI is intentionally operator-first
- Solana publication is optional and falls back to local-only when unconfigured
- organizer-defined tracks for Frontier are a Conclave overlay, not official Colosseum tracks

## Relevant external references

- [Solana Frontier Hackathon](https://colosseum.com/frontier)
- [Colosseum Copilot docs](https://docs.colosseum.com/copilot/introduction)
- [NDAI Agreements](https://arxiv.org/abs/2502.07924)
