"""M-42 (W2 media, 2026-10-09): the Media in-memory caches are bounded LRUs (the disk meta cache is the long tier),
and TTLs still apply on read."""
import time

from hub import media_cache, media_discover as md, media_files, media_item, media_omdb
from hub.media_cache import LRU


def test_lru_evicts_the_least_recently_used():
    c = LRU(3)
    for k in "abc":
        c[k] = k
    assert c.get("a") == "a"          # a read refreshes "a"
    c["d"] = "d"
    assert list(c) == ["c", "a", "d"] and "b" not in c
    c["c"] = "C"                      # a write refreshes too
    c["e"] = "e"
    assert set(c) == {"c", "d", "e"} and c["c"] == "C"
    assert c.pop("zz", None) is None and c.get("zz", 1) == 1
    c.clear()
    assert c == {} and len(c) == 0


def test_every_media_cache_is_bounded():
    for cache in (md._cache, media_item._cache, media_files._cache, media_omdb._mem):
        assert isinstance(cache, LRU) and cache.maxsize == media_cache.MAX_ENTRIES


def test_meta_get_disk_hits_never_grow_memory_past_the_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("META_CACHE_DIR", str(tmp_path / "meta"))
    monkeypatch.setenv("JELLYSEERR_URL", "http://seerr.invalid")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "k")
    md.clear_cache()
    n = media_cache.MAX_ENTRIES + 40
    now = time.time()
    for i in range(n):
        md._meta_store(f"/api/v1/movie/{i}", now, {"id": i})
    monkeypatch.setattr(md, "_fetch", lambda path: (_ for _ in ()).throw(AssertionError("no upstream call")))
    try:
        assert [md.meta_get(f"/api/v1/movie/{i}")["id"] for i in range(n)] == list(range(n))   # all off disk
        assert len(md._cache) == media_cache.MAX_ENTRIES
        assert "meta:/api/v1/movie/0" not in md._cache and f"meta:/api/v1/movie/{n - 1}" in md._cache
    finally:
        md.clear_cache()


def test_ttl_still_applies_to_a_cached_entry(monkeypatch):
    md.clear_cache()
    calls = []
    monkeypatch.setenv("JELLYSEERR_URL", "http://seerr.invalid")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "k")
    monkeypatch.setattr(md, "_meta_disk", lambda path: None)
    monkeypatch.setattr(md, "_meta_store", lambda *a: None)
    monkeypatch.setattr(md, "_fetch", lambda path: (calls.append(path) or {"n": len(calls)}, 200))
    try:
        assert md.meta_get("/api/v1/person/1")["n"] == 1
        assert md.meta_get("/api/v1/person/1")["n"] == 1             # fresh: from memory
        at, body = md._cache["meta:/api/v1/person/1"]
        md._cache["meta:/api/v1/person/1"] = (at - md.META_TTL - 1, body)
        assert md.meta_get("/api/v1/person/1")["n"] == 2             # expired: read again
    finally:
        md.clear_cache()
