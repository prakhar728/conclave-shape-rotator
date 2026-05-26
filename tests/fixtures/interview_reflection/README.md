# interview_reflection fixtures

Synthetic transcripts that exercise the v0 pipeline (Pipeline A) across the
attribution-pattern × team-context grid plus two edge cases. Used by:

- Step 4 (deterministic) — attribution counts, word count, simple keyword density
- Step 5 (agent) — theme extraction + ownership prompts, with mocked LLM
- Step 6 (guardrails) — confirm no raw transcript leaks
- Step 7 (aggregation) — sequenced into multi-session trajectories

## Provenance

Hand-authored to match what Novel told us about his Shape Rotator interview format:

| Aspect            | Assumed value                                       | Source           |
|-------------------|-----------------------------------------------------|------------------|
| Length            | 20–30 minutes                                       | Novel            |
| Format            | 1:1, two speakers                                   | Novel            |
| Style             | Socratic / probing, follow-up driven                | Novel            |
| Medium            | Audio (transcribed post-hoc, no speaker labels)     | Novel            |
| Opening structure | **UNCONFIRMED — placeholder openers used below**    | Novel TBC        |

**Compression note:** these fixtures are ~600–1200 words each, well below a real
20–30-min transcript (~3000–4500 words at 150 wpm). Word-count assertions in
`*.expected.yaml` reflect the fixture length, not the real session length. When
real transcripts arrive in Step 10, expect deterministic thresholds (Layer 1) to
be retuned against actual length distribution.

**Speaker labels:** kept in the transcripts as `INTERVIEWER:` / `INTERVIEWEE:` for
fixture readability. The real pipeline does not require them — Step 4 derives
attribution markers from pronouns, not speaker labels.

## Two attribution labels per fixture

`attribution_bucket` is what the **deterministic Layer 1** is expected to emit —
pure pronoun counting over interviewee turns. This is a coarse pronoun-frequency
snapshot, not a true ownership classifier.

`human_attribution_bucket` (when present) is the **human-judgment label** of
ownership/attribution the **Step 5 agent layer** should target. The two can
diverge because pronoun counts under-detect named-others framing ("the market",
"the reviewers", "the partner") and over-count first-person reflections that
still externalise cause ("I think they didn't engage"). When they diverge, the
fixture is a useful agent-layer test — Layer 1 will say one thing, the agent
should arrive at the other after weighing context.

## Known placeholders (replace when confirmed)

1. **Opening questions** — every fixture currently opens with a generic
   "walk me through your week" style prompt. Replace with Novel's actual opening
   structure once confirmed.
2. **Interviewee/team names** — synthetic (`leo`, `mira`, `dax`, etc.). Real
   slugs map to Shape Rotator `people/*.md` and `teams/*.md`.

## Coverage matrix

| Fixture                       | Attribution     | Team context      | Notes                                  |
|-------------------------------|-----------------|-------------------|----------------------------------------|
| `prod_internal.txt`           | mostly_internal | productization    | clean ownership                        |
| `prod_external.txt`           | mostly_external | productization    | blames market / partners               |
| `prod_mixed.txt`              | mixed           | productization    | balanced                               |
| `prod_shifting.txt`           | shifting        | productization    | starts external, lands internal        |
| `research_external.txt`       | mostly_external | research_lineage  | blames reviewers / lit gaps            |
| `research_shifting.txt`       | shifting        | research_lineage  | external → internal on research scope  |
| `collab_internal.txt`         | mostly_internal | collaborative     | strong ownership of coordination role  |
| `collab_mixed.txt`            | mixed           | collaborative     | own work clear, blames collab partners |
| `edge_silent.txt`             | n/a             | productization    | mostly-silent interviewee              |
| `edge_derailed.txt`           | mixed           | research_lineage  | long off-topic stretch                 |

## File pairing

Each fixture is `<slug>.txt` (transcript) + `<slug>.expected.yaml` (labels the
tests assert against). Adding a new fixture: add both files and update the table
above plus any test that iterates the directory.
