# transcripts — shared context pipeline (Layer 1)

Turns raw diarized transcripts (meetings, 1-on-1s, discussions) into a
queryable intelligence layer on top of the Shape Rotator OS graph.

```
raw diarization  ──parse──►  immutable Session  ──enrich (LLM)──►  derived  ──►  SQLite
   (VoxTerm /                 raw + metadata +                    summary,        transcript_
    Whisper /                 derived(null)                       signals,        sessions
    AssemblyAI)                                                   entities
```

## Two layers

- **Layer 1 (built):** per-transcript intelligence — parse → enrich → store →
  print. One LLM pass fills `derived.summary`, `derived.signals`,
  `derived.entities`.
- **Layer 2 (later, not built):** cross-transcript connection finding —
  speaker resolution, matching `derived.entities` to graph nodes, similarity /
  relation queries across sessions, natural-language organizer queries.

## The contract that makes Layer 2 cheap

`raw_diarization` is written **once and never mutated**. Every later stage
reads a session and writes back only to `metadata` / `derived`. So new pipeline
stages can be added tomorrow without reprocessing anything. The storage layer
enforces this: `store.save_session` (→ `sqlite.save_transcript_session`) will
not overwrite `raw_diarization` on a row that already exists.

`derived` slots Layer 2 will fill: `derived.graph_nodes` (matched node ids),
`metadata.resolved_speakers` (label → real identity).

## Usage

```bash
# VoxTerm hivemind batch, generic Whisper/AssemblyAI segments, or a list of either
python -m transcripts.cli session.json
python -m transcripts.cli - < session.json            # stdin
python -m transcripts.cli session.json --tags 1on1,mentoring
python -m transcripts.cli session.json --no-enrich    # parse + store only
python -m transcripts.cli session.json --dry-run --json
```

stdout is markdown (summary + signals + entities) — pipe it to Slack, Notion,
or any router.

## Session shape

```jsonc
{
  "session_id": "transcript-2026-05-27-1430-voxterm",   // record_id, or date-source-hash
  "raw_diarization": [{"speaker": "speaker_1", "text": "...", "start": 2.1, "end": null}],
  "metadata": {
    "date": "2026-05-27", "source": "voxterm",
    "resolved_speakers": {}, "tags": [], "pipeline_version": "transcript-pipeline/0.1.0",
    "record_id": "...", "origin_device": "...", "location": "...", "started_at": "...", "ended_at": "..."
  },
  "derived": { "summary": null, "signals": null, "entities": null, "graph_nodes": null }
}
```

## Adaptations from the original spec

- **Storage is SQLite, not Supabase.** Sessions live in the shared
  `data/conclave.db` (`transcript_sessions` table), which persists across Phala
  CVM redeploys. No external dependency, stays inside the TEE.
- **Enrichment uses `config.get_llm()`, not the raw Anthropic SDK.** That routes
  through NearAI confidential compute, so transcripts never leave the enclave —
  consistent with Conclave's trust story. Switch backends/models via
  `CONCLAVE_LLM_BACKEND` and the `--model` flag; `langchain-anthropic` is already
  a dependency if you want to point it at Claude.

## VoxTerm merge

The first-class input is VoxTerm's hivemind wire format
(`{record_id, started_at, ended_at, origin_device, location, segments:[{t, speaker, text}]}`).
VoxTerm's single timestamp `t` maps to `start` (`end` stays null). A natural
Layer-1.5 step is a sink endpoint that accumulates VoxTerm batches by
`record_id`, then runs this pipeline when a session closes.
