# Part 1 — local testing runbook

How to run the transcript-refinement editor locally and exercise it end to end.
Run the servers in your own terminals so you can watch the logs.

## Verified-ready prerequisites
- **Canonical venv** `/Users/prakharojha/Desktop/me/personal/conclave/.venv` — has
  uvicorn + fastapi + spaCy + `en_core_web_sm` + wordfreq (the dev-only NLP deps;
  a bare pyenv/requirements env silently has no detection — see the warning below).
- **Default DB** migrated to head (`transcript_v2` table exists) — the app self-runs
  `init_db()` + `alembic upgrade head` on boot.
- Ports 8000/3001 free; the docker `conclave-api`/`recato-lite` stack NOT running
  (it owns 8000/3001 and serves an old image — `docker stop` them first if up).

## Commands — two terminals

**Terminal 1 — backend** (canonical venv + the two dev flags):
```bash
cd /Users/prakharojha/Desktop/me/personal/shape-rotator-all/conclave-transcript-refine
CONCLAVE_DEV_LOGIN=1 CONCLAVE_REFINE_DEBUG=1 \
  /Users/prakharojha/Desktop/me/personal/conclave/.venv/bin/uvicorn main:app --reload
```
`--reload` so you see request logs live. Expect NO "Loading weights …" — the eval
skill's MiniLM is gated off at startup (`CONCLAVE_PREWARM_MODELS=1` to opt back in).

**Terminal 2 — frontend**:
```bash
cd /Users/prakharojha/Desktop/me/personal/shape-rotator-all/conclave-transcript-refine/frontend
npm run dev
```

## Env vars that must be set
- `CONCLAVE_DEV_LOGIN=1` → no-Supabase login bypass (`/auth/v1/dev-login`).
- `CONCLAVE_REFINE_DEBUG=1` → enables the `?debug=1` backend-state panel.
- Run uvicorn from the **canonical venv** (the NLP deps live there — not in a bare env).
- DB = default (already migrated + populated) — nothing to set.

> **Detection needs the dev-only NLP deps.** `spacy` + `en_core_web_sm` + `wordfreq`
> are deliberately not in `requirements.txt`. Without them the editor opens but shows
> **no word highlights, no `tag…` dropdowns, blank speaker suggestions** (detection
> falls back to nothing). That's the #1 local gotcha — use the canonical venv.

## Walk
1. Sign in (browser): `http://localhost:3001/api/auth/v1/dev-login?email=you@example.com&next=/dashboard`
2. **Upload a fresh Otter transcript** (`Speaker  M:SS` format) from the dashboard.
   In-person Record stays disabled locally (needs FPM + ASR URLs).
3. Open `http://localhost:3001/meeting/<session_id>/refine?debug=1`
4. Edit a word / tag a candidate / assign a speaker → watch the **Backend state (live)**
   panel reflect what persisted.

## Where you see v2 (not raw v1)
- **The `/refine` editor reads v2** — your corrected tokens + tagged entities.
- **The `?debug=1` panel** shows the persisted v2 (status, annotations, vocab).
- **Approve keeps you on `/refine`** showing the approved corrected v2 (it no longer
  bounces to the meeting page).
- ⚠️ The **meeting page `/meeting/<id>` still shows raw v1** — known gap
  (`transcript-refine-issues.md` #2). Judge persistence from `/refine` or the debug
  panel, not that page.

## Error display for words
Failed edit/tag/assign show a **"Couldn't save…" banner** + re-sync from the server
— no silent optimistic-only changes.

## Verifying persistence without the UI
```bash
python scripts/inspect_session.py <session_id>   # same env/DB as the backend
```
Dumps the v2 corrected segments, annotations, vocab, graduation stats, entity counts.
Walk the 11-case checklist in `transcript-refine-verify.md`.
