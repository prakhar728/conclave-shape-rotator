# Interview Reflection Pipeline (Track A v0)

Confidential, TEE-resident pipeline that turns one interview transcript into bounded,
interviewer-facing reflection signals — without the raw transcript ever leaving the enclave.

- **In:** an interview transcript + `interviewee_slug` (+ optional notes, opt-in share flag)
- **Inside (Intel TDX):** deterministic features → LLM themes/ownership → guardrails → append-only ledger
- **Out:** themes, attribution patterns, ownership prompts, suggested next questions, session summary — signed with the enclave key. Raw transcript text never exits.

Pipeline A only (per-interview, team-contextual labeling). Cross-interview clustering (B),
signal-vs-goals (C), and conversational admin query (D) are later phases — see
[`../../plans/new directions/interview_pipeline_architecture.md`](../../plans/new%20directions/interview_pipeline_architecture.md).

## End-to-end flow

```mermaid
flowchart TD
    subgraph Client["Agent client (Novel's Claude Code / Cursor)"]
        A1["submit_interview(transcript, interviewee_slug, share_with_interviewee?)"]
        A2["get_interview_results(interviewee_slug)"]
    end

    subgraph TEE["Intel TDX enclave — raw transcript never leaves"]
        direction TB

        subgraph Entry["Entry surface (api/routes.py + mcp_server.py)"]
            E1["MCP /mcp tools<br/>submit_interview · get_interview_results<br/>list_interviewees · get_team_context<br/>whoami · verify_attestation(nonce)"]
            E2["REST /submit · /trigger"]
            TOK{"X-Instance-Token<br/>admin vs participant"}
        end

        ORCH["run_skill() — per transcript in batch<br/>skill.py"]

        subgraph L1["Layer 1 — deterministic.py (pure Python, no LLM)"]
            D1["parse INTERVIEWEE / INTERVIEWER turns"]
            D2["pronoun tally → internal_count / external_count"]
            D3["attribution_bucket<br/>mostly_internal | mostly_external<br/>mixed | shifting | insufficient_signal"]
            D4["session_word_count · speaker_turn_count · keyword_freq"]
            D1 --> D2 --> D3
            D1 --> D4
        end

        subgraph L2["Layer 2 — agent.py (LangGraph + LLM, inside TEE)"]
            direction LR
            G1["themes_node<br/>3-5 themes + session_summary<br/>grounded in team_context"]
            G2["ownership_node<br/>attribution_patterns {internal,external}<br/>ownership_prompts · suggested_next_questions"]
            G1 --> G2
        end

        ASM["assemble NovelOutput<br/>plus IntervieweeOutput iff share_with_interviewee"]

        subgraph L3["Layer 3 — guardrails.py (InterviewReflectionFilter)"]
            direction TB
            R1["filter_keys — drop non-whitelisted keys"]
            R2["strip_long_quotes — cap per-field length"]
            R3["gate_evidence_quotes — drop unless share=True"]
            R4["redact_unknown_names — keep cohort people only"]
            R5["leakage_check — scan vs raw transcript, redact substrings"]
            R1 --> R2 --> R3 --> R4 --> R5
        end

        L4["Layer 4 — aggregate.append_digest()<br/>append-only ledger after guardrails only"]
    end

    LLM["NearAI confidential LLM<br/>config.get_llm — DeepSeek-V3.1"]
    LEDGER["data/interview_reflection/{slug}.jsonl"]
    OUT["Signed bounded outputs<br/>NovelOutput → interviewer<br/>IntervieweeOutput → interviewee opt-in"]

    A1 --> E1
    A2 --> E1
    E1 --> TOK
    E2 --> TOK
    TOK --> ORCH
    ORCH --> L1
    L1 -->|"deterministic features"| L2
    G1 -.->|"LLM call"| LLM
    G2 -.->|"LLM call"| LLM
    L2 --> ASM
    ORCH -.->|"team_context: stubbed in v0; Step 8 = teams/slug.md"| L2
    ASM --> L3
    L3 --> L4
    L4 --> LEDGER
    L3 --> OUT
    OUT --> A2
```

## Agent sub-graph (Layer 2)

Two sequential LLM nodes compiled with LangGraph. Each falls back to neutral
defaults if the model is unavailable, so the skill stays usable offline.

```mermaid
flowchart LR
    START["transcript + team_context + Layer 1 features"] --> T["themes_node<br/>weights themes by team trajectory:<br/>productization / research_lineage / collaborative"]
    T --> O["ownership_node<br/>reads themes + pronoun counts + transcript<br/>judges real attribution beyond pronouns"]
    O --> END_NODE["merged dict → NovelOutput"]
```

## Cross-session aggregation (Layer 4)

Single interviews are noise; value compounds across a slug's session history.
Reads the append-only ledger (never raw transcripts) and derives trajectory.

```mermaid
flowchart TD
    J["{slug}.jsonl<br/>ordered post-guardrail digests"] --> AGG["run_aggregate(digests)"]
    AGG --> RT["recurring_themes: 2+ sessions"]
    AGG --> NT["new_themes / dropped_themes"]
    AGG --> AS["attribution_series + trajectory<br/>shifted_internal | shifted_external<br/>stable_internal | stable_external | stable_mixed"]
    AGG --> OA["overall_assessment<br/>e.g. 'shifting toward ownership; latest internal share 0.71'"]
```

## Trust boundary in one line

The agent client sees the raw transcript locally; the **enclave** sees it inside TDX;
the **interviewer/coordinator** sees only bounded, signed outputs. Persistence to the
ledger happens **after** guardrails, so raw text can never enter stored history.

## Source map

| Layer | File | Role |
|-------|------|------|
| Entry | `mcp_server.py`, `../../api/routes.py` | MCP tools + REST, token-scoped, signed responses |
| Orchestration | `skill.py` | `run_skill` — runs the four layers per transcript |
| Layer 1 | `deterministic.py` | pronoun/attribution buckets, session stats, keywords |
| Layer 2 | `agent.py` | LangGraph `themes_node → ownership_node` |
| Layer 3 | `guardrails.py` | key whitelist, quote caps, name redaction, leakage scan |
| Layer 4 | `aggregate.py` | per-slug JSONL ledger + cross-session trajectory |
| Contracts | `models.py` | `TranscriptInput`, `NovelOutput`, `IntervieweeOutput` |
