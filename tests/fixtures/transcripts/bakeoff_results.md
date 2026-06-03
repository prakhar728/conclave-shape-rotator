# Q1 bake-off results — one-prompt vs per-type extraction

Model: `redpill:google/gemma-3-27b-it`. Scoring: greedy one-to-one fuzzy match (text 0.7 / turn-overlap 0.3, threshold 0.35); entities matched type-agnostically by name similarity (threshold 0.5).

Ground truth: Codex-labelled (see LABELER_PROMPT.md). F1 here is agreement-with-Codex; the one_prompt vs per_type comparison is the decision signal, not the absolute numbers.

## Aggregate (all transcripts pooled)

| metric | one_prompt | per_type |
|---|---|---|
| obligation F1: action | 0.11 (n=16) | 0.20 (n=16) |
| obligation F1: decision | 0.00 (n=1) | 0.00 (n=1) |
| obligation F1: commitment | 0.00 (n=7) | 0.20 (n=7) |
| obligation F1: open_question | 0.00 (n=3) | 0.04 (n=3) |
| obligation F1: blocker | 0.50 (n=1) | 0.05 (n=1) |
| obligation macro-F1 | 0.12 | 0.10 |
| obligation F1 (type-agnostic) | 0.22 | 0.14 |
| entity F1 | 0.50 | 0.45 |

## dstack-intro-salon

| metric | one_prompt | per_type |
|---|---|---|
| obligation F1: action | 0.09 (n=4) | 0.12 (n=4) |
| obligation F1: decision | 0.00 (n=0) | 0.00 (n=0) |
| obligation F1: commitment | 0.00 (n=4) | 0.38 (n=4) |
| obligation F1: open_question | 0.00 (n=2) | 0.17 (n=2) |
| obligation F1: blocker | 0.00 (n=0) | 0.00 (n=0) |
| obligation macro-F1 | 0.03 | 0.22 |
| entity F1 | 0.63 | 0.64 |

## elocute

| metric | one_prompt | per_type |
|---|---|---|
| obligation F1: action | 0.00 (n=4) | 0.00 (n=4) |
| obligation F1: decision | 0.00 (n=0) | 0.00 (n=0) |
| obligation F1: commitment | 0.00 (n=3) | 0.22 (n=3) |
| obligation F1: open_question | 0.00 (n=1) | 0.00 (n=1) |
| obligation F1: blocker | 0.00 (n=0) | 0.00 (n=0) |
| obligation macro-F1 | 0.00 | 0.07 |
| entity F1 | 0.45 | 0.47 |

## project-intros-agents-day3

| metric | one_prompt | per_type |
|---|---|---|
| obligation F1: action | 0.19 (n=8) | 0.34 (n=8) |
| obligation F1: decision | 0.00 (n=1) | 0.00 (n=1) |
| obligation F1: commitment | 0.00 (n=0) | 0.00 (n=0) |
| obligation F1: open_question | 0.00 (n=0) | 0.00 (n=0) |
| obligation F1: blocker | 0.50 (n=1) | 0.15 (n=1) |
| obligation macro-F1 | 0.23 | 0.17 |
| entity F1 | 0.42 | 0.32 |
