# Conclave Architecture

## Overview

Conclave is currently a Python FastAPI service that exposes a generic skill runtime for enclave-style analysis workflows. The separate Next.js app under `client/` is still a scaffold and is not yet wired into the backend runtime.

The core design is:

- The API owns transport, token resolution, and instance-scoped state.
- A `SkillCard` is the contract between the API and each skill.
- A skill owns its own onboarding flow, runtime pipeline, and output restrictions.
- Only derived outputs are intended to leave the runtime.

## Whole App

```mermaid
flowchart LR
    Admin[Admin Operator]
    User[Participant User]
    FE[Next.js frontend scaffold<br/>not wired yet]
    API[FastAPI app]
    Routes[API routes layer]
    Stores[In-memory instance stores<br/>instances submissions results tokens]
    Router[SkillRouter]
    Card[SkillCard metadata]
    Skill[Skill runtime]
    LLM[Configured LLM provider]
    Embeddings[Deterministic ML layer]
    Guardrails[Output guardrails]
    Results[Derived results only]

    Admin -->|POST /init /trigger /results| API
    User -->|POST /submit GET /results/:id| API
    FE -. future client .-> API

    API --> Routes
    Routes --> Stores
    Routes --> Router
    Router --> Card
    Router --> Skill

    Skill --> Embeddings
    Skill --> LLM
    Skill --> Guardrails
    Guardrails --> Results
    Results --> Stores
```

## Core Runtime

The backend starts in `main.py`, enables permissive CORS, registers skills, and mounts the API router.

`api/routes.py` is intentionally thin. It does not contain skill-specific business logic. Its responsibilities are:

- create and resume skill instances
- issue and resolve instance tokens
- store submissions and results in memory
- validate submissions against the selected skill's `input_model`
- invoke the skill pipeline through `SkillRouter`
- expose skill metadata through `/skills`

### Request and state flow

```mermaid
flowchart TD
    Start[FastAPI startup] --> Register[register_skills]
    Register --> OneSkill[Register hackathon_novelty only]

    Init[/POST init/]
    Submit[/POST submit/]
    Trigger[/POST trigger/]
    GetAll[/GET results/]
    GetOne[/GET results/:id/]
    Skills[/GET skills/]

    Init --> InitState[Create or resume instance]
    InitState --> InitHandler[Skill init_handler]
    InitHandler --> Ready{status == ready}
    Ready -- no --> Wait[Keep conversation in memory]
    Ready -- yes --> Tokens[Issue admin_token and user_token]
    Tokens --> InstanceConfig[Persist config + threshold in memory]

    Submit --> ResolveToken[Resolve X-Instance-Token]
    ResolveToken --> SaveSubmission[Store raw submission in memory]
    SaveSubmission --> Threshold{count >= threshold}
    Threshold -- no --> Pending[received_pending]
    Threshold -- yes --> Pipeline[_run_pipeline]

    Trigger --> AdminCheck[Admin role required]
    AdminCheck --> Pipeline

    Pipeline --> Validate[Validate each submission with skill input_model]
    Validate --> Invoke[SkillRouter.invoke]
    Invoke --> SkillRun[skill.run]
    SkillRun --> StoreResults[Write result dicts by submission_id]
    StoreResults --> ReadAPIs[Results endpoints read from in-memory store]

    GetAll --> ReadAPIs
    GetOne --> ReadAPIs
    Skills --> SkillMeta[Return SkillCard metadata]
```

## Skills Model

The key abstraction is `SkillCard`. A skill is more than one callable. It is a self-describing package that tells the app:

- what input schema to validate against
- what output keys are allowed to leave the skill
- how the skill is configured
- what trigger modes it supports
- what admin and user roles mean for that skill
- whether it supports conversational setup through `init_handler`

This lets the app remain generic while each skill owns its own behavior.

### App-to-skill contract

```mermaid
flowchart LR
    subgraph App
        API[API routes]
        SR[SkillRouter]
    end

    subgraph Skill Package
        Card[SkillCard]
        Init[init_handler]
        Input[input_model]
        Run[run_skill]
        Outputs[allowed output_keys]
    end

    API -->|/skills metadata| Card
    API -->|/init setup loop| Init
    API -->|validate raw submission| Input
    API -->|invoke| SR
    SR --> Card
    SR --> Run
    Run --> Outputs
```

## `hackathon_novelty` Deep Dive

`hackathon_novelty` is the only fully implemented skill in the repo today. It is the reference architecture for adding future skills.

Its pipeline is explicitly three-layered:

1. deterministic analysis
2. LangGraph-based agent execution
3. guardrails before returning results

### Skill pipeline

```mermaid
flowchart TD
    Inputs[HackathonSubmission list]
    Det[run_deterministic]
    Ctx[set_context + triage_context]
    Agent[run_agent]
    Merge[Merge deterministic + agent outputs]
    Filter[HackathonNoveltyFilter.apply]
    Response[SkillResponse results]

    Inputs --> Det
    Det -->|novelty_scores percentiles clusters sim_matrix| Ctx
    Ctx --> Agent
    Det --> Merge
    Agent --> Merge
    Merge --> Filter
    Filter --> Response
```

### Layer 1: deterministic analysis

The deterministic layer fuses submission text, computes embeddings, builds a cosine similarity matrix, derives novelty scores, ranks them into percentiles, and clusters submissions with KMeans.

This produces the shared context used by the agent and the output merge step:

- `novelty_scores`
- `percentiles`
- `clusters`
- `sim_matrix`
- ordered `submission_ids`

### Layer 2: LangGraph branching

The agent graph classifies submissions into one of three paths:

- `duplicate` -> handled by a deterministic flag node
- `quick` -> lightweight LLM scoring
- `analyze` -> deeper LLM evaluation with more tool use

### Agent graph

```mermaid
flowchart TD
    Triage[triage node<br/>LLM + TRIAGE_TOOLS]
    Router[router node<br/>deterministic split]
    Flag[flag node<br/>duplicates]
    Quick[quick node<br/>LLM scoring]
    Analyze[analyze node<br/>LLM deep evaluation]
    Finalize[finalize node<br/>fill gaps]
    End([END])

    Triage --> Router
    Router --> Flag
    Router --> Quick
    Router --> Analyze
    Flag --> Finalize
    Quick --> Finalize
    Analyze --> Finalize
    Finalize --> End
```

### Layer 3: guardrails

Guardrails do three things:

- strip keys not on the allowed whitelist
- clamp numeric values into expected ranges
- detect raw substring leakage from input content in the output

This is important because the analyze flow does let the LLM inspect raw submission content inside the runtime.

## Tooling and Trust Boundary

The hackathon skill splits tools into derived-context tools and raw-text tools.

- `TRIAGE_TOOLS` expose summary and similarity information
- `ANALYSIS_TOOLS` expose raw idea text, technical details, deck content, and criterion context
- `ALL_TOOLS` combines both

The intended trust model is that raw content stays inside the runtime, while only filtered, derived result fields leave.

```mermaid
flowchart LR
    subgraph Deterministic Context
        Summary[get_submission_summary]
        Similar[get_similar_submissions]
        Dist[get_distribution_stats]
    end

    subgraph Raw Text Access
        Idea[get_idea_text]
        Tech[get_technical_details]
        Deck[get_deck_content]
    end

    Score[score_criterion]
    LLM[LangGraph nodes]
    Guard[filter_keys + bounds + leakage detector]
    APIOut[API response]

    Summary --> LLM
    Similar --> LLM
    Dist --> LLM
    Idea --> LLM
    Tech --> LLM
    Deck --> LLM
    Score --> LLM
    LLM --> Guard
    Guard --> APIOut
```

## Operator Setup Flow

The setup experience is skill-owned. For `hackathon_novelty`, the `init_handler` runs a multi-turn LLM conversation to collect:

- weighted criteria
- optional guidelines
- submission threshold

Only when the skill says it is ready does the API issue tokens.

```mermaid
sequenceDiagram
    participant Admin
    participant API as /init
    participant Skill as hackathon_init_handler
    participant LLM

    Admin->>API: POST /init {skill_name, message, instance_id?}
    API->>Skill: init_handler(message, conversation)
    Skill->>LLM: conversational config prompt
    LLM-->>Skill: question or final JSON
    Skill-->>API: {status, message, conversation, config?, threshold?}

    alt configuring
        API-->>Admin: instance_id + status=configuring + message
    else ready
        API-->>Admin: instance_id + admin_token + user_token
    end
```

## Current Constraints

- State is in memory only. There is no persistent storage layer yet.
- Only `hackathon_novelty` is registered. `dataset_audit` is currently just a stub package.
- The frontend is not integrated with the backend workflow yet.
- The code assumes a single-worker deployment model for submission-trigger safety.
- The shared `user_token` model is a known limitation until per-user auth exists.
- The env file example does not currently match the `CONCLAVE_`-prefixed settings expected by `config.py`.

## Files to Read First

- `main.py`
- `api/routes.py`
- `core/skill_card.py`
- `skills/router.py`
- `skills/hackathon_novelty/__init__.py`
- `skills/hackathon_novelty/deterministic.py`
- `skills/hackathon_novelty/agent.py`
- `skills/hackathon_novelty/tools.py`
- `core/guardrails.py`
