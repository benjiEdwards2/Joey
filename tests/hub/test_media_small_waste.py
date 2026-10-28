"""E1 (2026-10-13), the smaller waste: /media/library builds its library index once per request; a Diary visit syncs
Jellyfin history only when the jellyfin snapshot moved and keeps its stats while nothing changed; the lifespan
pre-compiles every template and pre-parses the snapshots; the Search now lookup is kept 5 minutes (and dropped by
Joey's own writes); outbound calls ride one keep-alive Session per upstream. No network."""
import importlib
from pathlib import Path

import pytest
import requests
from requests.adapters import BaseAdapter
from fastapi.testclient import TestClient

from hub import (images, media_db, media_discover as md, media_jellyfin, media_library, media_omdb, media_pages,
                 media_requests, tasks, upstream)
from tests.hub.helpers import write_envelope
from tests.hub.test_media_discover_search_now import HX, RADARR, arr_env, env  # noqa: F401  (fixtures)
from tests.hub.test_media_rate import env as diary_env  # noqa: F401  (fixture)

HUB = Path(__file__).resolve().parents[2] / "hub"


# ---- /media/library: one index per request ----

def test_link_arrivals_with_a_prebuilt_index_matches_building_it(monkeypatch):
    items = [{"jf_id": "a", "item_key": "tmdb:1", "title": "The Quiet Coast", "year": 2020},
             {"jf_id": "b", "item_key": "tvdb:9", "title": "Slow Horses", "year": 2022}]
    rows = [{"item_key": "tmdb:1", "title": "x"}, {"item_key": "tvdb:7", "title": "Slow Horses · S01E02"},
            {"item_key": "tmdb:5", "title": "Nope"}]
    href = lambda jf: f"/media/item/{jf}"   # noqa: E731
    want = media_library.link_arrivals(rows, items, "tv", href)
    assert media_library.link_arrivals(rows, None, "tv", href, media_library.library_index(items)) == want
    assert [r["href"] for r in want] == ["/media/item/a", "/media/item/b", "/media/title/tv/5"]


def test_the_library_page_builds_each_index_once(diary_env, monkeypatch):
    build, _ = diary_env
    built = []
    real = media_library.library_index
    monkeypatch.setattr(media_library, "library_index", lambda items: built.append(1) or real(items))
    with build() as client:
        assert client.get("/media/library").status_code == 200
    assert len(built) == 2   # movie + tv, once each for the whole page - never one per row (8+ here before E1)


# ---- /media/diary: sync only on a new snapshot, stats kept ----

def test_a_diary_visit_syncs_only_when_the_snapshot_moved(diary_env, monkeypatch):
    build, _ = diary_env
    syncs, stats = [], []
    real_sync, real_stats = media_db.sync_diary_from_history, media_db.diary_stats
    monkeypatch.setattr(media_db, "sync_diary_from_history", lambda *a, **k: syncs.append(1) or real_sync(*a, **k))
    monkeypatch.setattr(media_db, "diary_stats", lambda *a, **k: stats.append(1) or real_stats(*a, **k))
    with build() as client:
        first = client.get("/media/diary").text
        second = client.get("/media/diary").text
        assert len(syncs) == 1 and len(stats) == 1                       # same snapshot, same diary: no write, no scan
        media_db.add_manual_watch("tmdb:77", "movie", "Logged By Hand")   # a new row: the stats are worked out again
        third = client.get("/media/diary").text
        assert len(syncs) == 1 and len(stats) == 2 and "Logged By Hand" in third
    assert first.split("<main", 1)[1] == second.split("<main", 1)[1]
    with build() as client:                                              # a new sweep: synced again
        client.get("/media/diary")
    assert len(syncs) == 2


# ---- lifespan pre-warm ----

def test_the_lifespan_precompiles_every_template_and_parses_the_snapshots(tmp_path, monkeypatch):
    write_envelope(tmp_path / "snaps", "weather", age_minutes=1)
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.delenv("AREAS_PATH", raising=False)
    import hub.main
    importlib.reload(hub.main)
    env_ = hub.main.templates.env
    env_.cache.clear()
    with TestClient(hub.main.app):
        names = env_.list_templates()
        assert len(names) > 50
        cached = {key[1] for key in env_.cache.keys()}
        assert set(names) <= cached
    out = tasks.prewarm()
    assert out["templates"] == len(names) and out["template_errors"] == 0 and out["snapshots"] == 1


# ---- Search now: the lookup kept 5 minutes ----

def test_the_search_now_lookup_is_kept_five_minutes_and_dropped_by_a_write(arr_env, monkeypatch):
    client, both, arr = arr_env()

    def lookups():
        return [c for c in arr.calls if c[0] == "GET"]
    with client:
        for _ in range(3):
            assert "Search now</button>" in client.get("/media/title/movie/603/arr", headers=HX).text
        assert len(lookups()) == 1 and media_requests.LOOKUP_TTL == 300
        real = media_requests.time.monotonic
        monkeypatch.setattr(media_requests.time, "monotonic", lambda: real() + 301)
        client.get("/media/title/movie/603/arr", headers=HX)
        assert len(lookups()) == 2
        media_requests.forget_lookups()            # what every Joey write to Radarr / Sonarr / Seerr does
        client.get("/media/title/movie/603/arr", headers=HX)
    assert len(lookups()) == 3


def test_a_failed_lookup_is_not_kept(arr_env):
    client, both, arr = arr_env()
    arr.raise_get = requests.ConnectionError
    with client:
        assert client.get("/media/title/movie/603/arr", headers=HX).text == ""
        arr.raise_get = None
        assert "Search now</button>" in client.get("/media/title/movie/603/arr", headers=HX).text


def test_joeys_writes_drop_the_kept_lookups(monkeypatch):
    src = {m: (HUB / f"{m}.py").read_text(encoding="utf-8") for m in ("media_requests", "media_arr_search",
                                                                       "media_follow", "media_discover")}
    assert src["media_requests"].index("forget_lookups()\n        resp = upstream.session(\"arr\").put(") > 0
    assert "mr.forget_lookups()\n        _ok(upstream.session(\"arr\").put(" in src["media_arr_search"]
    assert "mr.forget_lookups()   # E1" in src["media_follow"]
    assert "media_requests.forget_lookups()" in src["media_discover"]


# ---- keep-alive Sessions ----

# JY-237: the real factory, taken when this file is imported (collection, before any fixture patches it). The old
# fixture hunted for it through sys.modules (the conftest copy whose REAL_UPSTREAM was filled) and raised StopIteration
# as a setup error whenever that copy was not the one found. Three conftest.py files share the module name "conftest".
REAL_SESSION = upstream.session


@pytest.fixture()
def real_sessions(monkeypatch):
    monkeypatch.setattr(upstream, "session", REAL_SESSION)
    upstream.close_all()
    yield
    upstream.close_all()


def test_one_kept_session_per_upstream(real_sessions):
    s = upstream.session("jellyfin")
    assert isinstance(s, requests.Session) and upstream.session("jellyfin") is s
    assert upstream.session("seerr") is not s
    assert s.get_adapter("http://x.invalid").poolmanager.connection_pool_kw["maxsize"] == upstream.POOL
    with pytest.raises(ValueError):
        upstream.session("anything")


def test_a_session_keeps_no_cookies(real_sessions):
    class SetCookie(BaseAdapter):
        def send(self, request, **kw):
            r = requests.Response()
            r.status_code, r.url, r.request = 200, request.url, request
            r.headers["Set-Cookie"] = "sid=abc; Path=/"
            r._content = b"{}"
            return r

        def close(self):
            pass
    s = upstream.session("seerr")
    s.mount("http://cookie.invalid", SetCookie())
    s.get("http://cookie.invalid/api")
    assert len(s.cookies) == 0


def test_each_media_upstream_goes_through_its_session(monkeypatch):
    used = []

    class Rec:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, method):
            def call(url, *a, **k):
                used.append((self.name, method))
                raise requests.ConnectionError("offline")
            return call
    monkeypatch.setattr(upstream, "session", lambda name: Rec(name))
    for k, v in (("JELLYSEERR_URL", "http://s.invalid"), ("JELLYSEERR_API_KEY", "k"), ("OMDB_API_KEY", "k"),
                 ("JELLYFIN_URL", "http://j.invalid"), ("JELLYFIN_API_KEY", "k"),
                 ("RADARR_URL", "http://r.invalid"), ("RADARR_API_KEY", "k")):
        monkeypatch.setenv(k, v)
    md._fetch("/api/v1/movie/1")
    with pytest.raises(requests.ConnectionError):
        media_jellyfin.get("http://j.invalid", {}, "/Users")
    with pytest.raises(requests.ConnectionError):
        media_requests._find("radarr", "http://r.invalid", {}, 1, None)
    media_omdb.metascore("tt0133093")
    for ref in ("jf:a1", "radarr:5", "tmdb:/p.jpg"):
        kind, ident = ref.split(":", 1)
        images._fetch(kind, ident, 240)
    assert used == [("seerr", "get"), ("jellyfin", "get"), ("arr", "get"), ("omdb", "get"),
                    ("jellyfin", "get"), ("arr", "get"), ("tmdb", "get")]
