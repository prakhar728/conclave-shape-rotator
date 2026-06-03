# Ollama prereqs for the 3.5 KB pipeline

> Phase 3.5.0 C2.5 (see discoveries/KB-AND-GRAPH-BUILD-PLAN.md).
> Captured 2026-06-03.

## What the pipeline needs

| Stage | Model role | Default in this repo | Roadmap calls for |
|---|---|---|---|
| C7  context-header generation     | LLM   | `qwen2.5-conclave:latest`   | `qwen2.5:14b` |
| C13 typed extraction              | LLM   | `qwen2.5-conclave:latest`   | `qwen2.5:14b` |
| C14 importance scoring (Q4)       | LLM   | `qwen2.5-conclave:latest`   | `qwen2.5:14b` |
| C15 ER LLM tiebreak (Q5)          | LLM   | `qwen2.5-conclave:latest`   | `qwen2.5:14b` |
| C16 Mem0 upsert decision (Q10)    | LLM   | `qwen2.5-conclave:latest`   | `qwen2.5:14b` |
| C8  chunk embeddings              | embed | `nomic-embed-text:v1.5`     | same          |
| C23 query embeddings              | embed | `nomic-embed-text:v1.5`     | same          |

## How to set it up

```sh
make ollama-check       # verifies Ollama is running and both models are pulled
make ollama-prereqs     # pulls the project-default models if missing
make ollama-prereqs-14b # escape hatch: pull qwen2.5:14b for roadmap-literal mode
```

`OLLAMA_LLM_MODEL` and `OLLAMA_EMBED_MODEL` env vars override the defaults
for any of the targets, e.g. `OLLAMA_LLM_MODEL=qwen2.5:14b make ollama-check`.

## Why we deviate from the roadmap on the LLM

The roadmap nominates `qwen2.5:14b` (~9GB). We use the in-tree
`qwen2.5-conclave:latest` (built from `qwen2.5:7b-instruct` via
`ollama/Modelfile.qwen-conclave`, `num_ctx=8192`) for three reasons:

1. **Bake-off robustness.** Q1 (C3) compares one-prompt vs per-type
   extraction prompts against the same model. The decision is *relative*;
   absolute extraction F1 may differ between 7b and 14b but the prompt
   shape that wins on one is overwhelmingly likely to win on the other.
2. **Production single-model.** Existing enrichment + reduce paths run
   on `qwen2.5-conclave`. Pulling a second 9GB model creates two
   coexistent Qwens with different `num_ctx` and prompt-tuning history.
   Avoidable until proven necessary.
3. **Disk + bandwidth.** ~9GB unsolicited pull, with no obvious payback
   at v1 corpus scale (Survey D8 fallback also names smaller models
   like `BGE-small-en-v1.5` for the embed side; size-vs-quality is
   not a settled call at our corpus size).

## When to switch to 14b

Trigger the `make ollama-prereqs-14b` path if **either**:

- C13's extraction F1 against ground truth comes in clearly below
  what the bake-off promised (say >10pp regression), suggesting the
  smaller model can't carry the locked prompt shape.
- A specific extraction-type (e.g. blockers, which tend to be
  conversationally subtle) consistently misses on 7b but recovers
  on 14b in spot-checks during C2's hand-coding cross-reference.

Record the trigger in `transcripts/EVAL.md` (C4 onwards) as a decision
record alongside the F1 numbers. Don't switch on vibes — the cost of
running both for one evening of bake-off is worth knowing for sure.

## Model footprints (as of 2026-06-03)

```
qwen2.5-conclave:latest   4.7 GB   (qwen2.5:7b-instruct + num_ctx=8192)
qwen2.5:7b-instruct       4.7 GB   (base — used to build qwen2.5-conclave)
nomic-embed-text:v1.5     ~270 MB
qwen2.5:14b               ~9 GB    (only if you run ollama-prereqs-14b)
```
