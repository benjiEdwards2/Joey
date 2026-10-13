"""E1 (2026-10-13): link prefetches yield to real taps, server side. A prefetch's background read (X-Joey-Prefetch)
runs in its own 1-worker lane, at most one more waits there (later ones are skipped), and a tap on a title whose
prefetch is still waiting takes the read over in the page lane — so a tap never queues behind speculation.
The background read (`_load_extras`) is faked; no network."""
import threading
import time

import pytest

from hub import media_film
from tests.hub.helpers import env  # noqa: F401  (env fixture)


@pytest.fixture()
def gated(monkeypatch):
    """_load_extras that blocks on a per-title gate; records which thread lane ran each title."""
    gates, ran, lock, all_open = {}, [], threading.Lock(), threading.Event()

    def load(kind, tmdb, imdb_hint):
        with lock:
            ran.append((tmdb, threading.current_thread().name.split("_")[0]))
        g, end = gates.setdefault(tmdb, threading.Event()), time.monotonic() + 10
        while not (g.is_set() or all_open.is_set()) and time.monotonic() < end:
            time.sleep(0.005)
        return {"tmdb": tmdb}

    def gate(tmdb):
        return gates.setdefault(tmdb, threading.Event())
    monkeypatch.setattr(media_film, "_load_extras", load)
    yield gate, ran
    all_open.set()
    media_film.drain_extras()


def wait_until(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not cond():
        time.sleep(0.005)
    return cond()


def test_a_tap_never_waits_behind_prefetches(gated):
    gate, ran = gated
    a = media_film.warm_extras("movie", 1, prefetch=True)           # running in the prefetch lane
    assert wait_until(lambda: (1, "film-prefetch") in ran)
    b = media_film.warm_extras("movie", 2, prefetch=True)           # waiting behind it
    assert media_film.warm_extras("movie", 3, prefetch=True) is None   # a second waiter is skipped, not queued
    assert getattr(a, "joey_prefetch", False) and getattr(b, "joey_prefetch", False)
    gate(9).set()
    tap = media_film.warm_extras("movie", 9)                         # a real page's read
    assert tap.result(timeout=2) == {"tmdb": 9}                      # done while both prefetches are still held
    assert (9, "film-extras") in ran and not a.done() and not b.done()


def test_a_tap_takes_over_its_titles_waiting_prefetch(gated):
    gate, ran = gated
    media_film.warm_extras("movie", 1, prefetch=True)
    assert wait_until(lambda: (1, "film-prefetch") in ran)
    queued = media_film.warm_extras("movie", 2, prefetch=True)
    gate(2).set()
    tap = media_film.warm_extras("movie", 2)
    assert queued.cancelled() and tap is not queued
    assert tap.result(timeout=2) == {"tmdb": 2} and (2, "film-extras") in ran
    assert media_film._prefetch_waiting[0] == 0
    assert media_film.warm_extras("movie", 3, prefetch=True) is not None   # the lane's waiting slot is free again


def test_a_tap_joins_its_titles_running_prefetch(gated):
    gate, ran = gated
    running = media_film.warm_extras("movie", 5, prefetch=True)
    assert wait_until(lambda: (5, "film-prefetch") in ran)
    assert media_film.warm_extras("movie", 5) is running            # already reading: the tap waits for that read
    gate(5).set()
    assert running.result(timeout=2) == {"tmdb": 5} and ran.count((5, "film-prefetch")) == 1


def test_prefetch_requests_use_the_prefetch_lane(env, monkeypatch):
    client, both = env()
    lanes = []
    real = media_film.warm_extras

    def spy(kind, tmdb, imdb_hint=None, *, prefetch=False):
        lanes.append(prefetch)
        return real(kind, tmdb, imdb_hint, prefetch=prefetch)
    monkeypatch.setattr(media_film, "warm_extras", spy)
    with client:
        r = client.get("/media/title/movie/603", headers={"X-Joey-Prefetch": "1"})
        assert r.status_code == 204 and lanes and all(lanes)
        media_film.drain_extras()
        lanes.clear()
        from hub import media_discover as md
        md.clear_cache()
        client.get("/media/title/movie/603")
    assert lanes and not any(lanes)
