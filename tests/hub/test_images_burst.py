"""E1 (2026-10-13): /img never stalls pages. The route is async; a cache hit is served at once; a MISS waits on the
event loop (no thread held) for one of MISS_SLOTS upstream slots and fetches in a worker of its own limiter; a miss
that waited MISS_WAIT_S for a slot gets the fallback card (FALLBACK_CACHE). requests.get is faked — no network."""
import asyncio
import threading
import time

import pytest
import requests
from fastapi.testclient import TestClient

from hub import images
from hub.main import app

JF_URL, JF_KEY = "http://jelly.example.invalid:8096", "JFSECRETkey"
JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"


class Resp:
    status_code, headers, content = 200, {"content-type": "image/jpeg"}, JPEG


class SlowUpstream:
    """Each poster read blocks until `release` is set (bounded); counts reads in flight and the most seen at once."""

    def __init__(self):
        self.release, self.lock = threading.Event(), threading.Lock()
        self.now = self.peak = self.calls = 0
        self.fast = True
        self.open = set()   # url fragments let through before `release`

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        with self.lock:
            self.calls += 1
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            end = time.monotonic() + 10
            while not (self.fast or self.release.is_set() or any(k in url for k in self.open)) and time.monotonic() < end:
                time.sleep(0.005)
            return Resp()
        finally:
            with self.lock:
                self.now -= 1


@pytest.fixture()
def slow(tmp_path, monkeypatch):
    monkeypatch.setenv("IMG_CACHE_DIR", str(tmp_path / "img"))
    monkeypatch.setenv("JELLYFIN_URL", JF_URL)
    monkeypatch.setenv("JELLYFIN_API_KEY", JF_KEY)
    up = SlowUpstream()
    monkeypatch.setattr(requests, "get", up.get)
    yield up
    up.release.set()


def wait_for(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_the_route_is_async():
    route = next(r for r in images.router.routes if r.path.startswith("/img/"))
    assert route.endpoint is images.image and asyncio.iscoroutinefunction(images.image)
    assert images.MISS_SLOTS == 6 and images.MISS_WAIT_S == 8


def test_twenty_slow_misses_never_delay_a_cached_hit_or_a_page(slow):
    with TestClient(app) as client:   # one event loop for every request, as under uvicorn
        assert client.get("/img/jf:cachedhit?h=240").content == JPEG      # stored while the upstream is fast
        slow.fast = False
        out = {}

        def miss(i):
            out[i] = client.get(f"/img/jf:slow{i}?h=240")
        threads = [threading.Thread(target=miss, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        assert wait_for(lambda: slow.now == images.MISS_SLOTS)            # six reads stuck upstream, 14 queued
        started = time.perf_counter()
        hit = client.get("/img/jf:cachedhit?h=240")
        hit_s = time.perf_counter() - started
        started = time.perf_counter()
        page = client.get("/healthz")
        page_s = time.perf_counter() - started
        assert slow.now == images.MISS_SLOTS                               # still stuck: the hit didn't wait for them
        slow.release.set()
        for t in threads:
            t.join(15)
    assert hit.status_code == 200 and hit.content == JPEG and hit.headers["cache-control"] == images.HIT_CACHE
    assert hit_s < 1.0, hit_s
    assert page.status_code == 200 and page_s < 1.0, page_s
    assert slow.peak == images.MISS_SLOTS                                  # never more than six upstream at once
    assert len(out) == 20 and all(r.status_code == 200 and r.content == JPEG for r in out.values())


def test_a_miss_that_waits_too_long_for_a_slot_gets_the_fallback_card(slow, monkeypatch, caplog):
    monkeypatch.setattr(images, "MISS_WAIT_S", 0.3)
    with TestClient(app) as client:
        slow.fast = False
        busy = [threading.Thread(target=client.get, args=(f"/img/jf:busy{i}?h=240",)) for i in range(images.MISS_SLOTS)]
        for t in busy:
            t.start()
        assert wait_for(lambda: slow.now == images.MISS_SLOTS)
        started = time.perf_counter()
        r = client.get("/img/jf:late?h=240&t=Late Show")
        waited = time.perf_counter() - started
        slow.release.set()
        for t in busy:
            t.join(15)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["cache-control"] == images.FALLBACK_CACHE and b">LA<" in r.content
    assert 0.25 <= waited < 3, waited
    assert slow.calls == images.MISS_SLOTS                                 # the late one never reached the upstream
    assert "image upstream busy (jf)" in caplog.text and JF_KEY not in caplog.text and "jelly.example" not in caplog.text


def test_a_queued_miss_finds_the_poster_a_request_ahead_of_it_stored(slow):
    with TestClient(app) as client:
        slow.fast = False
        first = [threading.Thread(target=client.get, args=(f"/img/jf:ref{i}?h=240",)) for i in range(images.MISS_SLOTS)]
        for t in first:
            t.start()
        assert wait_for(lambda: slow.now == images.MISS_SLOTS)      # every slot taken
        queued = [threading.Thread(target=client.get, args=("/img/jf:ref0?h=240",)) for _ in range(2)]
        for t in queued:
            t.start()
        time.sleep(0.2)                                              # both are waiting for a slot
        slow.open.add("/ref0/")                                      # ref0 lands first and frees one slot
        for t in [first[0]] + queued:
            t.join(15)
        slow.release.set()
        for t in first:
            t.join(15)
    assert slow.calls == images.MISS_SLOTS        # the two that queued behind re-checked the cache and read no upstream
