# Q1 bake-off results — one-prompt vs per-type extraction

Model: `redpill:google/gemma-3-27b-it`. Scoring: greedy one-to-one fuzzy match (text 0.7 / turn-overlap 0.3, threshold 0.35); entities matched type-agnostically by name similarity (threshold 0.5).

Ground truth: Codex-labelled (see LABELER_PROMPT.md). F1 here is agreement-with-Codex; the one_prompt vs per_type comparison is the decision signal, not the absolute numbers.

## Aggregate (all transcripts pooled)

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.10 (n=16) |
| obligation F1: decision | 0.00 (n=1) |
| obligation F1: commitment | 0.00 (n=7) |
| obligation F1: open_question | 0.18 (n=3) |
| obligation F1: blocker | 0.00 (n=1) |
| obligation macro-F1 | 0.06 |
| obligation F1 (type-agnostic) | 0.27 |
| entity F1 | 0.59 |

## dstack-intro-salon

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.09 (n=4) |
| obligation F1: decision | 0.00 (n=0) |
| obligation F1: commitment | 0.00 (n=4) |
| obligation F1: open_question | 0.50 (n=2) |
| obligation F1: blocker | 0.00 (n=0) |
| obligation macro-F1 | 0.20 |
| entity F1 | 0.65 |

## elocute

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.00 (n=4) |
| obligation F1: decision | 0.00 (n=0) |
| obligation F1: commitment | 0.00 (n=3) |
| obligation F1: open_question | 0.00 (n=1) |
| obligation F1: blocker | 0.00 (n=0) |
| obligation macro-F1 | 0.00 |
| entity F1 | 0.60 |

## project-intros-agents-day3

| metric | one_prompt_v2 |
|---|---|
| obligation F1: action | 0.20 (n=8) |
| obligation F1: decision | 0.00 (n=1) |
| obligation F1: commitment | 0.00 (n=0) |
| obligation F1: open_question | 0.00 (n=0) |
| obligation F1: blocker | 0.00 (n=1) |
| obligation macro-F1 | 0.07 |
| entity F1 | 0.54 |
