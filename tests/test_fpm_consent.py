"""P4 Phase 2 (Conclave) — FPM consent client cache (C4 read-side, ~60s TTL)."""
import infra.fpm_consent as fc


def test_consent_cache_serves_within_ttl(monkeypatch):
    fc._cache.clear()
    calls = []
    monkeypatch.setattr(fc, "_http_resolve",
                        lambda ws, vids: (calls.append(list(vids))
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
                        lambda ws, vids: (calls.append(list(vids))
                                          or {v: {"name": v, "owner_email": None,
                                                  "visibility": "named"} for v in vids}))
    fc.consent_resolve_batch_sync("ws", ["vp1"])
    fc.consent_resolve_batch_sync("ws", ["vp1", "vp2"])  # only vp2 is uncached
    assert calls == [["vp1"], ["vp2"]]
