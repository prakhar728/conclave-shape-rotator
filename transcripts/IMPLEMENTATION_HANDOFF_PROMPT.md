# Implementation Handoff — Phase 1, Cohort Context Intelligence

> Copy everything below the line into a fresh chat. The plan exists in the repo; your job is to **execute it**.

---

You are picking up an in-progress project. The plan exists; your job is to execute it step by step. **Do not improvise scope, do not skip ahead, do not batch commits.**

## ⛔ Doc allowlist — read NOTHING outside this list

The ONLY markdown docs relevant to this work, in this order:
1. `transcripts/IMPLEMENTATION_PLAN.md`
2. `transcripts/BUILD_PLAN.md`
3. `transcripts/README.md` *(optional, low-priority)*

**Do NOT read, browse, search, grep, or `ls` any of the following — they belong to unrelated work and will derail you:**
- `plans/`  ·  `plans/new directions/`  *(this is a different vertical — collab-matching — with conflicting `S1, S2…` step labels and a different branch `feat/collab-matching`. If you find yourself looking at it, **stop**.)*
- Any `*.md` outside `transcripts/` (top-level READMEs, `CHANGELOG.md`, etc.) — irrelevant.
- Any other feature branch (`feat/*`).

If you need *code* context, read source files under `transcripts/`, `storage/sqlite.py`, `config.py`, `tests/test_transcript_pipeline.py`, and `skills/hackathon_novelty/agent.py` (LLM/JSON-parse reference pattern). Nothing else.

## ⚠️ Name-collision trap (the reason for the allowlist)

The unrelated `plans/new directions/` work uses **`S1, S2, … S<N>`** as step labels. **Your work uses `C1, C2, … C11`** — defined in `transcripts/IMPLEMENTATION_PLAN.md` §H. **Never use `S<N>`.** If you catch yourself reaching for `S1` or `feat/collab-matching`, you're on the wrong doc — back out and re-read the allowlist.

## Project & branch
- Repo: `/Users/prakharojha/Desktop/me/personal/shape-rotator-all/conclave-shape-rotator/`
- Branch: **`transcripts-phase1`** (already checked out; 3 baseline commits ahead of `main`'s `Init`).
- Verify with `git rev-parse --abbrev-ref HEAD` → must print `transcripts-phase1`. **Do not switch branches** — never `git checkout`, `merge`, `rebase`, or `fetch` other branches.

## Step 1 — orient (do this BEFORE any code)
Read the allowlisted docs (1 and 2 above) in order. You should understand:
- The product = **cohort context intelligence** (per-meeting summaries → cross-meeting connections, confidential-by-design, declared-only graph).
- The **viable-minimal-not-naive** principle (deferred = working minimal, never a naive stub).
- The **commit-and-test sequence C1–C11** in §H, anti-domino discipline in §H.0.
- The **Otter transcript format** (§G1) and **mock-identity source** (§G2).
- What's **anti-scoped** (§L) — don't drift.

**Report your understanding back to the user before writing any code.** State what C1 produces, its inputs/outputs, and the test gate. Wait for "go."

## Step 2 — execute C1 → C11 sequentially
Per §H critical path: **C1 → C2 → C3 → C4 → C5 → C6 → C7 → C8 → C9 → C10 → C11**. C1–C5 + C9 need **zero LLM** — start there. C8 onwards needs the LLM unblocked.

For each commit Cn:
1. **Implement** per the spec in §G (file responsibilities, function contracts, critical notes).
2. **Run the test gate** named in §H plus the focused suite:
   `CONCLAVE_DISABLE_SCHEDULER=1 .venv/bin/python -m pytest -q --ignore=external --ignore=tests/test_interview_reflection_mcp.py`
3. **Propose the commit message** in project style (lowercase prefix + em-dash sub-clause; **no `Co-Authored-By` trailer**).
4. **STOP.** Wait for explicit approval before `git commit`. Never batch commits.
5. After approval, commit, then propose the next Cn.

## Discipline (non-negotiable)
- **Stay on `transcripts-phase1`.** Never switch, merge, or rebase against other branches.
- **Read only the allowlisted docs.** Never open `plans/`, never grep across `plans/`.
- **Green trunk** before every commit — no red commit, ever.
- **FakeLLM** for any LLM-touching test (pattern in `tests/test_transcript_pipeline.py`) → suite runs with **zero credits / zero network**.
- The **7 legacy tests** in `tests/test_transcript_pipeline.py` must stay green through C2's parse refactor — they are the behavior-preservation net.
- **`raw_diarization` must never leave the API** (C10 has an explicit test asserting this).
- **No `Co-Authored-By` trailer** on any commit.

## LLM access (one operational thing)
NearAI is currently credit-walled. For C8+ (enrichment) you'll need one of:
- a NearAI top-up, **or**
- local Ollama: `ollama pull qwen2.5:14b-instruct` + `CONCLAVE_LLM_BACKEND=ollama` + `CONCLAVE_OLLAMA_MODEL=qwen2.5:14b-instruct`. Set `num_ctx` ≥ `CHUNK_MAX_TOKENS` so long transcripts don't silently truncate (see §F).

**C1–C5 and C9's metric-math test need no LLM** — start there.

## Real data is already in place
13 real cohort transcripts at `tests/fixtures/transcripts/*.txt` (gitignored — local only; consented + public via the SROS GitHub). Format documented in §G1. Use them for C4's ingest tests and as raw input for C8's eval golden set.

## Anti-patterns (will fail review)
- **Reading anything under `plans/`** — wrong vertical, will derail you with `S<N>` naming.
- **Browsing the repo for "more context"** — the allowlist is exhaustive. If it's not on it, you don't need it.
- **Switching branches** — `transcripts-phase1` is the entire session.
- Adding **new sources/adapters** (VoxTerm live, Gemini, Matrix) — §K Extension points, *future*, not Phase 1.
- **Embeddings / vectors** — anti-scoped (§L). Phase 1 has no matching.
- **Real Cohort-OS API calls** — identity is mocked from `cohort-data/people/*.md` slugs (§G2).
- **Real permission enforcement** — `can_see` is a stub returning `True` for Phase 1.
- **Reformatting / refactoring beyond the spec.**
- **Skipping ahead** to a more interesting commit.

## When in doubt
Re-read the §G spec for the file you're working on, and the §H critical notes for the commit you're on. The plan has the answer. If it genuinely doesn't, ASK — don't invent, don't browse `plans/`.

**Begin now:**
1. Confirm branch: `git rev-parse --abbrev-ref HEAD` → `transcripts-phase1`.
2. Confirm naming: your steps are **C1–C11**, never `S<N>`.
3. Confirm doc allowlist: you'll read only `transcripts/IMPLEMENTATION_PLAN.md` + `transcripts/BUILD_PLAN.md` (+ optionally `transcripts/README.md`).
4. Then read those, and report your understanding of C1 (`sources.py` + `NormalizedInput`) and the Otter format from §G1. Stop for approval before writing code.
