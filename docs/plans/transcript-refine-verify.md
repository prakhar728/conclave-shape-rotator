# Part 1 — manual verification checklist (does it actually work?)

A short, runnable list to confirm the front-end → back-end → Part-2-surface path
works end to end. **The "before/after" is the inspector:** run it before an action
and after, and diff.

```bash
# same venv + env (DB path) as the running backend
python scripts/inspect_session.py <session_id>
```

Each case maps to a backend test that ALREADY proves the persistence logic against a
real SQLite DB — so if the inspector shows the change, the round-trip works; if it
doesn't, the issue is the FE→BE wiring (the proxy/auth/owner), not the logic.

| # | Do this in the editor | Before → After (inspector field) | Already proven by |
|---|---|---|---|
| 1 | **Edit a word** (click → type → Enter) | `corrected transcript` line: that word changes; **all other words identical** | `V2-4` word_edit_writes_v2_not_raw · api `test_edit_token_owner` |
| 2 | (after #1) **unchanged words** | every other token is byte-for-byte the same → Part B reads the full corrected text, not a diff | `V2-8` reload_after_approve_preserves · `G-5` |
| 3 | **Tag an entity** (candidate/oov → pick a type) | `annotations` gains a row (`surface, state=known, type, source=user`) **and** `vocab` gains a row | `GT-1` tag_entity_writes_vocab_and_annotation · api `test_tag_entity_writes_vocab` |
| 4 | **Assign a speaker** (click label → chip) | that segment shows `speaker_name`; raw label still kept underneath | `V2-7` speaker_assignment_independent_of_raw · api `test_assign_speaker` |
| 5 | **Reload the page** (or re-run inspector) after #1/#3/#4 | the edit/tag/speaker is **still there** → it's persisted, not in-memory | `V2-8` · `V2-6` span_annotation_roundtrips |
| 6 | **Raw stays immutable** | the raw transcript is unchanged by any edit (Part 2 can always fall back) | `V2-5` raw_immutable_under_all_edits |
| 7 | **Approve & build** | status `draft → approved`; `entity graph` count grows; extraction ran over the **corrected** v2 | `G-5` test_index_session_chunks_corrected_text · `V2-2` |
| 8 | **Edit after approve** (try) | blocked (409) — approved drafts are frozen | api `test_edit_after_approve_conflicts` |
| 9 | **Make any edit** | `insights_stale = true`; the badge shows; **no LLM fired** per edit | `IN-2/3/6` |
| 10 | **Per-user isolation** | your tags land in *your* `vocab`, not another user's | `GT-6` tag_entity_is_per_user |
| 11 | **Owner-gating** | a non-owner gets 403 on any edit | api `test_non_owner_cannot_edit` |

## What "accessible to Part 2" concretely means
Part 2 reads three things, all populated by the actions above and pinned by
`tests/test_part2_contract.py`:
1. **the approved corrected v2** (`v2_segments_or_raw` → full text, changed + unchanged) — cases 1, 2, 7
2. **`transcript_v2.annotations[]`** (your confirmed entity labels = priors) — case 3
3. **`vocab`** (your personal dictionary) — case 3

If cases 1–11 pass in the browser, Part 2 has everything it needs and the contract
holds. Cases 1–11 are each backed by a green backend test; the browser run only
proves the live wire between them.
