"""P4 Phase 2 (Conclave) — FPM consent client cache (C4 read-side, ~60s TTL)."""
import infra.fpm_consent as fc


def test_consent_cache_serves_within_ttl(monkeypatch):
    fc._cache.clear()
    calls = []
    monkeypatch.setattr(fc, "_http_resolve",
                        lambda ws, vids, host_user=None: (calls.append(list(vids))
                                          or {v: {"name": "N", "owner_email": None,
                                                  "visibility": "named"} for v in vids}))
    a = fc.consent_resolve_batch_sync("ws", ["vp1"])
    b = fc.consent_resolve_batch_sync("ws", ["vp1"])
    assert a == b
    assert len(calls) == 1  # second call served from cache, no second HTTP hit


def test_consent_cache_only_fetches_missing(monkeypatch):
    fc._cache.clear()
    calls = []
    monkeypatch.setattr(fc, "_http_resolve",
                        lambda ws, vids, host_user=None: (calls.append(list(vids))
                                          or {v: {"name": v, "owner_email": None,
                                                  "visibility": "named"} for v in vids}))
    fc.consent_resolve_batch_sync("ws", ["vp1"])
    fc.consent_resolve_batch_sync("ws", ["vp1", "vp2"])  # only vp2 is uncached
    assert calls == [["vp1"], ["vp2"]]


def test_cache_is_host_scoped(monkeypatch):
    # Task #2: the same voiceprint can resolve differently per host (adder-only overlay), so
    # the read cache is keyed on host_user — a different host must trigger a fresh fetch.
    fc._cache.clear()
    calls = []
    monkeypatch.setattr(fc, "_http_resolve",
                        lambda ws, vids, host_user=None: (calls.append(host_user)
                                          or {v: {"name": "N"} for v in vids}))
    fc.consent_resolve_batch_sync("ws", ["vp1"], host_user="tina@x.com")
    fc.consent_resolve_batch_sync("ws", ["vp1"], host_user="tina@x.com")  # cached
    fc.consent_resolve_batch_sync("ws", ["vp1"], host_user="bob@x.com")   # different host → fetch
    assert calls == ["tina@x.com", "bob@x.com"]


def test_workspace_host_email_resolves_owner(monkeypatch):
    # Task #2: host = the workspace owner's email; a lookup miss → None (back-compat floor).
    from infra import identity, workspaces
    monkeypatch.setattr(workspaces, "get_workspace", lambda ws: {"created_by": "u1"} if ws == "ws1" else None)
    monkeypatch.setattr(identity, "get_user", lambda uid: {"email": "owner@x.com"} if uid == "u1" else None)
    assert fc.workspace_host_email("ws1") == "owner@x.com"
    assert fc.workspace_host_email("missing") is None
    assert fc.workspace_host_email(None) is None
