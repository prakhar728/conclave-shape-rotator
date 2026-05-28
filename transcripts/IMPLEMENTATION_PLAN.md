# Transcript Pipeline — Detailed Implementation Plan

> Scope: **Phase 1 in full implementation detail** (ingest → enrich → store → dashboard),
> plus **structural-only** forward declarations for 1.5 (permissions) and Phase 2 (intelligence).
> No code here — file responsibilities, minimal function signatures
> (`name(args) -> ret  # what it does`), data shapes, and changes to existing files.
>
> **Immediate input model:** we **hand-provide transcript files** (format TBD — see §M open item).
> Transcripts carry a mix of real names and `Speaker 1/2` labels. **No live source connection now**
> — VoxTerm/Gemini/Matrix wiring is a *future* task (see §K Extension points). Identity is linked to
> Cohort OS via **mock IDs** behind one seam, so the real lookup swaps in later.
>
> Companion to `BUILD_PLAN.md` (strategy/decisions). This is the execution layer.

---

## A. How to read this (and how to pick it up cold)

- Each module spec = **path · status · responsibility · minimal functions · deps · critical notes.**
- `status`: **HAVE** (exists, unchanged) · **MODIFY** (exists, changes listed) · **NEW**.
- Function signatures are the *contract*, not the implementation. One-line purpose each.
- "Critical notes" are where the non-obvious risk/decision lives — read those.

### Cold-start orientation (read this first if you're new to the project)

**Doc reading order:** `transcripts/BUILD_PLAN.md` (strategy/decisions/positioning) → this file
(execution) → `transcripts/README.md` (package overview).

**Where things live (paths relative to `conclave-shape-rotator/`):**
- Code (Phase 0 done): `transcripts/{models,parse,enrich,store,cli}.py` + `storage/sqlite.py`
  (`transcript_sessions` table already there). 7 tests in `tests/test_transcript_pipeline.py`.
- Real transcript samples (13 Otter-style files): `external/shape-rotator-os/apps/os/src/content/context/raw-scripts/*.txt`
  (format detailed in §G1).
- Cohort roster (for `MOCK_DIRECTORY`): `external/shape-rotator-os/cohort-data/people/*.md`
  (YAML frontmatter: `record_id`, `name`).
- LLM config: host `config.py` exposes `get_llm()` (NearAI default; Ollama via
  `CONCLAVE_LLM_BACKEND=ollama` + `CONCLAVE_OLLAMA_MODEL`).
- Reference pattern for LLM+JSON-parsing: `skills/hackathon_novelty/agent.py`.
- FakeLLM pattern (zero-credit tests): already used in `tests/test_transcript_pipeline.py`.

**Test command (run before every commit — the anti-domino rule):**
`CONCLAVE_DISABLE_SCHEDULER=1 .venv/bin/python -m pytest -q --ignore=external --ignore=tests/test_interview_reflection_mcp.py`

**Commit rules:** lowercase area prefix + em-dash sub-clauses
(`transcripts: ingest — raw capture`). **No `Co-Authored-By` trailer.** Branch off the default
(`transcripts-phase1`); never commit WIP to default. Commits only when the user asks.

**Current state:** Phase 0 done (Layer-1 core + 7 green tests). C1–C11 not yet started. LLM is
credit-walled — top up NearAI or use local Ollama (qwen2.5:14b on Apple Silicon) before C8. Set
local `num_ctx` ≥ `CHUNK_MAX_TOKENS` so long transcripts don't silently truncate.

**Where to start:** §H, C1. The **no-LLM stretch C1→C5** is buildable today against real data with
zero credits.

---

## B. Design revision log (the iterations — what I reversed and why)

1. **parse.py leaks source specifics → move to `sources.py` (the seam).** `parse.py` today knows
   about `origin_device`, `record_id`, `batch_index`, `t` — source knowledge in the core normalizer
   (a core-vs-skin violation). → Strip parse.py to a *generic* normalizer that consumes a
   source-agnostic `NormalizedInput`; the format-specific reading lives in `sources.py`.

2. **Decouple ingest from enrich.** Enrichment needs the LLM (down right now — credit wall). If
   enrich is inline, an LLM outage loses ingested data. → **Ingest captures raw + stores immediately
   (no LLM, never fails on credits); enrichment is a separate idempotent pass** over un-enriched
   sessions. Free bonus: that *is* the backfill mechanism. Biggest structural win here.

3. **No `enrich_run.py`.** Enrich-pass logic lives as `enrich.enrich_pending()`; `cli.py` is a thin
   subcommand dispatcher (`ingest|enrich|link|eval|serve`).

4. **No adapter package in Phase 1.** With only one hand-provided source, a multi-source registry +
   `detect_source` is premature. → A single `sources.py` reader now. The registry/adapter layer
   *returns* when VoxTerm (source #2) connects — see §K.

5. **`llm.py` is shared, not buried in enrich.** Reliable JSON-invoke + access-guard is reused by
   enrich now and query/match later → standalone module.

6. **Add `visibility`/`owner` to the model NOW (free), enforce at 1.5.** They live in the JSON
   `metadata` column → no SQL migration. Avoids a model change mid-1.5.

7. **No embeddings / vector code in Phase 1.** Scale is small, Phase 1 has no matching. Anti-scoped.

8. **Dashboard = standalone static page, not a Next.js route in `client/`.** `shape-ui` is vanilla
   WebGL/JS; a static page served by FastAPI is faster and avoids coupling to the existing web app.

9. **Chunker must handle the oversized single turn.** A 20-min monologue is one segment that exceeds
   the chunk budget → intra-turn sentence split required, not just turn-boundary split.

10. **Reduce step can itself overflow.** Merging N partial summaries is another LLM call → bound by
    hierarchical reduce; minimal-now assumes partial summaries are short (guard with K).

11. **eval uses deterministic set-overlap metrics, not LLM-as-judge.** Avoids cost + circularity.

12. **Idempotency edge: completed-transcript assumption.** Re-ingesting the same file is a no-op on
    raw (write-once). Replacing a transcript needs explicit `--force` (delete+reinsert).

13. **Scope correction (this revision): hand-provided files + mock identity now; sources are future.**
    No running adapters to connect to yet. Immediate path = we feed transcript files; identity to
    Cohort OS is **mocked** behind `identity.resolve_identity()`. VoxTerm/Gemini connection is a
    future add at the `sources.py` seam (§K). Mock-ID linkage is brought into Phase 1 (cheap, no LLM)
    so the demo shows real names, not anonymous speakers.

---

## C. Target package layout

```
transcripts/
  __init__.py            HAVE    package exports
  config.py              NEW     pipeline constants (chunk budget, model ids, versions)
  models.py              MODIFY  + visibility/owner/provenance fields
  sources.py             NEW     read a provided transcript file -> NormalizedInput (the source seam)
  parse.py               MODIFY  strip source-specifics → generic normalizer (NormalizedInput -> Session)
  identity.py            NEW     mock name→cohort-ID linkage (resolve_identity seam)
  store.py               MODIFY  + list_pending(), visibility passthrough, force-replace
  llm.py                 NEW     reliable JSON invoke + LLM access guard (shared)
  chunk.py               NEW     turn-aware chunking with overlap + oversized-turn split
  prompts.py             NEW     versioned enrichment prompts (chunk / reduce / single)
  enrich.py              MODIFY  map-reduce orchestration; enrich_session + enrich_pending
  ingest.py              NEW     batch import: file/dir -> sources.read -> parse -> link -> store(raw)
  eval.py                NEW     golden-set runner + metrics
  cli.py                 MODIFY  subcommand dispatcher: ingest|enrich|link|eval|serve
  web/
    index.html           NEW     dashboard shell
    app.js               NEW     fetch sessions -> render cards -> mountShape per card
    styles.css           NEW     stylized dark editorial theme
    shape-ui/            NEW     vendored copy of packages/shape-ui (glyph renderer, MIT)

storage/sqlite.py        MODIFY  + delete_transcript_session (1.5 adds visibility column+index)
config.py                HAVE    host LLM config (get_llm) — unchanged
api/
  transcripts_routes.py  NEW     GET /transcripts/sessions[/{id}] (derived-only projection)
main.py                  MODIFY  mount transcripts_router; optional static mount for web/
tests/
  test_transcript_pipeline.py  HAVE  (7 tests; keep green through the refactor)
  fixtures/transcripts/        NEW   sample transcripts + <slug>.expected.yaml (when samples arrive)
  test_sources.py              NEW
  test_identity.py             NEW
  test_chunk.py                NEW
  test_llm.py                  NEW
  test_enrich_mapreduce.py     NEW
  test_ingest.py               NEW
  test_api_transcripts.py      NEW
```

**File-count discipline:** 11 new Python files + 3 web files. Rejected: `enrich_run.py`, an adapter
package/registry (premature at one source — §B.4), embeddings module, Next.js coupling.

---

## D. Data model — `transcripts/models.py` (MODIFY)

Current: `RawSegment`, `SessionMetadata`, `Signal`, `Entity`, `Derived`, `Session`, `PIPELINE_VERSION`.

**Changes (all additive; JSON column → no SQL migration):**

`SessionMetadata` — add:
- `visibility: str = "cohort"`            # "cohort" | "owner-only"; **enforced at 1.5**, stored now
- `owner: Optional[str] = None`           # record_id of owner; for 1.5
- `model_id: Optional[str] = None`        # LLM that produced derived (provenance, set by enrich)
- `enrich_prompt_version: Optional[str] = None`  # which prompt produced derived
- `chunk_count: Optional[int] = None`     # how many chunks enrichment used (debug/provenance)

`resolved_speakers` already exists on `SessionMetadata` (`dict`, default `{}`) — the **mock-ID
linkage writes here** (label → `{record_id, name, mock: true}`). No new field needed.

`Derived` — no change now. (`relations` added at 2c; `graph_nodes` present, stays null in Phase 1.)
`Signal`, `Entity`, `RawSegment` — unchanged.

**Critical notes:**
- Bump `PIPELINE_VERSION` only when the *contract* changes; `enrich_prompt_version` (prompts.py)
  tracks prompt changes independently — that's what `enrich_pending` keys off for backfill.
- `visibility` defaults to `"cohort"` so Phase-1 all-access is the model default.

---

## E. Storage — `storage/sqlite.py` (MODIFY)

Current `transcript_sessions`: `session_id, source, session_date, raw_diarization, metadata,
derived, created_at, updated_at` + indexes on date/source. `save_transcript_session` already does
`ON CONFLICT(session_id) DO UPDATE` of **metadata/derived only** (raw write-once) — the idempotency
we need.

**Phase 1: only one addition.** `visibility`/`owner`/`resolved_speakers` live in `metadata` JSON.
- `delete_transcript_session(session_id: str) -> None`  # hard delete (force-replace path only)

**Deferred (1.5):** typed `visibility TEXT` column + index when permission filtering needs SQL
pushdown instead of Python-side filtering.

**Critical:** `list_transcript_sessions()` returns full rows; the "pending enrichment" filter
(derived empty OR stale `enrich_prompt_version`) is Python-side in `store.list_pending()` for Phase 1
(small N). Upgrade to a typed column + index when N grows.

---

## F. Config — `transcripts/config.py` (NEW)

**Responsibility:** pipeline constants in one place; no logic, no I/O. Distinct from host
`config.py` (which owns `get_llm`).

**Contents (constants):**
- `CHUNK_MAX_TOKENS = 6000`            # per-chunk budget; **must be ≤ the model's num_ctx** (Ollama!)
- `CHUNK_OVERLAP_TOKENS = 400`         # trailing-turn overlap between chunks
- `TOKENS_PER_CHAR = 0.25`             # cheap heuristic for estimate_tokens (≈ chars/4)
- `ENRICH_MODEL = None`, `REDUCE_MODEL = None`   # None → backend default (config.get_llm)
- `MAX_SIGNALS = 8`, `MAX_ENTITIES = 30`   # caps applied in reduce
- `GOLDEN_DIR = ".../tests/fixtures/transcripts"`

**Critical:** local Ollama defaults to a small `num_ctx` (often 2048–4096) and *silently truncates*.
`CHUNK_MAX_TOKENS` must be set to fit whatever local model context we run, or long transcripts lose
content with no error. Model ids stay `None` until eval says a specific one is worth pinning.

---

## G. Module specs

### G1. `sources.py` (NEW — the source seam)
**Responsibility:** read a hand-provided transcript file → `NormalizedInput` (source-agnostic). The
*only* place that knows the input file format. Today: one Otter-style reader (the real format
below). Future: VoxTerm/Gemini readers + a registry move in here (§K).

**Input format (Otter.ai-style — what the real cohort transcripts at
`external/shape-rotator-os/apps/os/src/content/context/raw-scripts/*.txt` actually look like):**
- Repeating block of `Header\n<body…>\n\n`.
- **Header line:** `^(.+?)\s{2,}(\d{1,3}:\d{2}(?::\d{2})?)\s*$` — name then **2+ spaces** then
  timestamp `M:SS` / `MM:SS` / `H:MM:SS` (elapsed seconds from session start).
- **Body:** everything between this header and the next; usually one long line, sometimes wrapped.
  **Blank line separates segments.**
- **Speaker labels (verbatim, three flavors):**
  - plain names: `Shaw`, `James Barnes`, `Kristel Alliksaar`
  - names with parentheticals: `Alex (flashbots?)`, `Hunter (tinycloud)` — pass through unchanged;
    `identity.py` normalizes them
  - anonymous diarization: `Speaker 1`, `Speaker 2` — pass through; identity leaves them unresolved
- **BOM gotcha:** at least one file has UTF-8 BOM (`Day 1 Project Intros Notes May 19 2026.txt`) →
  strip before parsing.

**Minimal surface:**
- `NormalizedInput` dataclass: `segments: list[dict]` (each `{speaker, text, start, end}`),
  `provenance: dict` (`source, session_id, date?, members, file_path?`), `source: str`
- `read_file(path: Path) -> NormalizedInput`   # read text → strip BOM → `_parse_otter` → build provenance
- `read_obj(text: str, *, source="otter", path=None) -> NormalizedInput`   # same, from in-memory text (tests/cli)
- `_parse_otter(text) -> list[dict]`           # header-regex pass; returns `{speaker, text, start, end}` (end = next.start; last = None)
- `_seconds(timestamp: str) -> float`          # `"1:23"` / `"1:02:03"` → seconds
- `_slug(name: str) -> str`                    # filename → session_id slug
- `_date_from_name(name: str) -> Optional[str]` # `_May_20` / `May 19 2026` → ISO date

**Deps:** none (pure). **Critical:**
- Speaker labels pass through **verbatim** — *no* identity work here (that's `identity.py`).
- `provenance.session_id` = `_slug(file_stem)` (e.g. `"dstack-hangout-alex-shaw-lsdan-andrew"`).
- `provenance.members` = distinct speakers **excluding `Speaker N`**, in insertion order. Carries
  attendee info for the future permission layer (captured now, unused in Phase 1).
- `provenance.date` = parsed from filename when possible (most have it); fall back to file mtime.
- **`end` per segment** = next header's `start`; last segment's `end` = `None` (we don't know audio
  end-time from the transcript).
- Keep empty-bodied segments (a real utterance can be just `"way"` or `"MK OSI,"`).
- One file (`Day 1 Project Intros Notes May 19 2026.txt`) is labeled "Notes" not "Transcript" —
  spot-check it's the same Otter shape; if it's literal notes, skip or special-case.

### G2. `identity.py` (NEW — mock name→Cohort-OS linkage; the identity seam)
**Responsibility:** the single chokepoint mapping a speaker name to a Cohort-OS record id. Mocked
now (built from real `cohort-data/people/*.md` slugs — so the demo links to *actual* cohort people
from day one); the real `cohort-surface.json` / voiceprint lookup swaps in *here* later (§K).

**Mock directory source (this is what makes the mock meaningful):** at module load, read
`external/shape-rotator-os/cohort-data/people/*.md` and build `MOCK_DIRECTORY` from each file's
YAML frontmatter (`record_id` + `name` + any aliases). So the directory is **not invented** — it's
the real cohort roster, looked up by simple name equality instead of a real cohort-OS API. The
Phase-1 demo therefore shows real `record_id`s next to real names from day one, and the swap to a
real lookup later is a one-function change with the same return shape.

**Minimal functions:**
- `MOCK_DIRECTORY: dict[str, str]`             # populated at import: normalized_name → record_id
- `_load_mock_directory(people_dir: Path) -> dict[str,str]`  # parse frontmatter `name`+`record_id`+aliases; lowercase keys
- `_normalize_name(s: str) -> str`             # lowercase, trim, **strip parenthetical** (`"Alex (flashbots?)"` → `"alex"`); collapse whitespace
- `resolve_identity(name: str) -> Optional[str]`   # normalize + lookup; `None` for `Speaker N` / unknown
- `resolve_speakers(session) -> dict`          # {label: {record_id, name, mock: True}} for resolved labels; unknowns omitted
- `link_identities(*, session_id=None) -> int` # re-link pass over store (re-run when the directory grows)

**Deps:** `store` (for the pass), `pathlib`, `yaml`. **Critical:**
- **One chokepoint.** Don't scatter name→id logic anywhere else. Future swaps (real cohort lookup,
  voiceprint UUIDs) happen *only* here, preserving the
  `resolve_identity(name: str) -> Optional[record_id]` contract.
- Deterministic, **no LLM**. `Speaker N` stays unresolved — that's correct, not a bug.
- **Parenthetical normalization** is the load-bearing trick: `"Alex (flashbots?)"` strips to
  `"alex"` for lookup; the original label remains on the segment.
- Path to `cohort-data/people/` should resolve from repo root; if the directory isn't found, fall
  back to empty `MOCK_DIRECTORY` (everything unresolved) and log a warning — **never crash on
  missing cohort data.**

### G3. `parse.py` (MODIFY — becomes generic)
**Responsibility (narrowed):** turn a `NormalizedInput` into an immutable `Session`
(`derived = Derived()`). No source detection, no format knowledge.
**Functions (after refactor):**
- `build_session(norm: NormalizedInput, *, session_id=None, tags=None) -> Session`  # the new core
- `_segments(norm) -> list[RawSegment]`        # validate/sort (start asc; blanks dropped)
- `_session_id(norm, override) -> str`         # override > provenance.session_id > content hash
- `_metadata(norm, tags) -> SessionMetadata`   # date from provenance|today; carry provenance
- *(KEEP)* `parse_transcript(raw, *, source=None, ...) -> Session` → thin:
  `sources.read_obj(raw)` then `build_session(...)`
**Critical:** keep `parse_transcript` as the convenience entry (tests + cli use it); its guts move to
`sources` + `build_session`. **The existing 7 tests must still pass** — they call `parse_transcript`
on a VoxTerm-shaped batch; that path now routes through `sources.read_obj` (which still understands
the `{segments:[{t,speaker,text}]}` shape as one of its JSON forms).

### G4. `llm.py` (NEW — shared reliability layer)
**Responsibility:** the only caller of `config.get_llm`; wraps it with JSON parse, one repair retry,
schema check, typed access-guard. Reused by enrich now, query/match later.
**Minimal functions:**
- `invoke_json(messages, *, llm=None, model=None, required_keys=(), max_retries=1) -> dict`
  # LLM → bracket-parse JSON → on bad/short JSON re-prompt once → schema-check required_keys
- `_extract_json(text) -> dict | None`         # bracket-matcher (moved from enrich)
- `class LLMUnavailable(Exception)`             # 402/credit/connection — caller decides
- `_get_llm(model)`                             # thin wrapper over config.get_llm with error mapping
**Critical:** map provider errors (`openai.APIStatusError` 402, connection) → `LLMUnavailable` so
`enrich_pending` can **skip-and-continue** instead of crashing the batch. Robust to the credit wall.

### G5. `chunk.py` (NEW)
**Responsibility:** split a session's segments into token-bounded, turn-aware chunks with overlap.
**Minimal functions:**
- `estimate_tokens(text) -> int`               # heuristic (chars * TOKENS_PER_CHAR)
- `chunk_segments(segments, max_tokens=CHUNK_MAX_TOKENS, overlap=CHUNK_OVERLAP_TOKENS) -> list[list[RawSegment]]`
- `_split_oversized_turn(seg, max_tokens) -> list[RawSegment]`   # sentence-split a turn that alone exceeds budget
**Critical:** oversized-turn path (revision #9) is mandatory. Returns `[segments]` (one chunk) when
total < budget → single enrich call, preserving current behavior.

### G6. `prompts.py` (NEW)
**Responsibility:** versioned enrichment prompts, isolated so `enrich_prompt_version` is meaningful.
**Contents:** `ENRICH_PROMPT_VERSION = "v1"`; `SINGLE_SYSTEM`/`SINGLE_USER(text)` (current prompt
moved here); `CHUNK_SYSTEM`/`CHUNK_USER(chunk)`; `REDUCE_SYSTEM`/`REDUCE_USER(partials)`.
**Critical:** keep the `<transcript>`=data injection guard in all three; chunk prompt asks for the
*same JSON shape* as single so the parser/`_to_derived` is reused.

### G7. `enrich.py` (MODIFY — map-reduce + pending pass)
**Responsibility:** produce `derived`; orchestrate chunk→map→reduce; run the backfill pass. Uses
`llm.invoke_json`, `chunk`, `prompts`.
**Functions:**
- `enrich_session(session, *, llm=None, model=None) -> Session`  # single OR map-reduce by chunk count
- `_enrich_chunk(chunk_text, *, llm, model) -> dict`             # one LLM call → partial
- `_reduce(partials, *, llm, model) -> Derived`                  # LLM-synth summary; dedup entities by name; cap signals
- `_to_derived(data) -> Derived`                                 # (KEEP) defensive dict→typed
- `transcript_text(session) -> str`                             # (KEEP)
- `enrich_pending(*, only_stale=True, session_id=None, llm=None) -> EnrichReport`
  # iterate store.list_pending(): enrich → set_derived + set_metadata(model_id, prompt_version); skip on LLMUnavailable
**Critical:** stamp `model_id`+`enrich_prompt_version`+`chunk_count`; entity merge is deterministic
(no LLM), only the summary reduce calls the model; guard `_reduce` against many-partial overflow (K).

### G8. `store.py` (MODIFY)
**Add:** `list_pending(current_prompt_version) -> list[Session]`; `replace_session(session) -> None`
(delete+save, for `--force`); `set_visibility(session_id, visibility, owner=None)` (1.5, defined now).
**Keep:** `save_session`, `load_session`, `list_sessions`, `set_derived`, `set_metadata`,
`_row_to_session`.

### G9. `ingest.py` (NEW — raw capture + mock link, no LLM)
**Responsibility:** import provided transcripts → stored sessions with `derived=null` and
mock-linked `resolved_speakers`. Decoupled from enrichment.
**Functions:**
- `ingest_path(path, *, force=False, dry_run=False) -> IngestReport`
  # discover files → `sources.read_file` → `build_session` → `identity.resolve_speakers` (sets metadata) → `save_session` (or `replace_session` if force)
- `_iter_files(path) -> Iterable[Path]`; `_read(path) -> Any`
- `IngestReport`: `stored:int, skipped:int, failed:list[(path,err)]`
**Critical:** **never calls the LLM** (identity is deterministic). A credit outage cannot lose
ingested data — enrich runs later via `enrich_pending`. Idempotent; `--force` → `replace_session`.

### G10. `eval.py` (NEW)
**Responsibility:** run enrichment over the golden set and score it; the regression gate.
**Functions:** `run_eval(golden_dir=GOLDEN_DIR, *, llm=None) -> EvalReport`;
`_score(derived, expected) -> dict` (signal coverage, entity P/R); `_load_golden(dir)`; `EvalReport`
(+`save_baseline`/`diff_baseline`).
**Critical:** deterministic metrics only; summary stays manual-eyeball v1. Needs the LLM up to run.

### G11. `cli.py` (MODIFY — subcommand dispatcher)
- `transcripts ingest <path> [--force] [--dry-run]`   → `ingest.ingest_path`
- `transcripts link [--session ID]`                   → `identity.link_identities` (re-link after directory grows)
- `transcripts enrich [--all|--pending] [--session ID]` → `enrich.enrich_pending`
- `transcripts eval`                                  → `eval.run_eval`
- `transcripts serve [--port]`                        → run the read API (uvicorn) for the dashboard
- *(KEEP)* single-file quick run (`render_markdown`) for stdout piping.

### G12. `api/transcripts_routes.py` (NEW)
**Responsibility:** read-only HTTP surface for the dashboard; derived-only projection (no raw leak).
- `GET /transcripts/sessions` → `list[Card]`           # newest first (Phase 1 all-access)
- `GET /transcripts/sessions/{id}` → `SessionView`     # derived + metadata; raw gated (1.5)
- `to_card(session) -> dict`                            # {session_id, date, source, summary, signals, resolved_speakers, seed}
- `can_see(viewer, session) -> bool`                    # **stub returns True**; real impl at 1.5
- `router = APIRouter(prefix="/transcripts")`
**Critical:** **never serialize `raw_diarization`** to responses — only `derived` + safe metadata
(summary, signals, resolved_speakers). The raw-leak guard is an explicit test (§I).

### G13. `web/` (NEW — the flashy dashboard)
- `index.html` — shell; loads app.js, styles.css, shape-ui
- `app.js` — `loadSessions()` → `renderCard(card)` (header w/ resolved names, summary, bullet signals
  by kind) → `mountShape(canvas, {seed: card.session_id})`
- `styles.css` — dark editorial theme, card grid, motion
- `shape-ui/` — vendored `packages/shape-ui` (copy; **retain MIT notice**); per-card `mountShape`
**Critical:** verify shape-ui renders standalone (use per-card `mountShape`, not the shared-overlay
`data-shape-*` path). Served by `transcripts serve` (static mount) — no build step, no framework.

### G14. `main.py` (MODIFY)
Mount `transcripts_routes.router`; optional `app.mount("/dashboard", StaticFiles(web/))`. Keep
transcript routes on their own prefix — don't entangle with Conclave skill routes (clean extraction).

---

## H. Execution — commit-and-test sequence (Phase 1)

### H.0 Discipline (the anti-domino rules)

- **Branch:** `transcripts-phase1` off the default branch; never commit WIP to the default branch.
- **Green trunk, always.** Every commit leaves the **full suite green**:
  `CONCLAVE_DISABLE_SCHEDULER=1 .venv/bin/python -m pytest -q --ignore=external --ignore=tests/test_interview_reflection_mcp.py`
  Run it before each commit. No red commit ever — the rule that stops a domino.
- **Tests gate progression.** A step isn't done until its gate passes; the next doesn't start.
- **Offline tests.** Every LLM-touching test injects `FakeLLM` → suite needs zero credits/network.
- **Behavior-preservation net.** The 7 `test_transcript_pipeline.py` tests guard the **C2 parse
  refactor** (C1 is purely additive). If they go red, the refactor changed observable behavior.
- **Commit style:** lowercase area prefix + em-dash (`transcripts: ingest — raw capture`).
  **No `Co-Authored-By` trailer** (project rule).

### Commit sequence

**C1 — `sources.py` reader + `NormalizedInput` (additive; parse untouched)**
- *Files:* NEW `sources.py`.
- *Steps:* define `NormalizedInput`; implement `read_obj`/`read_file` for the line + JSON forms
  (incl. the existing `{segments:[{t,speaker,text}]}` shape so parse can route through it). Labels
  pass through verbatim.
- *Test gate — `test_sources.py`:* a `Name:`/`Speaker N:` text sample → expected segments; a JSON
  sample → expected segments; **existing 7 green** (parse still has its own path this commit).
- *Commit:* `transcripts: source reader (sources.py) + NormalizedInput contract`
- *Note:* exact format finalized when the real sample lands (§M); scaffold + contract land now.

**C2 — parse.py becomes the generic normalizer**
- *Files:* MODIFY `parse.py` (add `build_session`/`_segments`/`_session_id`/`_metadata`; thin
  `parse_transcript` → `sources.read_obj` → `build_session`; delete `_collect_batches`/`_infer_source`/`_normalize_segment`).
- *Test gate:* **existing 7 still green** (proves behavior preserved); + `build_session` units.
- *Commit:* `transcripts: parse.py — generic normalizer over NormalizedInput`
- *Safe boundary:* `parse_transcript` external API unchanged; tests prove it.

**C3 — model fields + storage helpers**
- *Files:* MODIFY `models.py` (+visibility/owner/model_id/enrich_prompt_version/chunk_count);
  MODIFY `store.py` (+`list_pending`/`replace_session`/`set_visibility`); MODIFY `storage/sqlite.py`
  (+`delete_transcript_session`).
- *Test gate (extend `test_transcript_pipeline.py`):* round-trip with new fields; `list_pending`
  returns only derived-empty/stale; `replace_session` deletes+resaves; existing store tests green.
- *Commit:* `transcripts: provenance/visibility fields + pending/replace store helpers`

**C4 — batch ingest (no LLM) ⭐ milestone: raw in DB**
- *Files:* NEW `ingest.py`; MODIFY `cli.py` (dispatcher + `ingest`).
- *Steps:* discover files → `sources.read_file` → `build_session` → `save_session`/`replace_session`.
- *Test gate — `test_ingest.py`:* fixtures dir → N sessions with `derived` null; **idempotent
  re-ingest** (no dup, raw unchanged); `--force` replaces; **LLM never constructed** (monkeypatch
  `config.get_llm` to raise).
- *Commit:* `transcripts: batch ingest — raw capture, no LLM + ingest CLI`

**C5 — mock identity linkage (no LLM)**
- *Files:* NEW `identity.py`; MODIFY `ingest.py` (call `resolve_speakers` after `build_session`);
  MODIFY `cli.py` (`link` subcommand).
- *Steps:* `MOCK_DIRECTORY` (name→mock record_id); `resolve_identity`; `resolve_speakers` populates
  `metadata.resolved_speakers`; `link_identities` re-link pass.
- *Test gate — `test_identity.py`:* known name → mock id; `Speaker 1` → unresolved (absent);
  ingest populates `resolved_speakers`; `link_identities` re-links after directory grows;
  **deterministic, LLM never called.**
- *Commit:* `transcripts: mock identity linkage (resolve_identity seam)`
- *Safe boundary:* one chokepoint; real cohort/voiceprint lookup swaps here later (§K).

**C6 — reliable LLM layer**
- *Files:* NEW `llm.py`.
- *Test gate — `test_llm.py`:* valid JSON parsed; garbage→repair retry→valid; `required_keys`
  missing→raise; simulated 402/connection → `LLMUnavailable`.
- *Commit:* `transcripts: reliable JSON LLM invoke + access guard (llm.py)`

**C7 — chunker + pipeline constants**
- *Files:* NEW `chunk.py`, NEW `config.py`.
- *Test gate — `test_chunk.py`:* short→1 chunk; long→N with overlap; oversized turn split;
  **chunk union covers original text**.
- *Commit:* `transcripts: turn-aware chunking with overlap + pipeline constants`

**C8 — map-reduce enrichment + prompts + backfill ⭐ milestone: derived populated**
- *Files:* NEW `prompts.py`; MODIFY `enrich.py` (map-reduce, `enrich_pending`); MODIFY `cli.py`
  (`enrich`). Uses C6/C7.
- *Test gate — `test_enrich_mapreduce.py`:* FakeLLM single + multi-chunk reduce (summary synth,
  entity dedup, signals ≤ cap); `enrich_pending` only touches pending and **continues past
  `LLMUnavailable`**; provenance stamped.
- *Commit:* `transcripts: map-reduce enrichment + versioned prompts + backfill pass`

**C9 — eval golden set**
- *Files:* NEW `eval.py`.
- *Test gate — `test_eval.py`:* P/R/coverage math correct on a **synthetic** hand-built case (verify
  the metric, not the LLM). Real golden fixtures land with samples (§M).
- *Commit:* `transcripts: eval golden-set runner + set-overlap metrics`

**C10 — read API**
- *Files:* NEW `api/transcripts_routes.py`; MODIFY `main.py`.
- *Test gate — `test_api_transcripts.py`:* card shape; **`raw_diarization` never in any response**;
  `/{id}` returns derived+metadata; `can_see` stub allows all.
- *Commit:* `transcripts: read API — derived-only session projection`

**C11 — stylized dashboard ⭐ milestone: the demo**
- *Files:* NEW `web/{index.html,app.js,styles.css}` + vendored `web/shape-ui/` (MIT notice);
  MODIFY `cli.py` (`serve`).
- *Test gate:* smoke — `serve` boots, `/` 200, `/transcripts/sessions` reachable, assets 200.
  **"looks flashy" = human visual check.**
- *Commit:* `transcripts: stylized per-meeting dashboard (vendored shape-ui, MIT)`

### Critical path & parallelism

- **Demo path:** C1 → C2 → C3 → C4 → C8 → C10 → C11. (C6, C7 are prereqs of C8; C5 identity and C9
  eval run in parallel.)
- **No-LLM milestones (C4 raw, C5 identity)** are reachable today with zero credits — start here.
- **Enrich milestone (C8)** needs the LLM unblocked (NearAI top-up / dev-Ollama, qwen2.5:14b).

---

## I. Test inventory & pyramid

Each test file is the **gate** for the commit named in §H. Full suite green before *every* commit.
Run: `CONCLAVE_DISABLE_SCHEDULER=1 .venv/bin/python -m pytest -q --ignore=external --ignore=tests/test_interview_reflection_mcp.py`

| Test file | Gates | Level | Key assertions |
|---|---|---|---|
| `test_transcript_pipeline.py` (HAVE) | C2, C3 | unit | 7 existing stay green = behavior preserved through refactor; build_session; new fields |
| `test_sources.py` | C1 | unit | line + JSON forms → expected segments; labels (names + `Speaker N`) pass through verbatim |
| `test_ingest.py` | C4 | integration | idempotent re-ingest (no dup, raw unchanged); `--force` replaces; **LLM never constructed** |
| `test_identity.py` | C5 | unit | name → mock id; `Speaker N` → unresolved; ingest fills `resolved_speakers`; re-link; **no LLM** |
| `test_llm.py` | C6 | unit | valid JSON; garbage→repair→valid; `required_keys` missing→raise; 402/conn → `LLMUnavailable` |
| `test_chunk.py` | C7 | unit | short→1 chunk; long→N with overlap; oversized turn split; **chunk union covers original** |
| `test_enrich_mapreduce.py` | C8 | unit | FakeLLM single + multi-chunk reduce; entity dedup; signal cap; `enrich_pending` **survives `LLMUnavailable`**; provenance |
| `test_eval.py` | C9 | unit | metric math correct on a hand-built synthetic case |
| `test_api_transcripts.py` | C10 | integration | card shape; **`raw_diarization` never in any response**; `can_see` stub allows all |
| dashboard smoke + manual | C11 | manual | `serve` boots, `/` 200, assets load; **"looks flashy" = human visual check** |

**Pyramid:** mostly unit (sources, parse, identity, chunk, llm, enrich, store, eval) → thin
integration (ingest, API) → one manual visual gate (dashboard). No browser automation in Phase 1.

**Two assertions worth never losing:** (1) the **7 legacy tests green** through C2 (refactor safety),
and (2) **raw never leaves the API** (C10 privacy). Highest blast radius.

All LLM-touching tests inject `FakeLLM` → suite runs with **zero credits / zero network**.

---

## J. Phase 1.5 & Phase 2 — structural-only (do NOT build yet)

**1.5 Permissions** (build once, stable after):
- `models`: `visibility`/`owner` already present (D).
- `api`: implement real `can_see(viewer, session)` (membership/role) — the one-function swap.
- `store`/`sqlite`: promote `visibility` to a typed column + index when SQL pushdown needed.
- New `auth.py` (viewer → role); membership-keyed (vs Phase-1 speaker-keyed) when membership lands.

**2a–2d Intelligence** (forward-declared; shapes firm up against real Phase-1 data):
- `match/entities.py` — `resolve_entities(session, graph) -> graph_nodes`; reads `cohort-surface.json`.
- `match/relations.py` — `find_relations(sessions) -> relations`; co-occurrence first.
- `query/prep.py` — `prep_brief(meeting, history) -> brief`.  `query/ask.py` — agentic organizer query.
- `graph/sros.py` — real Cohort-OS adapter (this is also where `identity.resolve_identity` graduates
  from mock to real lookup).
- `embed.py` — only when 2b needs it: `all-MiniLM-L6-v2`, numpy cosine, in-TEE.

---

## K. Extension points (future connections — keep these seams OPEN)

The whole point of the structure: future connections plug in at **named seams** without touching
store/enrich/dashboard. Don't build them now — keep them addable.

**1. Source connections (VoxTerm, Gemini, Matrix) → `sources.py`.**
- Now: `sources.read_file` for hand-provided files. Future: add `from_voxterm_batch(batch) ->
  NormalizedInput`, `from_gemini(export) -> NormalizedInput`, etc. — each produces the **same
  `NormalizedInput`** into the **same** `ingest`/`build_session`. Downstream unchanged.
- When there are **2+ auto-detected sources**, `sources.py` grows a `detect_source()` + registry
  (the adapter layer deferred in §B.4). Not before.
- **Live VoxTerm** also needs a sink endpoint: `POST /hivemind/transcripts` in
  `api/transcripts_routes.py` (or a sibling) → normalizes batches → `ingest`. The CVM *is* the sink.

**2. Identity (real Cohort OS, voiceprint IDs) → `identity.resolve_identity`.**
- Now: `MOCK_DIRECTORY` lookup. Future: swap the body to read `cohort-surface.json` / swf-node
  `/graph`, and (when VoxTerm carries them) consult voiceprint profile UUIDs. **One function changes.**

**3. Permissions (membership/role) → `api.can_see` (+ `auth.py`).** Stub → real at 1.5.

### Two assumptions to NOT weld (or the seams won't fit later)
- **Stable `session_id`, not "one file = one session."** VoxTerm is streaming (batches accumulate by
  record_id); keep `session_id` derivation stable and the write-once-raw invariant explicit, so the
  future streaming path is "accumulate → save once" with no store-contract change.
- **Identity only via `resolve_identity`.** Never scatter name→id logic elsewhere.

---

## L. Explicitly OUT of scope for Phase 1 (anti-scope — do not build)

- **No live source connections / no adapter registry.** Phase 1 ingests **hand-provided transcript
  files** via the single `sources.read_file`. VoxTerm/Gemini/Matrix wiring + `detect_source`/registry
  are future, at the `sources.py` seam (§K).
- **Local + all-access deployment.** Phase 1 runs entirely local (local SQLite/API/dashboard),
  login-for-everyone. *Confidential-by-design is a CVM deployment property — the local MVP is NOT
  confidential, and that's fine: own consented/public test data on a local box.* `can_see` = stub True.
- **No embeddings / vector store** — no matching in Phase 1; scale small. (`embed.py` is Phase 2.)
- **No cross-transcript relations / graph rendering** — dashboard is per-meeting only.
- **No real-time / streaming ingest** — completed transcript files only.
- **No real Cohort-OS lookup** — identity is mocked via `MOCK_DIRECTORY`.
- **No personality extraction** — open vertical, later.
- **No self-hosted generative LLM** — NearAI (TEE) for cohort runs; Ollama (qwen2.5:14b/gemma2:9b) on
  the laptop for dev/eval only. Confidential GPU TEE = Phase 2/3 scale-out.
- **No standalone repo extraction** — stays in `transcripts/`; keep seams clean for later.

---

## M. Decisions (resolved + remaining)

**Resolved:**
1. **Convergence point** ✅ — everything converges at `NormalizedInput` → `Session` (logical) and one
   `ingest_path` + one store (operational). New source = one `sources` reader; nothing downstream changes.
2. **LLM** ✅ — top up **NearAI** (TEE, trivial cost at our volume) for cohort runs; **Ollama
   (qwen2.5:14b / gemma2:9b) on the laptop for dev/eval only**. NearAI is a TEE too — axis is
   cost/control, not privacy. Set local `num_ctx` ≥ `CHUNK_MAX_TOKENS`. Confidential GPU TEE later.
3. **Dashboard host** ✅ — local + all-access for Phase 1; standalone static page via `transcripts serve`.
4. **`shape-ui` license** ✅ — MIT (© 2026 dmarz); vendor freely, retain the notice. `"private":true`
   is an npm-publish guard, not a legal restriction.
5. **Sources are future; input is hand-provided files** ✅ — single `sources.read_file` now;
   VoxTerm/Gemini at the §K seam.
6. **Identity is mocked now** ✅ — `identity.resolve_identity` + `MOCK_DIRECTORY`; real Cohort-OS /
   voiceprint lookup swaps in at the same function (§K).

7. **Transcript format + sample** ✅ — Otter.ai-style export (`Name  M:SS\n<body>\n\n`), 13 real
   workshop transcripts at `external/shape-rotator-os/apps/os/src/content/context/raw-scripts/`.
   Full format spec in §G1 (incl. parenthetical labels, anonymous speakers, BOM, filename dates).
8. **`MOCK_DIRECTORY` source** ✅ — built from `external/shape-rotator-os/cohort-data/people/*.md`
   frontmatter (real cohort `record_id` + `name`), not invented. Spec in §G2.
9. **Test fixtures = real cohort transcripts, committable** ✅ — all 13 Otter-style transcripts
   copied to `tests/fixtures/transcripts/` (~1.2 MB). They're **already public** via the
   `shape-rotator-os` GitHub repo, so committing the duplicate here adds zero new exposure. CI/tests
   run against the real corpus, no synthetic mocks needed.

**No remaining blocking decisions.** One operational task before C8 (enrichment) can run:
- **LLM unblock** — top up NearAI (credit cap hit) **or** set `CONCLAVE_LLM_BACKEND=ollama` +
  `ollama pull qwen2.5:14b-instruct` (Apple Silicon M-series handles 14B comfortably). Set
  `num_ctx` ≥ `CHUNK_MAX_TOKENS` so long transcripts don't silently truncate. Not a decision; a switch.
```

---

## v1 Improvements — Post-PoC

> Minimal-change, maximum-impact lift to Phase 1 extraction quality, between the current PoC (commits up to `36e1feb`) and Phase 1.5 (permissions). Adds a per-team **context XML** for few-shot grounding, schema fixes (mostly additive; one breaking `Signal` field rename), a richer participant model, and a tightened prompt. No architectural reshuffle.
>
> **Companion docs:** `../METHODOLOGY_SURVEY.md` (literature), `../DECISION_INPUTS.md` (empirical inputs), `BUILD_PLAN.md` (strategy), this file (execution). `BUILD_PLAN.md` carries a parallel set of edits (architecture, compute model, list B, phases, connector roadmap, open questions) — applied in the same v1 cycle.

### 1. Why v1 — the diagnosis

The Phase 1 PoC ships end-to-end (parse → enrich → store → API → dashboard, C1-C11 done). It works as a demo. But signal quality is mediocre, and the diagnosis is **model-agnostic** — the four root causes below hold for any backend (local qwen-7B per `cf40f73`, hosted Gemma 3 27B per `36e1feb` — the current production default, or whatever lands in this slot next):

- **Zero-shot prompt.** `prompts.py` asks for "3-8 signals" with no examples and no contrast. The model converges on the safe default (`kind=insight`) — observed in `office-hours-transcript.txt` and `project-intros-agents-day-3-transcript-may-21.txt` where nearly every extracted signal is `insight` despite obvious decisions and action items in the source.
- **Generic entity taxonomy.** Current `Entity.type ∈ {person | project | concept | org}` has no `technology` bucket, so TDX / SGX / RATLS / Opus 4.0 / Whisper / Matrix all collapse to `concept`. The "concept" type becomes meaningless.
- **No team priors.** The model has no anchor list of what projects, technologies, or topics this cohort actually works on, so it can't tell "EZTE" is a project worth canonicalizing, "Make OSI" needs the spelling fix, or "Flashbots" and "Flash Bots" are the same thing.
- **Conflated participant roles.** `Signal.speakers` lumps "who spoke this turn" with "who the signal is about," and there's no record of who else was *listening* in the room. A 3-person panel with 30 audience members extracts the same as a 1-on-1 — we lose the participant graph.

Observed in real enriched outputs at `enriched-output*/` (repo root, gitignored) — including the qwen baseline, the Gemma 6K and Gemma 12K runs.

**Strategy.** v1 fixes all four cheaply: a per-team XML of priors + few-shot examples (§2), schema changes — mostly additive, one breaking rename plus a participants slot (§3), a tightened prompt (§4), tighter identity / dedup (§5–§6). Versioning + backfill (§7) lets us iterate. Verification (§8) is by side-by-side spot check across the existing `enriched-output*/` variants and an organizer walk-through — not formal eval — per the no-mass-annotation constraint in `../DECISION_INPUTS.md` §C and §H.

**What's NOT in v1.** Vector store, FTS5, graph layer, bi-temporal facts, cross-meeting connections, real Google Meet / Zoom / calendar attendance connector — all Phase 2 or later. The bright line is per-meeting extraction quality (v1) vs. cross-meeting intelligence (Phase 2). v1 doesn't add a single SQL table; everything is additive JSON.

### 2. The team-context XML — the load-bearing change

The single most impactful change in v1: a per-team file giving the model domain priors and few-shot examples that it can't infer from a transcript alone. **For v1 the file is hand-authored as if it were exported from a future cohort-OS ingestion connector.** The connector itself is deferred (§9). The core pipeline doesn't care where the file came from; it reads it from a path.

#### 2.1 What's in the file

```xml
<team_context>
  <team>
    <name>Shape Rotator Cohort</name>
    <domain>confidential AI infrastructure</domain>
  </team>

  <known_projects>
    <project name="Conclave" aliases="conclave">
      Cohort context intelligence layer running in TEE.
    </project>
    <project name="Phala" aliases="phala network,phala">
      Confidential compute network providing CVM (TEE) execution.
    </project>
    <project name="DStack" aliases="D-Stack,dstack">
      Stack for running TDX workloads.
    </project>
    <!-- … -->
  </known_projects>

  <known_technologies>
    <tech name="TDX" kind="standard">Intel Trust Domain Extensions</tech>
    <tech name="SGX" kind="standard">Intel Software Guard Extensions</tech>
    <tech name="TEE" kind="concept">Trusted Execution Environment</tech>
    <tech name="RATLS" kind="protocol">Remote Attestation TLS</tech>
    <tech name="MCP" kind="protocol">Model Context Protocol</tech>
    <!-- … -->
  </known_technologies>

  <known_topics>
    <topic>attestation</topic>
    <topic>reproducible builds</topic>
    <topic>context management</topic>
    <topic>cohort programs</topic>
    <!-- … -->
  </known_topics>

  <extraction_examples>
    <example>
      <chunk>
[Hang] Yeah, we want to get rid of TPM.
[Alex] OK, this also supports backwards compatibility for that.
[Hang] Right, we should remove the TPM dependency from the GCP variant.
      </chunk>
      <expected>
        {
          "summary": "Team decided to remove TPM dependency from the GCP variant, with backwards compatibility preserved.",
          "signals": [
            {"kind": "decision",
             "text": "Remove TPM dependency from the GCP variant",
             "source_quote": "we should remove the TPM dependency from the GCP variant",
             "said_by": ["Hang"],
             "about_person": []}
          ],
          "entities": [
            {"name": "TPM", "type": "technology", "evidence": "explicit removal target"},
            {"name": "GCP", "type": "org", "evidence": "deployment target for the variant being modified"}
          ],
          "topics": ["attestation", "platform compatibility"]
        }
      </expected>
    </example>
    <!-- 2-3 more examples, varied in shape: one action_item, one open_question, one with a Speaker N anonymous label -->
  </extraction_examples>

  <style_guide>
    <kind name="decision">A course of action the group agreed on. Past or present tense ("we decided", "let's go with").</kind>
    <kind name="action_item">A concrete next step someone agreed to do. Often "I'll send", "you handle", "can you".</kind>
    <kind name="open_question">A question raised in this chunk that is NOT answered within the same chunk.</kind>
    <kind name="insight">A non-obvious observation or learning. Use sparingly — prefer a more specific kind when one fits.</kind>
    <kind name="impactful_point">A consequential statement that doesn't fit decision/action/question but matters for prep. Use rarely.</kind>
  </style_guide>

  <open_world_note>
    The lists above are NON-EXHAUSTIVE. New projects, technologies, people (including guests joining a single meeting), and topics WILL appear in transcripts and must be extracted faithfully even when not listed here. Treat the lists as ANCHORS for known entities, not as a closed vocabulary.
  </open_world_note>
</team_context>
```

#### 2.2 How it's consumed

- **New module:** `transcripts/team_context.py` — loads the XML once at process start, renders it to a single string fragment for splicing into prompts.
- **Path:** resolved from `CONCLAVE_TEAM_CONTEXT` env var. Default points to a worked example shipped at `transcripts/team_context.example.xml` (Shape-Rotator-cohort flavored) so the demo works out of the box.
- **Splice point:** between the security data-injection guard and the JSON contract in both `SINGLE_SYSTEM` and `CHUNK_SYSTEM` in `transcripts/prompts.py`. Format is roughly what the model sees — adopters reading the XML can predict what's in the prompt. Transparency = adoption.
- **Cached:** loaded once per process; `enrich_pending` doesn't re-read it per session.

#### 2.3 Boundary commitment

The XML is a **STATIC curation artifact** the adopter maintains. It is NOT a snapshot of dynamic cohort-OS graph state, NOT a feed of "who's working on what right now," NOT a pull from a live API. The bright line:

- **OK to include** (and what the file is for): project names, technology vocab, topic taxonomy, style examples, open-world note. Facts the adopter explicitly hands the system as "this is what we work on."
- **NOT OK to include** (would break portability): current standings, recent decisions made in OTHER meetings, live progress trackers, individual status. That's Phase 2 graph-traversal territory and leaking it back into per-meeting extraction couples Phase 1 and Phase 2 in a way that breaks the "works for every team" property.

This boundary is what makes v1 portable: a new adopter writes their own XML, points `CONCLAVE_TEAM_CONTEXT` at it, and the system works. No code changes, no connector setup, no cohort-OS API binding.

#### 2.4 Token budget

For local **qwen2.5:7B** at `num_ctx=8192`:

- Team context priming: ~800 tokens (lists + 3 examples + style guide)
- System prompt + JSON contract: ~700 tokens
- Total priming: ~1.5K tokens
- Available for chunk: ~6K tokens

Matches existing `CHUNK_MAX_TOKENS=6000` in `transcripts/config.py` — no chunk-budget retuning required on the local path.

For hosted **Gemma 3 27B** at 54K context (the current production default): ample headroom — the 12K chunk experiment (see `enriched-output-gemma3-12k/`) ran cleanly even with the priming overhead. The chunk-budget decision (6K vs 12K hosted) is orthogonal to v1 and tracked separately.

#### 2.5 Multi-pass alternative — considered, deferred

Two-call extraction (entities first, signals second, with entities-from-pass-1 fed to pass-2) is a known pattern from Itext2KG (see `../METHODOLOGY_SURVEY.md` §5). For our config it would push effective chunk budget below 4K per turn (carrying both the original chunk AND the previous output), and quality would likely regress. Defer unless rich single-pass plateaus.

### 3. Schema additions

All storage additions are additive on the JSON column — no SQL migration. **One breaking source-level rename** (`Signal.speakers` → `Signal.said_by`) is budgeted as v1 implementation work; affects 3 test files plus `cli.render_markdown` and `web/app.js`. Bump `ENRICH_PROMPT_VERSION` (§7) so backfill picks up the new fields automatically via `enrich_pending`.

| Field | Where | Why |
|---|---|---|
| `Entity.type ∈ {... , "technology"}` | `transcripts/models.py` `Entity.type` + `transcripts/enrich.py` `_VALID_ENTITY_TYPES` + prompt entity-type vocabulary | Recovers an entire entity class currently dumped into `concept`. Observed misclassifications: TDX, SGX, RATLS, Opus 4.0, Whisper, Matrix, MCP, ATLS all tagged `concept` in real outputs. |
| `Signal.source_quote: Optional[str]` | `transcripts/models.py` `Signal` + prompt requirement + `transcripts/enrich.py` `_to_derived` + `_dedup_signals` | Verbatim quote (≤120 chars) anchoring the signal to a span in the chunk. **API-served alongside the rest of `derived`** — the TEE is the privacy boundary, not the API field surface; a 120-char highlight is no more sensitive than the model-paraphrased `signals[].text` already returned. The C10 raw-leak guard continues to protect `raw_diarization` (the FULL transcript blob) from leaking. Useful for: dashboard quote chips, dev spot-checks, future debugging. |
| `Signal.said_by: list[str]` **replaces** `Signal.speakers` | `transcripts/models.py` + prompt + `_to_derived` + `_dedup_signals` + `cli.render_markdown` + `web/app.js` + 3 test files (`test_transcript_pipeline.py`, `test_enrich_mapreduce.py`, `test_api_transcripts.py`) | **Breaking rename.** Verbatim speaker labels at the turn the signal was extracted from — disambiguates "who literally spoke" from "who's the subject." Coordinated updates across tests, CLI digest, and dashboard chips are part of v1 implementation work; no DB migration because the rename is JSON-side. |
| `Signal.about_person: list[str]` (NEW, default `[]`) | same set | Explicit subjects of the signal — may or may not be in the meeting. Captures *"Hang mentioned Tina to Andrew"* → `said_by=["Hang"]`, `about_person=["Tina","Andrew"]`. Tina may not be on the call at all; that's the point. |
| `SessionMetadata.participants: Optional[list[str]]` (NEW, default `None`) | `transcripts/models.py` `SessionMetadata` + ingest-side stub | Explicit attendance list when known. v1 leaves this `None` (no connector yet); future Google Meet / Zoom / calendar connectors populate it. **Listeners are derived, not stored:** for any signal, `listeners = (participants or members) − said_by`. In v1 with no connector, "listeners" is an undercount because `members` only contains people who spoke; once attendance lands the count becomes accurate. The dashboard can show "spoken by Hang · listeners: 12 others · about: Tina, Andrew" without a per-signal field. See `BUILD_PLAN.md §6` for connector roadmap. |
| `Entity.cohort_status: Literal["member", "external", "unknown"]` | `transcripts/models.py` `Entity` + `transcripts/enrich.py` `_dedup_entities` post-process (only for `type=person`) | Derived deterministically from `MOCK_DIRECTORY` (no LLM call) AFTER the dedup pass. `member` = matched roster; `external` = Person extracted but not in roster (Kevin, Alex from Flashbots, Hang); `unknown` = ambiguous parenthetical that didn't resolve. Powers dashboard chip styling (green / amber / grey) without runtime lookups. |
| `Entity.affiliation: Optional[str]` | `transcripts/models.py` `Entity` + `transcripts/identity.py` parenthetical handling + `_dedup_entities` | Captured from parenthetical labels ("Alex (flashbots?)" → `affiliation="flashbots"`) when the base name doesn't resolve to the roster. Useful for the dashboard: "external — flashbots". |
| `Derived.topics: Optional[list[str]]` | `transcripts/models.py` `Derived` + prompt extracts 3-6 per chunk + `transcripts/enrich._reduce` deterministic dedup (no LLM) | Separate from entities — topics are themes/areas ("attestation", "context management", "RAG"), entities are named things ("Phala", "Conclave"). Distinct in nature AND in dashboard role: topics filter the meeting list; entities populate chips on a meeting card. Reduce step: concat → lowercase → dedup → cap at 8. |

**Schema seam preserved.** All additions live in the JSON `metadata` / `derived` columns. The Phase-1.5 `visibility` / `owner` fields (already present per §D) are unaffected. The bi-temporal / graph-edge shapes flagged in `../METHODOLOGY_SURVEY.md §9` for Phase 2 are NOT added in v1.

### 4. Prompt overhaul

The current `transcripts/prompts.py` has good security and language guards but is zero-shot and loose on counts. v1 tightens:

- **Few-shot examples per signal kind.** 4 examples in `CHUNK_SYSTEM` covering decision / action_item / open_question / insight with the SAME speaker pattern so the model learns the CONTRAST, not just the labels. Comes from the `<extraction_examples>` block in the team context XML.
- **Decision-led summary style example.** Replace the current generic "what was actually discussed and decided" guidance with one concrete contrast — show one good summary ("Team decided to switch from RATLS to ATLS; agreed to use EZTE for reproducible builds; open question on Kubernetes migration") vs. one bland summary ("The conversation covered various topics including X, Y, Z") and label the latter as the anti-pattern to avoid.
- **Anti-hallucination rule.** Explicit: "If you are not confident about a person's name, term, or attribution, OMIT the entire item rather than guess. Never emit placeholder text like `<NAME>` or invent names not present in the transcript." Kills the observed `<NAME> (person)` placeholder in `dstack-hangout` and invented entities like `Tita (person)` and `near credits (person)`.
- **Transcription-fix policy.** "Only correct an obvious transcription error (e.g. 'Optus 4.0' → 'Opus 4.0') if the corrected term appears in `<known_technologies>` or `<known_projects>`. Otherwise preserve the surface form as-is." Avoids the model freelancing corrections.
- **One-line semantic definitions per entity type.** In the prompt:
  - `person` — an individual human
  - `project` — a named ongoing effort (codebase, product, initiative)
  - `technology` — a tool / library / protocol / standard / framework
  - `org` — a company or organization
  - `concept` — anything else (use sparingly)
- **Tighter signal-count guidance.** "Emit AT MOST 6 signals per chunk; prefer fewer high-quality ones over many bland ones."
- **Source-quote requirement on every signal.** "Every signal MUST include a `source_quote` field containing the verbatim text span (≤120 chars) from the chunk that the signal is extracted from. If you can't point to a specific span, don't emit the signal."
- **Said-by vs about-person rule.** "`said_by` is the verbatim speaker label(s) at the turn the signal is anchored to. `about_person` is filled ONLY when the signal is clearly about someone distinct from the speaker (an addressee, a mentioned person, a third party). For most signals `about_person` is `[]`."

`REDUCE_SYSTEM` stays simple — summary-only merge as today, no change.

### 5. Identity layer fixes

`transcripts/identity.py` currently resolves only verbatim or simple-normalized matches against `MOCK_DIRECTORY`. Observed failures: Alex (flashbots?) → missed; Hang → missed; Wiki → missed; "Andrew Hang" (an invented merge of "Andrew Miller" + "Hang") → not caught downstream.

Three fixes:

- **Parenthetical handling.** `_normalize_name` strips parentheticals BEFORE roster lookup ("Alex (flashbots?)" → "Alex" → try roster). If no match on the base name, the parenthetical content is retained as an **affiliation hint** stored on the resulting Person entity (`affiliation="flashbots"`, see §3) so external mentions carry context.
- **External-person tracking.** When the LLM extracts a Person whose name doesn't match the roster:
  - Currently: silently kept in the entity list with no status.
  - v1: stamped `cohort_status="external"` post-dedup. Affiliation preserved if available. The dashboard can render external mentions distinctly (grey chip vs. green).
- **Speaker-label ↔ Person-entity linkage.** When a Person entity's name matches a session's speaker label (verbatim OR after `_normalize_name`), link them: populate `said_by` on signals where this Person appears as the subject, so the dashboard can chip-link "Alex said this" → speaker turn.

`MOCK_DIRECTORY` loading from `external/shape-rotator-os/cohort-data/people/*.md` stays as-is (per §G2).

### 6. Dedup tightening

`transcripts/enrich.py` `_normalize_for_dedup` is currently `" ".join(s.lower().split())` — whitespace-collapse only. Observed failure: `Flashbots (org)` and `Flash Bots (org)` both stored, no merge.

Extended normalization:

- Lowercase + whitespace-collapse (current)
- PLUS strip internal spaces ("Flash Bots" → "flashbots")
- PLUS strip light punctuation (`.`, `,`, `'`, `"`)
- Optional Levenshtein-1 merge gated behind `STRICT_DEDUP=false` env (off by default to avoid surprise merges of legitimate distinct entities like "Sam" / "Sami")

When duplicates collapse, the `evidence` strings from all surface forms are joined with `"; "` (current behavior, kept).

When `cohort_status` differs across duplicates (e.g., one says `external`, another says `unknown`), the more specific value wins (`member` > `external` > `unknown`).

### 7. Versioning + backfill

- **Bump `ENRICH_PROMPT_VERSION`** in `transcripts/prompts.py`: `"v1"` → `"v2"`. `enrich_pending` already keys backfill off this field via `store.list_pending(current_prompt_version)` (per §G7). All previously-enriched sessions are now considered stale and will be re-enriched on the next `enrich --all` or `enrich --pending` run.
- **New `metadata.team_context_version: Optional[str]`** in `transcripts/models.py` `SessionMetadata`. Stamped by `enrich_session` with a short SHA-256 prefix (first 8 chars) of the loaded team_context XML body. Lets us A/B different XML versions across enrichment runs without conflating with prompt changes.
- **Re-run.** Once v2 prompts + XML are in place: `transcripts.cli enrich --all` over the existing 12 stored sessions to populate v2 derived. (Or `enrich --pending` if `only_stale=True` is sufficient.)

**v1 is model-agnostic; no further backend swap planned within v1.** Current production default is `redpill/google/gemma-3-27b-it` (per `36e1feb`); the local-dev default is `qwen2.5:7b` (per `cf40f73`). v1 improvements apply to both — the diagnosis is at the prompt + schema layer, not the model layer. If after re-enrichment quality still feels small on a specific backend, model swap is the next axis to explore, but ON the new prompt + schema baseline so we can measure the delta cleanly.

### 8. Verification (no formal eval)

Per the **no-mass-annotation constraint** (1-2 transcripts max for ground truth) from `../DECISION_INPUTS.md §C` and `§H`. v1 ships without an F1 eval set. Verification is side-by-side spot-check across the existing `enriched-output*/` variants and a walk-through with the cohort organizer.

Current variants on disk:

```
enriched-output/                     ← qwen-7B local (baseline)
enriched-output-gemma3/              ← Gemma 6K (default chunk budget)
enriched-output-gemma3-12k/          ← Gemma 12K experiment
```

Procedure:

1. **Re-enrich** all 12 stored sessions with `transcripts.cli enrich --all` on the current default backend (Gemma 3 27B via RedPill).
2. **Dump** outputs to a new sibling folder, e.g. `enriched-output-gemma3-v1-<chunkbudget>/`, so the v1 run sits next to the prior variants for organizer-eyeball comparison.
3. **Side-by-side compare** old-vs-new on 3 representative outputs (already in the variant folders):
   - `dstack-hangout-alex-shaw-lsdan-andrew.txt` — small / 1-chunk / discussion
   - `tee-dstack-easytee-phala-transcript.txt` — medium / 4-chunk / technical
   - `project-intros-agents-day-3-transcript-may-21.txt` — large / 5-chunk / project intros
4. **Pass/fail signals** (qualitative, all on the 3 above):
   - Signal `kind` distribution diversifies — not every signal is `insight`. Concrete target: at least 2 distinct kinds per session.
   - `Entity.type=technology` is populated for TDX / SGX / RATLS / similar tech terms.
   - `Entity.cohort_status` is populated for every Person entity.
   - No `<NAME>` placeholder, no invented entities like `Tita` or `near credits`.
   - No `Flashbots`/`Flash Bots` (or other same-name-different-spacing) duplicate pairs in entities.
   - `Signal.source_quote` is populated and anchors to actual transcript text.
   - `Signal.said_by` vs `Signal.about_person` are visibly distinct on attribution-shifted signals — the `tee-dstack-easytee-phala` "Hang said it but it's about Alex+Kevin" case in particular.
   - `Derived.topics` is populated with 2-6 sensible topic tags.
5. **Dashboard visual check.** Re-run `transcripts.cli serve` and confirm the dashboard renders the new fields cleanly — cohort_status as chips, topics as tags, source_quote inline next to signals, said_by + about_person as distinct attribution lines.
6. **Walk through with the cohort organizer.** Show the 3 reference transcripts (v1 alongside the prior variants) and confirm the schema additions look right on real cohort content.
7. **Regression net.** `CONCLAVE_DISABLE_SCHEDULER=1 .venv/bin/python -m pytest -q --ignore=external --ignore=tests/test_interview_reflection_mcp.py` stays green. In particular:
   - The (now updated) `tests/test_transcript_pipeline.py` 7 legacy tests still pass — the `speakers` → `said_by` rename propagates through them as part of v1.
   - `tests/test_api_transcripts.py` raw-leak guard still passes — `raw_diarization` remains the only field stripped; `source_quote` is intentionally served.

If all checks pass: v1 ships. The qwen-7B baseline run can be re-done in a follow-up to validate that v1 also lifts the lighter local model — useful for the model-agnostic claim but not gating.

### 9. What's deliberately OUT of v1

Reaffirms anti-scope from §L plus this round's specific deferrals:

- **sqlite-vec, FTS5 retrieval, graph tables** — Phase 2. v1 doesn't add a single SQL table.
- **Cross-meeting entity dedup, entity canonicalization across sessions** — Phase 2. v1 dedups WITHIN a session only.
- **Real connector for `team_context.xml`.** v1 mocks the file. The future connector (cohort-OS export → XML) is a separate feature on the Connector roadmap (`BUILD_PLAN.md §6`).
- **Real connector for meeting attendance.** `SessionMetadata.participants` is reserved in the schema but stays `None` in v1. The future Google Meet / Zoom / Matrix / calendar connector lives on the same connector roadmap and will populate it. Until then, listeners-by-default fall back to `members` (transcript-derived speakers only — an undercount when audience members didn't speak).
- **The future evidence-store separation.** Forward-declared, NOT built in v1:
  - **Shape:** raw-transcript references (and possibly `source_quote` if the privacy posture changes) move out of `Signal` (inline today) into a separate store, linked by unique ID. Probably a new `signal_evidence(signal_id, source_quote, raw_segment_ids[], retained_until)` table once we get there.
  - **Time-bound retention:** evidence rows carry a `retained_until` timestamp; a sweeper expires them on a configurable window.
  - **Migration plan, not a v1 design driver:** v1 schemas stay tight and inline.
- **Per-meeting-type variation in `team_context.xml`.** v1 uses ONE XML for the team across all meeting types (project-intros, workshops, 1-on-1s, hangouts). Split only if quality differs sharply by type after §8 verification.
- **Multi-pass extraction.** Deferred per §2.5.
- **Auto-promotion of frequently-seen new entities into the XML.** Hand-maintained for v1. Auto-promotion risks teaching the model its own past mistakes; defer until there's a clean eval loop.

### 10. Test impact

The schema changes (§3), prompt-version bump (§7), and identity/dedup tightening (§5–§6) propagate into the existing test suite. The implementation is gated on the full suite staying green per step (same anti-domino rule as C1–C11). This section is the checklist.

**Audit result:** 3 existing test files require updates, 1 file extended, 1 new file added, 7 files untouched. The C10 raw-leak guard (`test_api_transcripts.py`) extends to assert `source_quote` IS served and only `raw_diarization` is stripped.

| Test file | Status | What changes | Why |
|---|---|---|---|
| `tests/test_transcript_pipeline.py` | **modify** | (a) `"speakers"` → `"said_by"` in FakeLLM signal responses (lines ~155–157); (b) literal `"v1"` → `ENRICH_PROMPT_VERSION` constant in 4 places (lines ~214, 222, 241, 253) so the bump to `"v2"` doesn't break the legacy 7 tests; (c) new default-field assertions on `SessionMetadata.participants` (None), `Derived.topics` (None until populated), `Entity.cohort_status` (defaults), `Entity.affiliation` (None), `Signal.about_person` ([]) | speakers rename, prompt-version bump, new optional fields' defaults |
| `tests/test_enrich_mapreduce.py` | **modify** | (a) `"speakers"` → `"said_by"` in FakeLLM signal responses in 6 places (lines ~117, 173, 179, 212, 248, 249); (b) `_dedup_signals` test (line ~246) extended for `said_by`/`about_person` carry-through; (c) `_dedup_entities` test extended to verify cohort_status precedence (`member > external > unknown`) and the new strip-spaces/punct normalisation (e.g. "Flashbots" / "Flash Bots" → single merged entity); (d) `ENRICH_PROMPT_VERSION` constant continues to drive backfill assertions — no string-literal updates needed | speakers rename + dedup tests need new field structure + tightened normalisation |
| `tests/test_api_transcripts.py` | **modify + extend** | (a) `Signal(... speakers=...)` constructor → `Signal(... said_by=...)` (line ~62); (b) literal `"v1"` → `ENRICH_PROMPT_VERSION` constant (line ~57); (c) extend `card_shape_has_expected_fields` to include the new keys (`topics`, `cohort_status` chips, `affiliation`, `participants`); (d) **extend raw-leak guard:** add explicit assertions that `source_quote` IS present in responses (the privacy posture deliberately serves it; only `raw_diarization` is stripped) and that the new `participants` and `topics` fields flow through | Schema rename + new fields surface + raw-leak guard scope clarified |
| `tests/test_identity.py` | **extend** | No changes for the speakers rename (this file references `metadata.resolved_speakers`, not `Signal.speakers`). NEW tests added: (a) parenthetical → affiliation hint extraction (`"Alex (flashbots?)"` → `affiliation="flashbots"` when base name doesn't match roster); (b) `cohort_status` post-process — Person entities matching `MOCK_DIRECTORY` get `member`, non-matching get `external` (with affiliation if available), ambiguous get `unknown`; (c) speaker-label ↔ Person-entity linkage populating `said_by` on signals where applicable | new identity-layer behaviours (§5) |
| `tests/test_team_context.py` | **new file** | Tests: (a) XML loader round-trips example → priming string; (b) missing file → graceful empty fallback + warning log (`MOCK_DIRECTORY` posture); (c) malformed XML → empty fallback, no crash; (d) `team_context_version` SHA-256 prefix stamping is deterministic and changes when XML body changes | new module (§2.2) |
| `tests/test_sources.py` | untouched | References speaker labels on `RawSegment`, not `Signal.speakers` | — |
| `tests/test_chunk.py` | untouched | Operates on `RawSegment` only | — |
| `tests/test_llm.py` | untouched | Provider-error mapping is orthogonal to schema | — |
| `tests/test_eval.py` | untouched **in v1** | Deterministic metric math operates on `Derived`. The fields it scores against (`signals[].text`, `entities[].name`) keep their semantics. Golden-set YAMLs are still future work — when they land, that's a separate test pass. | v1 punts formal eval; metric code unchanged |
| `tests/test_ingest.py` | untouched | Ingest path doesn't touch `Signal` schema — only `RawSegment`s + `SessionMetadata.resolved_speakers` | — |
| `tests/test_dashboard_smoke.py` | untouched (automated); **manual check** at V8 | Smoke hits static-mount + API shape; the actual signal/entity rendering with new fields is visually verified in the V8 dashboard check | mechanical asset-load still passes; visual rendering covered by the §8 verification |

**Net test counts.**
- Existing modifications: 3 files (`test_transcript_pipeline.py`, `test_enrich_mapreduce.py`, `test_api_transcripts.py`)
- Existing extensions: 1 file (`test_identity.py`)
- New: 1 file (`test_team_context.py`)
- Untouched: 6 files

**Sequencing — which step touches which tests.**

| Step | Production code | Tests touched |
|---|---|---|
| V1 (models.py) | `transcripts/models.py` | `test_transcript_pipeline.py` (defaults), `test_enrich_mapreduce.py` (kept compiling), `test_api_transcripts.py` (constructor + literal "v1") |
| V2 (team_context.py) | NEW `transcripts/team_context.py` + example XML + config wiring | NEW `test_team_context.py` |
| V3 (prompts.py) | `transcripts/prompts.py` + version bump | the `ENRICH_PROMPT_VERSION` constant references in `test_enrich_mapreduce.py` & `test_api_transcripts.py` auto-pick up the bump |
| V4 (enrich.py) | `transcripts/enrich.py` `_to_derived` + `_reduce` + `_dedup_*` | `test_enrich_mapreduce.py` (FakeLLM payload schema + dedup), `test_transcript_pipeline.py` (FakeLLM payload schema) |
| V5 (identity.py) | `transcripts/identity.py` | `test_identity.py` extensions |
| V6 (cli + api + dashboard) | `transcripts/cli.py`, `api/transcripts_routes.py`, `web/app.js` | `test_api_transcripts.py` (card/view shape + raw-leak guard extension) |

**Anti-domino rule.** Each Vn commits with its tests in the same change. Suite stays green at every commit. If V1's `Signal.speakers → said_by` rename breaks the FakeLLM payload tests, those tests are updated *in the same commit* — not deferred to V4.

**One gotcha.** The DB already has 12 sessions stored with the old `"speakers"` JSON shape on signals. When V3 lands the prompt-version bump, `enrich_pending` will treat all 12 as stale and re-enrich them under v2 — at which point the new `said_by` shape gets written. There's no read-side migration needed: `Signal(**data)` will ignore unknown JSON keys (Pydantic default), and the old `"speakers"` keys on the existing rows just go unused after re-enrichment. If someone wants to inspect the pre-v1 rows before re-enrichment, they keep the old shape until re-enriched. Documented behaviour, not a migration task.
