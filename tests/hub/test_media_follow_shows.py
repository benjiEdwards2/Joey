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
from tests.hub.helpers import not_season_state  # WP-T1
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
        assert db.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 5
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
        # WP-E1 (2026-10-16): the episode ratings' TMDB season read is the response's BackgroundTask - after the
        # render, but TestClient runs it before get() returns, so it is the one Jellyseerr call allowed here.
        # WP-T1 (2026-10-19): likewise the season-state words' one Sonarr series-list read.
        assert not [c for c in both.calls if c.startswith(SEERR) and "/season/" not in c] and not_season_state(son.calls) == []
        go.set()
    assert 'action="/media/follow/show/100/unfollow"' in page and "Following ✓ · future seasons" in page


# ---- the 6-hourly check: followed shows ----

def test_check_puts_a_followed_show_sonarr_added_later_and_leaves_a_set_one(son_env, monkeypatch):
    client, both, son, _ = son_env()
    monkeypatch.delenv("JELLYSEERR_URL")                     # shows need Sonarr only
    with client:
        media_follow.follow("show", 100, "Quiet Show")
        got = media_follow.run_once()
        assert got["shows_set"] == 1 and got["skipped_no_keys"]
        assert son.of("GET") == [("GET", f"{SONARR}/api/v3/series", None, None)]          # one list read a run
        assert [c[3] for c in son.of("PUT")] == [{**son.series[0], "monitored": True, "monitorNewItems": "all"}]
        son.series[0].update(monitored=True, monitorNewItems="all")
        son.calls.clear()
        assert media_follow.run_once()["shows_set"] == 0
    assert son.of("PUT") == [] and son.of("DELETE") == [] and not both.seerr.posts


# ---- creators: "Created by" on a show page, the person page, the check ----

CREATOR = {"id": 77, "name": "Cass Creator", "knownForDepartment": "Writing", "profilePath": "/cass.jpg"}


def tv(i, name, when=SOON, job="Creator", **extra):
    return {"id": i, "mediaType": "tv", "name": name, "firstAirDate": when, "posterPath": f"/s{i}.jpg", "job": job, **extra}


CREDITS = {"cast": [], "crew": [
    tv(501, "New Show"),
    tv(502, "Old Show", when=PAST),
    tv(503, "Have It", job="Director", mediaInfo={"status": 5}),
    tv(504, "Produced Show", job="Executive Producer"),
    tv(505, "Written Show", job="Writer"),
    tv(506, "Undated Show", when=""),
    {"id": 507, "mediaType": "movie", "title": "Directed Film", "releaseDate": SOON, "job": "Director"},
]}


def seed_creator(both, credits=CREDITS):
    both.seerr.table["/api/v1/person/77"] = CREATOR
    both.seerr.table["/api/v1/person/77/combined_credits"] = credits
    both.seerr.table["/api/v1/tv/100"] = {**both.seerr.table["/api/v1/tv/100"],
                                          "createdBy": [{"id": 77, "name": "Cass Creator", "profilePath": "/cass.jpg"},
                                                        {"name": "No Id Writer"}]}


def test_created_by_row_follows_a_creator_as_a_tv_maker(son_env):
    client, both, son, _ = son_env()
    seed_creator(both)
    with client:
        page = whole(client, "/media/title/tv/100")
        row = page.split('<div class="microlabel">Created by</div>', 1)[1].split('<div class="makers', 1)[0]
        assert ('<form method="post" hx-swap="innerHTML show:none" action="/media/follow/person/77"><input type="hidden" name="back" '
                'value="/media/title/tv/100"><input type="hidden" name="name" value="Cass Creator">'
                '<input type="hidden" name="tv" value="1"><button class="btn btn-ghost btn-sm" type="submit">'
                'Follow Cass Creator</button></form>') in row
        assert '<a class="makercard" href="/media/person/77">' in row          # the card itself stays the person link
        assert "Follow No Id Writer" not in row                               # no TMDB id, nothing to follow
        r = client.post("/media/follow/person/77", data={"back": "/media/title/tv/100", "tv": "1"}, follow_redirects=False)
        assert r.headers["location"] == "/media/title/tv/100?follow=creator"
        son.calls.clear()
        page = whole(client, "/media/title/tv/100?follow=creator")
    assert "Following Cass Creator ✓" in page and "Follow Cass Creator</button>" not in page
    assert "Following — their new films and shows are requested automatically" in page
    assert son.calls == []
    f = media_follow.get("person", 77)
    assert f["dept"] == "creator" and media_follow.kind_word(f) == "Creator · films + shows"
    assert {(j["mediaType"], j["mediaId"]) for j in seerr_posts(both)} == {("tv", 501), ("tv", 504), ("movie", 507)}


def test_film_directed_by_row_has_no_follow_buttons(son_env):
    client, both, son, _ = son_env()
    with client:
        page = whole(client, "/media/title/movie/603")
    assert '<div class="microlabel">Directed by</div>' in page and "/media/follow/person/" not in page


def test_person_page_follows_a_tv_maker_with_shows(son_env):
    client, both, son, _ = son_env()
    seed_creator(both)
    with client:
        b = main_of(client.get("/media/person/77").text)
        assert '<input type="hidden" name="tv" value="1">' in b
        assert '<button class="btn btn-secondary btn-sm" type="submit">Follow</button>' in b
        client.post("/media/follow/person/77", data={"back": "/media/person/77", "name": "Cass Creator", "tv": "1"})
        b = main_of(client.get("/media/person/77?follow=creator").text)
    assert "Following ✓ · films + shows" in b and 'action="/media/follow/person/77/unfollow"' in b
    assert "their new films and shows are requested automatically" in b and 'name="tv"' not in b


def test_person_page_film_only_person_has_no_tv_field(son_env):
    client, both, son, _ = son_env()
    seed_creator(both, {"cast": [], "crew": [{"id": 507, "mediaType": "movie", "title": "F", "releaseDate": SOON,
                                              "job": "Director"}, tv(508, "Written", job="Writer")]})
    with client:
        b = main_of(client.get("/media/person/77").text)
    assert 'name="tv"' not in b and ">Follow</button>" in b


def test_check_requests_a_new_show_once_and_skips_old_seen_and_on_server(son_env, monkeypatch):
    hook = "https://discord.invalid/api/webhooks/1/secret-token"
    monkeypatch.setenv("MEDIA_DISCORD_WEBHOOK", hook)
    client, both, son, _ = son_env()
    seed_creator(both)
    with client:
        media_follow.follow("person", 77, "Cass Creator", dept="creator")
        first = media_follow.run_once()
        again = media_follow.run_once()
    assert seerr_posts(both) == [{"mediaType": "tv", "mediaId": 501, "seasons": "all"},       # same date: by id
                                 {"mediaType": "tv", "mediaId": 504, "seasons": "all"},
                                 {"mediaType": "movie", "mediaId": 507}]
    # 502 aired already; 503 is on the server (Available); 505 a writer credit; 506 has no date
    assert first["requested"] == 3 and first["already"] == 1 and again["requested"] == 0
    adds = {(a["media"], a["tmdb_id"]): a for a in media_follow.recent_adds(50)}
    assert adds[("tv", 501)]["reason"] == "creator" and adds[("tv", 504)]["reason"] == "executive producer"
    assert adds[("tv", 503)]["outcome"] == "already" and ("tv", 502) not in adds and ("tv", 505) not in adds
    msgs = sorted(j["content"] for u, j in both.seerr.posts if u == hook)
    assert f"Joey Media: added show New Show ({SOON[:4]}) — creator · following Cass Creator" in msgs
    assert son.calls == []


def test_executive_producer_alone_is_not_a_creator_and_others_ignore_tv():
    ep_only = {"crew": [tv(1, "EP Show", job="Executive Producer")]}
    assert media_follow.person_shows(ep_only) == [] and not media_follow.tv_maker(ep_only)
    assert media_follow.person_titles(CREDITS) == media_follow.person_films(CREDITS)            # not a TV-maker follow
    both_jobs = {"crew": [tv(9, "S", job="Executive Producer"), tv(9, "S", job="Creator")]}
    assert [r["reason"] for r in media_follow.person_shows(both_jobs)] == ["creator"]         # strongest reason, once


# ---- the Following tab ----

def test_following_tab_groups_shows_and_counts_films_and_shows(son_env):
    client, both, son, _ = son_env()
    seed_creator(both)
    with client:
        media_follow.follow("person", 77, "Cass Creator", dept="creator")
        media_follow.run_once()
        media_follow.follow("person", 55, "Ada Actor", dept="Acting")
        follow_show(client)
        son.calls.clear()
        b = main_of(client.get("/media/following").text)
        people, shows = b.split("Shows · future seasons · 1", 1)
        assert "Following · 2" in people and "Cass Creator" in people and "Creator · films + shows" in people
        assert "1 film · 3 shows" in people and "0 added" in people and "Quiet Show" not in people   # 503: already
        shows = shows.split("Recently added by follows", 1)[0]
        assert '<a class="rowlink" href="/media/title/tv/100">' in shows and "Quiet Show" in shows
        assert "qs.jpg" in shows                                                      # the show poster
        assert ('<form method="post" hx-swap="innerHTML show:none" action="/media/follow/show/100/unfollow"><input type="hidden" name="back" '
                'value="/media/following"><button class="btn btn-ghost btn-sm" type="submit">Unfollow</button></form>') in shows
        recent = b.split("Recently added by follows", 1)[1]
        assert '<a class="row" href="/media/title/tv/501">' in recent and '<a class="row" href="/media/title/movie/507">' in recent
        r = client.post("/media/follow/show/100/unfollow", data={"back": "/media/following"}, follow_redirects=False)
        assert r.headers["location"] == "/media/following?follow=off&sonarr=stopped"
        b = main_of(client.get(r.headers["location"]).text)
    assert "Unfollowed" in b and "Sonarr: new seasons are no longer added · what you have stays" in b
    assert "Shows · future seasons" not in b and son.of("DELETE") == []
    assert son.of("GET") == [("GET", f"{SONARR}/api/v3/series", None, None)]   # the unfollow's lookup; no read on render


def test_following_tab_shows_only(son_env):
    client, both, son, _ = son_env()
    media_follow.follow("show", 100, "Quiet Show")
    with client:
        b = main_of(client.get("/media/following").text)
    assert "Shows · future seasons · 1" in b and "Following · " not in b and "from their page" not in b
    assert son.calls == []


def test_contract_and_readme_document_follow_shows():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    contract = (root / "docs" / "connector-contract.md").read_text(encoding="utf-8")
    twelfth = contract.split("**Twelfth exception", 1)[1].split("**Thirteenth exception", 1)[0]
    for word in ('monitorNewItems: "all"', 'monitorNewItems: "none"', '"seasons": "all"', "Creator", "Executive Producer",
                 "/media/follow/show/{tmdb}", "nothing is ever DELETEd"):
        assert word in twelfth, word
    readme = (root / "hub" / "README.md").read_text(encoding="utf-8")
    assert "Follow shows + show creators (F5" in readme and "follow_show(request, film)" in readme
