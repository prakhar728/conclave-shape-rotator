"""Unit tests for infra/shape_contrib (Task #20, Arm 1).

Pure + dependency-injected: the HTTP `post` is a fake, so nothing here touches the
real Shape OS Supabase. Covers body rendering, 200 000-char chunking, the RLS-shaped
payload, status classification, and the contribute_raw success/failure/dry-run paths.
"""
from __future__ import annotations

import json

from infra import shape_contrib as sc


class FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


def _fake_post(status=201, sink=None):
    def post(endpoint, headers=None, content=None, timeout=None):
        if sink is not None:
            sink.append({"endpoint": endpoint, "headers": headers, "payload": json.loads(content)})
        return FakeResp(status)
    return post


# --- transcript_body ---------------------------------------------------------

def test_transcript_body_renders_speaker_lines():
    segs = [{"speaker": "Alice", "text": "hello"}, {"speaker": "Bob", "text": "hi there"}]
    assert sc.transcript_body(segs) == "[Alice] hello\n[Bob] hi there"


def test_transcript_body_skips_empty_and_defaults_speaker():
    segs = [{"speaker": "", "text": "lonely"}, {"speaker": "Bob", "text": "  "}]
    assert sc.transcript_body(segs) == "[Speaker] lonely"


# --- chunk_body --------------------------------------------------------------

def test_chunk_body_single_when_small():
    assert sc.chunk_body("a\nb\nc") == ["a\nb\nc"]


def test_chunk_body_splits_on_line_boundaries_under_limit():
    body = "\n".join(["x" * 40 for _ in range(10)])  # 10 lines of 40 + 9 newlines
    chunks = sc.chunk_body(body, limit=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    # Reassembling by newline round-trips the content (no lines lost/duplicated).
    assert "\n".join("\n".join(chunks).split("\n")) == body


def test_chunk_body_hard_splits_oversized_single_line():
    body = "y" * 250
    chunks = sc.chunk_body(body, limit=100)
    assert [len(c) for c in chunks] == [100, 100, 50]
    assert "".join(chunks) == body


def test_chunk_body_empty():
    assert sc.chunk_body("") == []


# --- build_payload (RLS shape) -----------------------------------------------

def test_build_payload_forces_rls_fields():
    p = sc.build_payload(body="hi", title="T", metadata={"conclave_session_id": "s1"})
    assert p["org_id"] == "srfg"
    assert p["processing_status"] == "pending"
    assert p["source_kind"] == "transcript"
    assert p["body"] == "hi"
    assert p["metadata"]["char_count"] == 2
    assert p["metadata"]["submitted_via"] == "conclave"
    assert p["metadata"]["conclave_session_id"] == "s1"
    assert "id" not in p and "submitted_at" not in p  # server/RLS-owned


def test_build_payload_caps_title_at_300():
    p = sc.build_payload(body="x", title="t" * 500, metadata={})
    assert len(p["title"]) == 300


def test_build_payload_omits_title_when_none():
    p = sc.build_payload(body="x", title=None, metadata={})
    assert "title" not in p


# --- _classify ---------------------------------------------------------------

def test_classify():
    assert sc._classify(201) == "ok"
    assert sc._classify(204) == "ok"
    assert sc._classify(401) == "forbidden"
    assert sc._classify(403) == "forbidden"
    assert sc._classify(422) == "rejected"
    assert sc._classify(400) == "rejected"
    assert sc._classify(500) == "network"


# --- contribute_raw ----------------------------------------------------------

SEGS = [{"speaker": "Alice", "text": "hello"}, {"speaker": "Bob", "text": "world"}]


def test_contribute_raw_happy_path_posts_once():
    sink = []
    res = sc.contribute_raw(
        segments=SEGS, title="T", metadata={"conclave_session_id": "s1"},
        url="https://x.supabase.co", anon_key="anon", post=_fake_post(201, sink),
    )
    assert res.ok and res.status == "ok" and res.parts == 1
    assert res.http_statuses == [201]
    # Mirrors context-submit.mjs headers exactly.
    h = sink[0]["headers"]
    assert h["apikey"] == "anon" and h["authorization"] == "Bearer anon"
    assert h["prefer"] == "return=minimal"
    assert sink[0]["endpoint"].endswith("/rest/v1/context_submissions")


def test_contribute_raw_dry_run_never_posts():
    sink = []
    res = sc.contribute_raw(
        segments=SEGS, title="T", metadata={}, url="https://x.supabase.co",
        anon_key="anon", dry_run=True, post=_fake_post(201, sink),
    )
    assert res.ok and res.status == "dry_run" and res.parts == 1
    assert sink == []  # the safety valve: no network call


def test_contribute_raw_unconfigured_when_no_key():
    res = sc.contribute_raw(
        segments=SEGS, title="T", metadata={}, url="", anon_key="", post=_fake_post(201),
    )
    assert not res.ok and res.status == "unconfigured"


def test_contribute_raw_empty_transcript_rejected():
    res = sc.contribute_raw(
        segments=[{"speaker": "A", "text": "  "}], title="T", metadata={},
        url="https://x.supabase.co", anon_key="anon", post=_fake_post(201),
    )
    assert not res.ok and res.status == "rejected"


def test_contribute_raw_forbidden_on_401():
    res = sc.contribute_raw(
        segments=SEGS, title="T", metadata={}, url="https://x.supabase.co",
        anon_key="anon", post=_fake_post(401),
    )
    assert not res.ok and res.status == "forbidden"


def test_contribute_raw_network_on_transport_error():
    def boom(*a, **k):
        raise RuntimeError("dns")
    res = sc.contribute_raw(
        segments=SEGS, title="T", metadata={}, url="https://x.supabase.co",
        anon_key="anon", post=boom,
    )
    assert not res.ok and res.status == "network"


def test_contribute_raw_multipart_labels_parts(monkeypatch):
    # The real cap is 200k; stub chunk_body to force two parts and assert each
    # insert carries a part-labelled title + part/parts metadata.
    monkeypatch.setattr(sc, "chunk_body", lambda body, **k: ["AAAA", "BBBB"])
    sink = []
    res = sc.contribute_raw(
        segments=SEGS, title="Sess", metadata={"k": "v"},
        url="https://x.supabase.co", anon_key="anon", post=_fake_post(201, sink),
    )
    assert res.ok and res.parts == 2 and res.http_statuses == [201, 201]
    titles = [c["payload"]["title"] for c in sink]
    assert titles == ["Sess (part 1/2)", "Sess (part 2/2)"]
    assert [c["payload"]["metadata"]["part"] for c in sink] == [1, 2]
    assert all(c["payload"]["metadata"]["parts"] == 2 for c in sink)


def test_contribute_raw_stops_at_first_failure(monkeypatch):
    monkeypatch.setattr(sc, "chunk_body", lambda body, **k: ["AAAA", "BBBB"])
    calls = {"n": 0}

    def flaky_post(endpoint, headers=None, content=None, timeout=None):
        calls["n"] += 1
        return FakeResp(201 if calls["n"] == 1 else 422)

    res = sc.contribute_raw(
        segments=SEGS, title="Sess", metadata={}, url="https://x.supabase.co",
        anon_key="anon", post=flaky_post,
    )
    assert not res.ok and res.status == "rejected"
    assert calls["n"] == 2  # stopped after the failing second insert
