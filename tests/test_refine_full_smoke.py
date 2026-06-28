"""Complete backend smoke — a realistic transcript through the WHOLE refine flow,
asserting the spec: OOV-only highlighting (novel terms tagged, well-known/common NOT),
edit/tag/assign/approve persistence, and duplicate-upload handling. Real spaCy
detection; LLM skipped (no tokens). Run with `-s` to read the printed analysis.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import identity
from transcripts import store

TRANSCRIPT = (
    "Prakhar  0:01\n"
    "We should ship Recato and the DStack protocol by Friday. "
    "I synced with Google about TDX.\n\n"
    "Alex  0:15\n"
    "Sounds good. The roadmap looks solid.\n"
)


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    import api.transcripts_routes as routes
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: True)  # no LLM → no tokens
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)


@pytest.fixture
def client(monkeypatch):
    import auth.routes as ar
    from infra import supabase_auth as sb
    for mod in (sb, ar):
        monkeypatch.setattr(mod, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def test_full_smoke(client, monkeypatch):
    import api.transcripts_routes as routes
    real_enrich = routes._enrich_in_background
    # Disarm the upload's fire-and-forget background task so the ingest is deterministic;
    # we run the REAL ingest synchronously below.
    monkeypatch.setattr(routes, "_enrich_in_background", lambda sid: None)

    client.post("/auth/v1/verify-otp", json={"email": "smoke@example.com", "token": "000000"})
    user = identity.upsert_user_by_supabase("sb-smoke@example.com", "smoke@example.com")
    ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]

    # --- 1) upload a realistic transcript over HTTP ---
    up = client.post(f"/api/workspaces/{ws}/transcripts",
                     json={"text": TRANSCRIPT, "filename": "smoke.txt", "intent": ""})
    assert up.status_code == 202, up.text
    sid = up.json()["session_id"]
    print(f"\n[1] uploaded → {sid}")

    # --- 2) run the real ingest (spaCy detection; enrich skipped) ---
    real_enrich(sid)
    v2 = client.get(f"/transcripts/sessions/{sid}/v2").json()
    anns = [(a["surface"], a["state"]) for a in v2["annotations"]]
    surfaces = {a["surface"] for a in v2["annotations"]}
    print(f"[2] speakers: {[s['speaker_label'] for s in v2['segments']]}")
    print(f"[2] DETECTED ({len(anns)}): {anns}")

    # --- 3) ASSERT the spec: truly-novel terms tagged oov; well-known/common NOT ---
    for novel in ("Recato", "DStack"):  # zipf==0 → flagged
        assert novel in surfaces, f"expected '{novel}' flagged"
    # Common, non-entity words stay UNflagged. (Friday = DATE, not in the #7 NER
    # type map → also unflagged.)
    for skip in ("roadmap", "protocol", "Friday", "Sounds", "good", "meeting"):
        assert skip not in surfaces, f"'{skip}' should NOT be flagged (common, non-entity)"
    # #7 NER pre-typing: well-known ENTITIES are now flagged WITH a type even though
    # they're not OOV (Google → affiliation, source=nlp). Novel OOV terms keep state=oov;
    # NER-only entities are state=candidate.
    assert "Google" in surfaces, "Google should be NER-flagged as an entity"
    google = next(a for a in v2["annotations"] if a["surface"] == "Google")
    assert google["type"] == "affiliation" and google["source"] == "nlp"
    assert all(state == "oov" for surf, state in anns if surf in ("Recato", "DStack"))
    print(f"[3✓] OOV (Recato/DStack) + NER-typed (Google→affiliation); common words NOT flagged")
    # Surfaced finding: pure OOV (zipf==0) is VERY conservative — rare tech acronyms
    # that DO appear in corpora are skipped (a tuning decision for the user).
    print(f"[3!] 'TDX' flagged? {'TDX' in surfaces}  (zipf=1.22 → pure-OOV skips it)")

    # --- 4) edit a word, tag an entity, assign a speaker ---
    seg0 = v2["segments"][0]
    d_idx = seg0["tokens"].index("DStack")
    r_idx = seg0["tokens"].index("Recato")
    assert client.post(f"/transcripts/sessions/{sid}/v2/edit-token",
                       json={"segment_id": 0, "token_idx": d_idx, "new_text": "Dstack"}).status_code == 200
    assert client.post(f"/transcripts/sessions/{sid}/v2/tag-entity",
                       json={"segment_id": 0, "token_start": r_idx, "token_end": r_idx + 1,
                             "surface": "Recato", "type": "project"}).status_code == 200
    assert client.post(f"/transcripts/sessions/{sid}/v2/assign-speaker",
                       json={"segment_id": 0, "name": "Prakhar Ojha"}).status_code == 200
    after = client.get(f"/transcripts/sessions/{sid}/v2").json()
    print(f"[4] edit DStack→{after['segments'][0]['tokens'][d_idx]} | "
          f"speaker={after['segments'][0]['speaker_name']} | "
          f"tags={[(a['surface'], a['type'], a['state'], a['source']) for a in after['annotations']]} | "
          f"stale={after['insights_stale']}")
    assert after["segments"][0]["tokens"][d_idx] == "Dstack"
    assert after["segments"][0]["speaker_name"] == "Prakhar Ojha"
    assert any(a["surface"] == "Recato" and a["type"] == "project"
               and a["state"] == "known" and a["source"] == "user" for a in after["annotations"])
    assert after["insights_stale"] is True

    # --- 5) approve → frozen + corrected ---
    assert client.post(f"/transcripts/sessions/{sid}/approve").status_code == 200
    final = client.get(f"/transcripts/sessions/{sid}/v2").json()
    assert final["status"] == "approved"
    # edit after approve re-opens to draft (Q3 — reverses V2-3 frozen contract)
    reopen_r = client.post(f"/transcripts/sessions/{sid}/v2/edit-token",
                           json={"segment_id": 0, "token_idx": 0, "new_text": "no"})
    assert reopen_r.status_code == 200
    assert client.get(f"/transcripts/sessions/{sid}/v2").json()["status"] == "draft"  # re-opened
    # re-approve to close the Q3 cycle (and so the duplicate check below sees approved)
    assert client.post(f"/transcripts/sessions/{sid}/approve").status_code == 200
    print(f"[5✓] post-approve edit → 200 re-opened to draft, then re-approved (Q3 cycle)")

    # --- 6) re-upload the SAME transcript → duplicate, not a fresh editor ---
    dup = client.post(f"/api/workspaces/{ws}/transcripts",
                      json={"text": TRANSCRIPT, "filename": "smoke.txt", "intent": ""})
    print(f"[6] re-upload → HTTP {dup.status_code} {dup.json()}")
    assert dup.status_code == 200
    body = dup.json()
    assert body["status"] == "duplicate" and body["session_id"] == sid
    assert body["v2_status"] == "approved"
    print(f"[6✓] dedup: same session, status=duplicate, v2_status=approved")

    # --- 7) raw transcript never mutated ---
    assert "Recato" in store.load_session(sid).raw_diarization[0].text
    print("[7✓] raw transcript immutable\n")
