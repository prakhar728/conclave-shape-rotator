# DEMO TODO — Persistent Working Plan

> **Created:** 2026-05-29. Demo is tomorrow.
> **Purpose:** This file survives context compaction. After compact, the
> user will say "read DEMO_TODO.md and proceed." I read this end-to-end,
> re-orient, and continue from where we left off.
>
> **Do NOT touch any code until the user signs off on the next design
> item.** Plan-first, code-second is the explicit workflow they asked for
> after I jumped ahead on signal-section rendering.

---

## Snapshot at compact time

- **Branch:** `transcripts-phase1` (will eventually push to main)
- **Last committed:** `c48707f transcripts: revert premature dashboard signal-section render — design first per plan`
- **Pre-revert commit (in history):** `8930d2a` — the unauthorized change
- **Tests passing:** 283 of 283
- **Uncommitted in working tree:**
  - `web/index.html` — has the `?dev` live-reload script (waiting on user sign-off to commit)
  - `.gitignore` and `data/interview_reflection/leo.jsonl` — test scratch, leave alone
  - `DECISION_INPUTS.md`, `METHODOLOGY_SURVEY.md` — user-added, leave alone

## Dashboard runtime state

- Server running, daemonized with `nohup`, PID in `/tmp/dashboard.pid`
- Bound to `0.0.0.0:8000` (all interfaces)
- macOS firewall confirmed disabled (`State = 0`)
- URLs:
  - LAN: `http://192.168.200.15:8000/dashboard/`
  - LAN + live reload: `http://192.168.200.15:8000/dashboard/?dev`
- DB has 12 sessions at `enrich_prompt_version=v2.1`, `team_context_version=d5341145`
- Visual state: **the pre-jump v1.1 layout** (no section headers, no sub-grouping) — verified by reverting `web/app.js` and `web/styles.css` to `8930d2a~1`

## UNRESOLVED (per user instruction)

### WiFi cross-device reach
- Server is correctly bound; macOS side is fine
- Other devices likely can't connect due to WiFi **client isolation** (route `192.168.200.15` from this Mac goes through `lo0` — so my "self-tests" never actually proved external reach)
- **Fallback ready:** `ngrok http 8000` (ngrok already installed)
- **Status:** leaving as-is per user request. Do not spend more time diagnosing.

---

## TODO — design + implement (each blocked until user signs off on its design)

### A. Live reload via `?dev` query param — **CODE READY, AWAITING COMMIT**
- Added to `web/index.html` (lines after the existing `<script type="module" src="/dashboard/app.js"></script>`)
- Polls `Last-Modified` on `app.js`, `styles.css`, `index.html`, `tokens.css` every 800ms
- Reloads page when a watched file changes
- Verified: FastAPI's StaticFiles DOES set `Last-Modified`; the script is in the served HTML; smoke tests pass
- **Action when user resumes:** ask if dashboard at `?dev` is working as expected on their other Mac → if yes, commit as: `transcripts: dev — live-reload via ?dev query param`
- **No tests needed** (purely client-side dev convenience)

### B. Backend-driven signal section rendering
**Design decision LOCKED by user**: backend ordering. `to_view()` already exposes `signals_by_kind` (decisions / action_items / open_questions / impactful_points / insights, in that priority order). Client just renders.

**Visual design questions to resolve BEFORE touching `web/app.js`:**

1. **Single labeling axis** — pick one of:
   - (i) Section headers with counts (`DECISIONS (3)`) AND drop the per-item `[decision]` badge inside each signal item.
   - (ii) Flat sorted list, no section headers, KEEP per-item `[decision]` badges in color.
   - (iii) Section headers AND keep per-item badges (the bug user spotted in the screenshot — "INSIGHT header followed by 'insight' subheading"). **Avoid.**
   - Recommendation: (i). Section headers convey the kind once per group; per-item badge becomes redundant. Avoids the bug.

2. **Empty sections** — render an empty `OPEN QUESTIONS (0)` header, or skip the section entirely?
   - Recommendation: skip. Headers should mean "there are some." User can see counts in the card metadata otherwise.

3. **Where does the section rendering live in the file?** Add a `renderSignalSections(detail)` helper, replace the existing single `el("ul", { class: "signals" }, detail.signals.map(renderSignal))` line.

4. **CSS naming** — `.signal-section`, `.signal-section-head`. Section header inherits the kind color via class.

**Tests:** none break, none new. (Visual change only; smoke test still passes.)

### C. Card-preview + click-to-detail-page
**User goal:** card = mini preview with the most important signals immediately visible; click anywhere on the card → goes to a per-meeting detail page with everything in depth.

**Design questions:**

1. **URL scheme:**
   - (i) Hash-based SPA route: `/dashboard/#/sessions/<id>` — same `index.html`, JS routes on hashchange. No new backend.
   - (ii) Real route per session: `/dashboard/sessions/<id>` — needs FastAPI to serve `index.html` for that path too OR a different per-session HTML file.
   - (iii) `?session=<id>` query param.
   - Recommendation: **(i) hash-based SPA**. Cleanest for demo; no backend changes; back button works.

2. **"Most important signals" rule** for the card preview:
   - Decisions first, then action items, capped at total of 2-3 items.
   - If no decisions/action_items, fall back to first 1-2 impactful_points.
   - Topic chips always visible on the card.
   - Summary always visible (1-2 lines, truncate with `…` if longer).
   - Signal-count badges (`5 signals · 9 entities · 3 topics`).
   - Resolved-speaker chips.

3. **Detail page composition:**
   - Re-uses the existing `GET /transcripts/sessions/{id}` API (already returns everything via `to_view()`).
   - Shows all signals in section-ordered groups (per B above — same rendering helper, no duplication).
   - Shows all entities with cohort_status chips.
   - Shows all topics.
   - Shows resolved-speakers + participants (when populated, currently None).
   - Has a clear back-link or back button.

4. **Click affordance on cards:**
   - Whole card is clickable, cursor: pointer on hover, soft elevation.
   - Or: a "View detail →" link in a corner.
   - Recommendation: whole card clickable.

5. **Routing in `app.js`:**
   - On `hashchange`, check if hash matches `#/sessions/<id>`. If yes, render detail view. Else, render grid.
   - Initial load checks `location.hash` and dispatches.

**Tests:** none break; smoke test still passes (it only checks the shell + assets).

### D. Permissions (Phase-1.5 demo-hardcoded)
**User goal:** loginless "who are you?" picker on first visit; you see meetings you can view; personal action items dashboard for things you owe / are owed. Hardcoded for demo — real auth waits for Phase 1.5.

**Permission rule (PRECISELY):**

```
can_see(viewer: str | None, session: Session) -> bool:
    md = session.metadata
    # (1) Public-to-cohort sessions visible to everyone
    if md.visibility == "cohort":
        return True
    # (2) Otherwise (visibility == "owner-only"), check viewer identity
    if viewer is None:
        return False
    # (3) Owner can always see their own
    if md.owner and md.owner == viewer:
        return True
    # (4) Speakers can see meetings they spoke in
    speaker_record_ids = {
        meta.get("record_id") for meta in (md.resolved_speakers or {}).values()
        if isinstance(meta, dict) and meta.get("record_id")
    }
    return viewer in speaker_record_ids
```

**Backend changes (5 surgical):**

1. `api/transcripts_routes.py`:
   - `can_see()` — replace the stub with the logic above.
   - `_resolve_viewer(viewer: Optional[str])` — small helper returning the same viewer string (placeholder so future auth swap is one function).
   - Endpoints accept `?viewer=<record_id>` query param:
     - `GET /transcripts/sessions?viewer=X` — filters via `can_see`.
     - `GET /transcripts/sessions/{id}?viewer=X` — 403 if `can_see` fails.

2. New endpoint `POST /transcripts/sessions/{id}/visibility`:
   - Body: `{"visibility": "cohort" | "owner-only", "viewer": "<record_id>"}`
   - Auth check: `viewer == session.metadata.owner`. If not, 403.
   - Calls `store.set_visibility(session_id, visibility, owner)` (already exists).

3. New endpoint `GET /transcripts/me/action-items?viewer=<record_id>`:
   - Walks all sessions that `can_see(viewer, s)` returns True for.
   - For each session, filters `signals` where `kind == "action_item"` AND viewer is implicated.
   - "Implicated" = viewer's record_id maps to a speaker label (via reverse-lookup on resolved_speakers) that appears in `signal.said_by` OR `signal.about_person`.
   - Returns `[{session_id, session_date, signal: {...}}, ...]`.

4. Owner-stamping on ingest (opt-in, additive):
   - Add `--owner-from-first-speaker` flag to `transcripts.cli ingest`.
   - When set, `metadata.owner = first record_id present in metadata.resolved_speakers`.
   - **Opt-in keeps existing tests green** (`test_metadata_defaults_are_phase_1_friendly` still passes because default owner stays `None`).

5. No schema changes. Everything lives in the JSON metadata column.

**Tests:**

- **MUST UPDATE (intentional behavior change):**
  - `tests/test_api_transcripts.py::test_can_see_stub_returns_true_for_everyone`
    - Rewrite as `test_can_see_visibility_cohort_returns_true_for_everyone` (the new always-true case is the default visibility).

- **MUST ADD:**
  - `test_can_see_owner_only_blocks_anonymous_viewer`
  - `test_can_see_owner_only_allows_owner`
  - `test_can_see_owner_only_allows_speaker_via_resolved_speakers`
  - `test_can_see_owner_only_blocks_unrelated_viewer`
  - `test_list_sessions_filters_by_viewer_query_param`
  - `test_get_session_403s_when_viewer_cannot_see`
  - `test_visibility_endpoint_owner_only_succeeds_for_owner`
  - `test_visibility_endpoint_403s_for_non_owner`
  - `test_me_action_items_filters_signals_by_viewer_via_said_by`
  - `test_me_action_items_filters_signals_by_viewer_via_about_person`
  - `test_me_action_items_skips_invisible_sessions`
  - `test_ingest_owner_from_first_speaker_opt_in_stamps_owner`
  - `test_ingest_default_leaves_owner_none`

- **MUST NOT CHANGE:**
  - C10 raw-leak guard (`raw_diarization` still never served)
  - The existing card-shape contract tests (additive only)

**Frontend changes (described, not part of backend plan):**

- Identity picker overlay on first visit:
  - Dropdown of cohort members loaded from `MOCK_DIRECTORY`. Needs a `GET /transcripts/_cohort/roster` endpoint OR the picker reads from the existing `resolved_speakers` of all sessions and dedupes.
  - Selected identity stored in `localStorage` as `conclaveViewerId`.
- All API calls in `app.js` append `?viewer=<id>`.
- Card UI shows "Hide from cohort" / "Show to cohort" toggle when viewer is the owner.
- New `/dashboard/#/me/action-items` route showing the personal queue.

### E. Shape-UI isolation — **PLAN NOTE ONLY, NO CODE**
- The vendored `web/shape-ui/` carries Shape-Rotator-cohort-specific vocabulary.
- For the **product layer**, must be optional/replaceable.
- Existing plan §D.2 covers this; just expand the boundary statement.
- No code action for the demo.

### F. Cross-meeting relations — **PLAN NOTE ONLY**
- Phase 2c per `BUILD_PLAN.md §5`.
- Out of scope for the demo entirely.
- User wants a plan note in the implementation plan capturing how we'd build it (shared-entity co-occurrence first, embeddings later) without committing code.

### G. `model_id` provenance bug — **5-LINE FIX**
- `transcripts/enrich.py::_model_id()` falls back to `settings.default_model` (NearAI's deepseek) when `llm` arg is `None`, even when the actual backend is RedPill/Gemma.
- Fix: check `settings.llm_backend` first and return the backend-specific model id.
- Patch existing 12 DB rows: small Python script loading each session, setting `metadata.model_id`, saving via `store.set_metadata`.
- Demo-cosmetic. Do it only if user asks.

---

## Implementation plan doc — additions still to write

Current state of `transcripts/IMPLEMENTATION_PLAN.md` §D appendix:

| Section | Current state | What needs to happen |
|---|---|---|
| §D.1 demo permission layer | High-level | **EXPAND** with detailed rule + endpoint surface + test deltas (D above) |
| §D.2 shape-ui isolation | Stub | Slight expansion (E above) — boundary commitment clearer |
| §D.3 card preview/detail | Placeholder | **EXPAND** with design questions + recommended choices (C above) |
| §D.4 signal section ordering | Says "LANDED" (NOW WRONG — was reverted) | **REWRITE** to "design pending, recommendation = section headers only, drop per-item badges to avoid the labeling bug observed in v1.1 dashboard screenshot" |
| §D.5 LAN access / tunneling | Adequate | Add note that WiFi reach is unresolved; ngrok is the prepared fallback |
| §D.6 model_id provenance | Stub | Adequate — small explicit fix already described |
| §D.7 live reload (NEW) | — | **ADD** the `?dev` query param dev-only polling pattern, with caveat it's dev-only and not part of the demo URL |
| §D.8 cross-meeting relations (NEW) | — | **ADD** stub: out-of-scope for demo, planned for Phase 2c, "shared-entity co-occurrence first, embeddings later, no code" |

**These plan-doc rewrites should land in ONE commit titled:**
`transcripts: plan — expand §D demo iteration with detailed design + new §D.7/§D.8`

**Order of plan-doc rewrite work (so the plan tells the implementation order):**

1. Update §D.4 (status correction — small)
2. Add §D.7 live reload (small)
3. Add §D.8 cross-meeting stub (small)
4. Expand §D.2 shape-ui isolation (small)
5. Expand §D.3 card preview/detail design (medium)
6. **Expand §D.1 permissions plan in full (LARGE — load-bearing)**

Then commit. Then ask user which item to actually implement first.

---

## Resumption workflow after compact

When user says **"read DEMO_TODO.md and proceed"** (or similar):

1. **Read this file end-to-end first.** Do not improvise from compacted summary.
2. **Quick state check:**
   ```bash
   git status -s
   git log --oneline -3
   CONCLAVE_DISABLE_SCHEDULER=1 .venv/bin/python -m pytest -q --ignore=external --ignore=tests/test_interview_reflection_mcp.py | tail -1
   lsof -nP -iTCP:8000 -sTCP:LISTEN | head -2
   ```
3. **Report state to user:** tests passing, server up/down, what's uncommitted.
4. **Ask:** "Which TODO item do you want me to design first?"
5. **For each item:**
   - Surface design questions first (use the section in this doc).
   - Wait for sign-off.
   - Implement with tests in the same commit.
   - Keep suite green.
6. **Default sequence if user says "go in order":**
   1. Commit live-reload (A) — pre-approved if dashboard verified
   2. Rewrite plan §D additions (per the order above)
   3. Design + implement B (signal sections)
   4. Design + implement C (card preview + detail page)
   5. Design + implement D (permissions) — biggest piece
   6. Optionally G (model_id fix)
   7. E, F are plan notes only — already covered in plan-doc rewrites

## Discipline rules (do not violate)

- **Plan-first, code-second.** Never touch production code until design is signed off.
- **Tests in the same commit as the code that changes their contract.** No domino.
- **Suite stays green at every commit.** 283 passing is the floor.
- **No new dependencies without asking.**
- **No file moves / rewrites that weren't requested.**
- **WiFi diagnostic is closed.** Do not reopen unless user asks.
- **Real Phase-1.5 work supersedes the hardcoded permission demo.** Commit messages should tag this work as `(demo)` or `demo —` prefix.
- **`data/interview_reflection/leo.jsonl`** is not ours — never commit it.

## Files to know

- `transcripts/IMPLEMENTATION_PLAN.md` — has §D appendix (needs the rewrites above)
- `transcripts/BUILD_PLAN.md` — has Phase 1.5 + Phase 2c definitions to defer to
- `transcripts/team_context.example.xml` — version `d5341145`, 9 examples with lessons
- `web/app.js`, `web/styles.css`, `web/index.html` — frontend; index.html has the uncommitted live-reload script
- `api/transcripts_routes.py` — has `can_see` stub, `to_card`, `to_view` (with `signals_by_kind`)
- `transcripts/store.py` — `set_visibility(session_id, visibility, owner)` already exists
- `tests/test_api_transcripts.py` — where most permission tests will land
- `/tmp/dashboard.pid` — current server PID

---

End of plan. Resume here.

---

## Cleanup on completion (ephemeral)

**Delete this file (`transcripts/DEMO_TODO.md`) once the 9-commit plan in `IMPLEMENTATION_PLAN.md §D.10` ships** (F1, F2, P2, P3, P4, P5, F3, F4, F5 all landed and tests green). The implementation plan + BUILD_PLAN ticks become the durable record; this file is working memory only.

Do NOT carry any notes from this file into a memory unless they describe behavior the implementation plan misses. Default: this file disappears with the version.
