# Q1 bake-off results — one-prompt vs per-type extraction

Model: `redpill:google/gemma-3-27b-it`. Scoring: greedy one-to-one fuzzy match (text 0.7 / turn-overlap 0.3, threshold 0.35); entities matched type-agnostically by name similarity (threshold 0.5).

Ground truth: Codex-labelled (see LABELER_PROMPT.md). F1 here is agreement-with-Codex; the one_prompt vs per_type comparison is the decision signal, not the absolute numbers.

## Aggregate (all transcripts pooled)

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.14 (n=16) |
| obligation F1: decision | 0.00 (n=1) |
| obligation F1: commitment | 0.00 (n=7) |
| obligation F1: open_question | 0.00 (n=3) |
| obligation F1: blocker | 0.00 (n=1) |
| obligation macro-F1 | 0.03 |
| obligation F1 (type-agnostic) | 0.26 |
| entity F1 | 0.62 |

## dstack-intro-salon

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.19 (n=4) |
| obligation F1: decision | 0.00 (n=0) |
| obligation F1: commitment | 0.00 (n=4) |
| obligation F1: open_question | 0.00 (n=2) |
| obligation F1: blocker | 0.00 (n=0) |
| obligation macro-F1 | 0.06 |
| entity F1 | 0.79 |

## elocute

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.00 (n=4) |
| obligation F1: decision | 0.00 (n=0) |
| obligation F1: commitment | 0.00 (n=3) |
| obligation F1: open_question | 0.00 (n=1) |
| obligation F1: blocker | 0.00 (n=0) |
| obligation macro-F1 | 0.00 |
| entity F1 | 0.67 |

## project-intros-agents-day3

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.19 (n=8) |
| obligation F1: decision | 0.00 (n=1) |
| obligation F1: commitment | 0.00 (n=0) |
| obligation F1: open_question | 0.00 (n=0) |
| obligation F1: blocker | 0.00 (n=1) |
| obligation macro-F1 | 0.06 |
| entity F1 | 0.48 |
