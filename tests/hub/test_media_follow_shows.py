"""F5 follow shows + show creators (2026-10-12). A show is followed from its page: Sonarr keeps it monitored with new
seasons (`monitored: true, monitorNewItems: "all"`; requested "all seasons + future" through Jellyseerr first when Sonarr
doesn't have it); unfollow sets `monitorNewItems: "none"` and never deletes. A person followed as a TV maker (dept
"creator") also gets their NEW shows requested by the 6-hourly check. Jellyfin / Jellyseerr / Discord are the film-page
fakes; Sonarr is faked here at requests.get / put / post. No network, no real sleeps."""
import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pytest
import requests

from hub import media_arr_search, media_follow, media_store
from tests.hub.conftest import main_of
from tests.hub.film_page import whole
from tests.hub.helpers import env, FakeResponse as R, SEERR_URL as SEERR, SKEY  # noqa: F401

SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr-key"
TODAY = date.today()
PAST = (TODAY - timedelta(days=400)).isoformat()
SOON = (TODAY + timedelta(days=90)).isoformat()
ORIGIN_BAD = {"Origin": "https://evil.invalid"}


# ---- schema step 3 ----

OLD_FOLLOWS = """CREATE TABLE media_follows(
  id INTEGER PRIMARY KEY, kind TEXT CHECK(kind IN ('person','collection')), tmdb_id INTEGER, name TEXT,
  followed_at TEXT, poster TEXT, dept TEXT, link TEXT, UNIQUE(kind, tmdb_id))"""
OLD_ADDS = """CREATE TABLE media_follow_adds(
  follow_id INTEGER, tmdb_id INTEGER, title TEXT, release_date TEXT, reason TEXT, outcome TEXT, note TEXT,
  at TEXT, poster TEXT, PRIMARY KEY(follow_id, tmdb_id))"""


def test_step_three_rebuilds_the_follow_tables_and_keeps_rows(tmp_path, monkeypatch):
    path = tmp_path / "media.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(path))
    with closing(media_store.connect()) as db:      # a current file, then put the follow tables back to their 2026-10-07 shape
        db.execute("DROP TABLE media_follows")
        db.execute("DROP TABLE media_follow_adds")
        db.execute(OLD_FOLLOWS)
        db.execute(OLD_ADDS)
        db.execute("INSERT INTO media_follows VALUES(1,'person',55,'Ada','2026-10-07',NULL,'Acting',NULL)")
        db.execute("INSERT INTO media_follow_adds VALUES(1,603,'Harbour','2027-01-01','top-5 cast','requested',NULL,'x',NULL)")
        db.execute("PRAGMA user_version = 2")
        db.commit()
    media_store.forget()
    assert media_follow.get("person", 55)["name"] == "Ada"                              # the first open migrates
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 3
        assert db.execute("SELECT media, tmdb_id, outcome FROM media_follow_adds").fetchall() == [("movie", 603, "requested")]
    media_follow.follow("show", 603, "Same Number Show")                                # 'show' now passes the CHECK
    assert {f["kind"] for f in media_follow.follows()} == {"person", "show"}
    with closing(media_store.connect()) as db:                                           # a film and a show with one number
        media_follow._record(db, 1, {"media": "tv", "tmdb_id": 603, "title": "Show", "date": SOON, "reason": "creator",
                                     "poster": None}, "requested", None)
        assert db.execute("SELECT COUNT(*) FROM media_follow_adds").fetchone()[0] == 2
        media_follow.migrate_shows(db)                                                   # idempotent
        assert db.execute("SELECT COUNT(*) FROM media_follow_adds").fetchone()[0] == 2


# ---- Sonarr fake ----

class Sonarr:
    def __init__(self):
        self.series = [{"id": 31, "tmdbId": 100, "tvdbId": 7100, "title": "Quiet Show", "monitored": False,
                        "monitorNewItems": "none", "path": "/tv/Quiet Show", "qualityProfileId": 4,
                        "seasons": [{"seasonNumber": 1, "monitored": True}]}]
        self.appear_after = 0          # reads that come back empty first (not added yet)
        self.calls, self.put_status = [], 202

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert headers == {"X-Api-Key": TKEY}
        self.calls.append(("GET", url, params, None))
        if self.appear_after:
            self.appear_after -= 1
            return R([])
        return R(self.series)

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        assert headers == {"X-Api-Key": TKEY}
        self.calls.append(("PUT", url, None, json))
        return R(json, self.put_status)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        assert headers == {"X-Api-Key": TKEY}
        self.calls.append(("POST", url, None, json))
        return R({"id": 1}, 201)

    def delete(self, url, *a, **k):
        self.calls.append(("DELETE", url, None, None))
        raise AssertionError("Follow never deletes")

    def of(self, method):
        return [c for c in self.calls if c[0] == method]


@pytest.fixture()
def son_env(env, monkeypatch):
    monkeypatch.setenv("SONARR_URL", SONARR)
    monkeypatch.setenv("SONARR_API_KEY", TKEY)
    sleeps = []
    monkeypatch.setattr(media_arr_search.time, "sleep", lambda s: sleeps.append(s))

    def build():
        client, both = env()
        son = Sonarr()
        get, post = requests.get, requests.post
        mine = lambda url: str(url).startswith(SONARR)
        monkeypatch.setattr(requests, "get", lambda url, *a, **k: son.get(url, *a, **k) if mine(url) else get(url, *a, **k))
        monkeypatch.setattr(requests, "post", lambda url, *a, **k: son.post(url, *a, **k) if mine(url) else post(url, *a, **k))
        monkeypatch.setattr(requests, "put", son.put)
        monkeypatch.setattr(requests, "delete", son.delete)
        return client, both, son, sleeps
    return build


def seerr_posts(both):
    return [j for u, j in both.seerr.posts if u.startswith(SEERR)]


def follow_show(client, back="/media/title/tv/100"):
    return client.post("/media/follow/show/100", data={"back": back, "name": "Quiet Show"}, follow_redirects=False)


# ---- Follow show / Unfollow show ----

def test_follow_show_in_sonarr_puts_monitored_and_all_new_seasons(son_env):
    client, both, son, sleeps = son_env()
    with client:
        r = follow_show(client)
    assert r.status_code == 303 and r.headers["location"] == "/media/title/tv/100?follow=show&sonarr=set"
    assert son.of("PUT") == [("PUT", f"{SONARR}/api/v3/series/31", None,
                              {**son.series[0], "monitored": True, "monitorNewItems": "all"})]   # every other field kept
    assert son.of("POST") == [] and seerr_posts(both) == [] and sleeps == []                  # no search, no request
    f = media_follow.get("show", 100)
    assert f["name"] == "Quiet Show" and f["poster"] == "tmdb:/qs.jpg" and f["link"] == "/media/title/tv/100"


def test_follow_show_not_in_sonarr_requests_all_seasons_plus_future(son_env):
    client, both, son, sleeps = son_env()
    son.appear_after = 2                       # find() misses it, follow_all's first read too, then Sonarr has it
    with client:
        r = follow_show(client, back="/media/item/ser1")
    assert r.headers["location"] == "/media/item/ser1?follow=show&sonarr=req-set"
    assert seerr_posts(both) == [{"mediaType": "tv", "mediaId": 100, "seasons": "all"}]
    assert [c[3] for c in son.of("PUT")] == [{**son.series[0], "monitored": True, "monitorNewItems": "all"}]
    assert [c[3] for c in son.of("POST")] == [{"name": "SeriesSearch", "seriesId": 31}]       # follow_all's search
    assert sleeps == [2.0] and media_follow.get("show", 100)["link"] == "/media/item/ser1"


def test_follow_show_is_recorded_when_jellyseerr_refuses_or_sonarr_is_unset(son_env, monkeypatch):
    client, both, son, _ = son_env()
    son.appear_after = 99
    both.seerr.post_status = 500
    with client:
        assert follow_show(client).headers["location"].endswith("follow=show&sonarr=reqfail")
        assert media_follow.get("show", 100) is not None
        media_follow.unfollow("show", 100)
        monkeypatch.delenv("SONARR_URL")
        n = len(son.calls)
        assert follow_show(client).headers["location"].endswith("follow=show&sonarr=unset")
    assert len(son.calls) == n and len(seerr_posts(both)) == 1 and media_follow.get("show", 100) is not None


def test_unfollow_show_sets_new_seasons_none_and_never_deletes(son_env):
    client, both, son, _ = son_env()
    son.series[0]["monitored"] = True
    with client:
        follow_show(client)
        son.calls.clear()
        r = client.post("/media/follow/show/100/unfollow", data={"back": "/media/title/tv/100"}, follow_redirects=False)
    assert r.headers["location"] == "/media/title/tv/100?follow=off&sonarr=stopped"
    assert son.of("PUT") == [("PUT", f"{SONARR}/api/v3/series/31", None, {**son.series[0], "monitorNewItems": "none"})]
    assert son.of("PUT")[0][3]["monitored"] is True                                          # monitored kept as is
    assert son.of("DELETE") == [] and son.of("POST") == [] and media_follow.get("show", 100) is None


def test_unfollow_show_not_in_sonarr_changes_nothing_there(son_env):
    client, both, son, _ = son_env()
    son.series = []
    media_follow.follow("show", 100, "Quiet Show")
    with client:
        r = client.post("/media/follow/show/100/unfollow", data={}, follow_redirects=False)
    assert r.headers["location"] == "/media/following?follow=off&sonarr=missing"
    assert son.of("PUT") == [] and son.of("DELETE") == []


def test_show_follow_routes_require_same_origin(son_env):
    client, both, son, _ = son_env()
    with client:
        assert client.post("/media/follow/show/100", headers=ORIGIN_BAD).status_code == 403
        assert client.post("/media/follow/show/100/unfollow", headers=ORIGIN_BAD).status_code == 403
    assert son.calls == [] and media_follow.follows() == []


# ---- the show page line ----

def test_show_page_line_reads_media_db_only(son_env):
    client, both, son, _ = son_env()
    with client:
        page = whole(client, "/media/title/tv/100")
        assert 'action="/media/follow/show/100"' in page and ">Follow show</button>" in page
        assert '<input type="hidden" name="back" value="/media/title/tv/100">' in page
        follow_show(client)
        son.calls.clear()
        page = whole(client, "/media/title/tv/100?follow=show&sonarr=req-notyet")
    assert 'action="/media/follow/show/100/unfollow"' in page and "Following ✓ · future seasons" in page
    assert "Following — new seasons are added automatically" in page
    assert ('<p class="metaline st-warn" role="status">Requested every season · Sonarr hasn&#39;t added it yet — '
            'new seasons are not set to follow</p>') in page
    assert son.calls == []                                                   # no Sonarr call on render
    assert SKEY not in page and TKEY not in page


def test_film_pages_have_no_follow_show(son_env):
    client, both, son, _ = son_env()
    with client:
        assert "/media/follow/show/" not in whole(client, "/media/title/movie/603")


def test_cold_show_page_draws_the_line_before_any_upstream_call(son_env, monkeypatch):
    import threading
    from hub import media_film
    client, both, son, _ = son_env()
    media_follow.follow("show", 100, "Quiet Show")
    go, real = threading.Event(), media_film._load_extras
    monkeypatch.setattr(media_film, "_load_extras", lambda *a: go.wait(5) and real(*a))
    with client:
        page = client.get("/media/item/ser1").text
        assert not [c for c in both.calls if c.startswith(SEERR)] and son.calls == []
        go.set()
    assert 'action="/media/follow/show/100/unfollow"' in page and "Following ✓ · future seasons" in page
