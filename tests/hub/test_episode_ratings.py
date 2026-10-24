"""WP-E1 (2026-10-16): per-episode ratings for the TV episode flow (EPISODES_CONTRACT §2 `ratings`, §4 E1).

OMDb is faked at `requests.get` with recorded-shape answers (tests/hub/fixtures/omdb/*.json, no key in them); Jellyfin
and Jellyseerr reuse the film page fakes (tests/hub/helpers.py). No network. Time is frozen through the module's
`_now` / `_today`."""
import json
import logging
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from hub import media_discover, media_episode_ratings as er, media_film, media_omdb, media_store
from tests.hub.helpers import env, FakeResponse as R, ITEMS, SEERR_URL  # noqa: F401

FIX = Path(__file__).resolve().parent / "fixtures" / "omdb"
KEY = "omdbSECRETkey42"
SERIES = "tt9100001"
TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


class Omdb:
    """OMDb by params: a season read answers its season fixture (else not found), an episode read the votes fixture."""

    def __init__(self, seasons=None, status=200, exc=None, body=None):
        self.seasons = {4: fixture("season_s4"), 3: fixture("season_s3")} if seasons is None else seasons
        self.status, self.exc, self.body, self.calls = status, exc, body, []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert url == media_omdb.URL
        self.calls.append(dict(params or {}))
        if self.exc:
            raise self.exc
        if self.body is not None or self.status != 200:
            return R(self.body, self.status)
        if "Season" in params:
            return R(self.seasons.get(int(params["Season"]), fixture("not_found")))
        return R(fixture("episode_votes"))

    def season_calls(self):
        return [int(c["Season"]) for c in self.calls if "Season" in c]

    def vote_calls(self):   # an episode id; the series' own id without Season is the Metacritic pill's lookup
        return [c["i"] for c in self.calls if "Season" not in c and c["i"] != SERIES]

    def ep_calls(self):
        return self.season_calls() + self.vote_calls()


@pytest.fixture()
def frozen(monkeypatch):
    clock = {"now": NOW, "today": TODAY}
    monkeypatch.setattr(er, "_now", lambda: clock["now"])
    monkeypatch.setattr(er, "_today", lambda: clock["today"])
    return clock


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "media.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(path))
    monkeypatch.setenv("META_CACHE_DIR", str(tmp_path / "meta"))
    media_store.reset()
    media_store.forget()
    yield path
    media_store.reset()


@pytest.fixture()
def omdb(monkeypatch, db, frozen):
    monkeypatch.setenv("OMDB_API_KEY", KEY)

    def install(**kw):
        fake = Omdb(**kw)
        monkeypatch.setattr(requests, "get", fake.get)
        return fake
    return install


def seasons_of(*specs):
    """episode_list-shaped seasons: specs = (n, [(number, played, in_progress, aired), ...])."""
    out = []
    for n, eps in specs:
        out.append({"n": n, "number": n, "episodes": [
            {"number": num, "name": f"Ep {num}", "jf_id": f"e{n}x{num}", "played": p, "in_progress": ip, "aired": a}
            for num, p, ip, a in eps]})
    return out


SHOW = {"kind": "series", "imdb": SERIES, "tmdb": "100"}
S4 = (4, [(1, True, False, True), (2, True, False, True), (3, True, False, True), (4, False, True, True),
          (5, False, False, True), (6, False, False, False)])


# ---- OMDb answers ----

def test_season_fixture_parses_ratings_ids_dates_and_na():
    rows, total = er.parse_season(fixture("season_s4"))
    assert total == 4 and [r["episode"] for r in rows] == [1, 2, 3, 4, 5, 6]
    assert rows[0] == {"episode": 1, "rating": 7.8, "episode_imdb": "tt9200401", "title": "One", "released": "2026-09-14"}
    assert rows[5]["rating"] is None                                   # the unaired episode's "N/A"
    assert er.parse_votes(fixture("episode_votes")) == 1234 and er.parse_votes({"imdbVotes": "N/A"}) == 0
    assert er.parse_season(fixture("not_found")) == ([], None)


def test_one_season_read_is_one_call_and_is_stored(omdb):
    fake = omdb()
    word, rows, total = er.season_ratings(SERIES, 4)
    assert word == "ok" and len(rows) == 6 and total == 4
    assert fake.calls == [{"i": SERIES, "Season": 4, "apikey": KEY}]
    got = er.stored(SERIES)[4]
    assert got[5]["rating"] == 9.0 and got[6]["rating"] is None and got[1]["episode_imdb"] == "tt9200401"
    assert got[1]["fetched_at"] == NOW.isoformat() and got[1]["votes"] is None


# ---- media.db v5 ----

def test_an_existing_v4_db_migrates_to_v5_and_the_table_is_idempotent(db):
    with closing(media_store.connect()):
        pass
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("DROP TABLE episode_rating")
        conn.execute("PRAGMA user_version = 4")                          # a live v4 file
        conn.commit()
    media_store.reset()
    media_store.forget()
    with closing(media_store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 5
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(episode_rating)")]
        assert cols[:7] == ["series_imdb", "season", "episode", "rating", "votes", "episode_imdb", "fetched_at"]
        assert [r["name"] for r in conn.execute("PRAGMA table_info(episode_rating)") if r["pk"]] == \
            ["series_imdb", "season", "episode"]
        er.migrate(conn)                                                  # idempotent
        er.migrate(conn)


def test_reads_never_create_the_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "none" / "media.db"))
    assert er.stored(SERIES) == {} and not (tmp_path / "none").exists()


# ---- the refresh rule ----

def rows_with(fetched: datetime, released: list[str]):
    return {i + 1: {"fetched_at": fetched.isoformat(), "released": d, "rating": 8.0} for i, d in enumerate(released)}


def test_refresh_rule_seven_days_while_airing_else_forever(frozen):
    assert er.season_due(None) and er.season_due({})                                     # never stored
    recent = ["2026-08-01", "2026-09-20"]                                                # aired within 120 days
    assert er.season_due(rows_with(NOW - timedelta(days=8), recent))
    assert not er.season_due(rows_with(NOW - timedelta(days=6), recent))                 # fresh
    old = ["2019-01-01", "2019-02-01"]
    assert not er.season_due(rows_with(NOW - timedelta(days=400), old))                  # finished: kept forever
    edge = [(TODAY - timedelta(days=121)).isoformat()]
    assert not er.season_due(rows_with(NOW - timedelta(days=8), edge))
    assert er.season_due(rows_with(NOW - timedelta(days=8), ["2026-12-01", None]))       # announced, nothing aired yet
    frozen["now"], frozen["today"] = NOW + timedelta(days=200), TODAY + timedelta(days=200)
    assert not er.season_due(rows_with(NOW - timedelta(days=8), recent))                 # time moves on: now finished


def test_a_fresh_stored_season_plans_nothing_and_a_stale_one_is_re_read(omdb, frozen):
    fake = omdb(seasons={4: fixture("season_s4")})
    er.season_ratings(SERIES, 4)
    with closing(media_store.connect()) as conn, conn:
        conn.execute("UPDATE episode_rating SET votes = 5, votes_at = ?", (NOW.isoformat(),))
    fake.calls.clear()
    _, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    assert later is None                                                                 # warm: no call at all
    frozen["now"] = NOW + timedelta(days=8)
    _, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    assert later.plan["seasons"] == [4] and later.plan["votes"] == 5                     # still airing: re-read


# ---- failures, the budget ----

@pytest.mark.parametrize("kw", [{"status": 401, "body": {}}, {"exc": requests.Timeout("t")}, {"status": 503, "body": {}}])
def test_a_failed_season_read_is_remembered_fail_ttl(omdb, monkeypatch, kw):
    fake = omdb(**kw)
    word, _, _ = er.season_ratings(SERIES, 4)
    assert word == "failed" and len(fake.calls) == 1
    media_omdb._day[2] = False                                    # (a 401 also stops OMDb for the day)
    _, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    assert later is None                                          # remembered: no re-read inside FAIL_TTL
    real = er.time.time
    monkeypatch.setattr(er.time, "time", lambda: real() + er.FAIL_TTL + 1)
    _, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    assert later is not None and later.plan["seasons"] == [4]     # after FAIL_TTL it is asked again


def test_a_401_stops_omdb_for_the_day(omdb):
    fake = omdb(status=401, body={})
    er.season_ratings(SERIES, 4)
    assert media_omdb._day[2] is True
    assert er.season_ratings(SERIES, 3)[0] == "stopped" and len(fake.calls) == 1


def test_a_refused_key_body_counts_as_failed_and_stops(omdb):
    omdb(body=fixture("invalid_key"))
    assert er.season_ratings(SERIES, 4)[0] == "failed" and media_omdb._day[2] is True


def test_not_found_is_remembered_ttl_and_falls_back(omdb, frozen):
    fake = omdb(seasons={})
    assert er.season_ratings(SERIES, 4)[0] == "none"
    assert er._memo(er._season_key(SERIES, 4)) == "none"
    fake.calls.clear()
    assert er.fill(SERIES, None, [], 4, [], [4])["seasons"] == 0 and fake.calls == []


def test_the_daily_budget_is_respected(omdb):
    fake = omdb()
    media_omdb._day[:] = [datetime.now(timezone.utc).date().isoformat(), media_omdb.DAILY_CAP, False]
    assert er.season_ratings(SERIES, 4)[0] == "stopped"
    assert fake.calls == [] and er._memo(er._season_key(SERIES, 4)) is None   # a cap marks nothing


def test_no_key_makes_no_call_and_no_plan(omdb, monkeypatch):
    fake = omdb()
    monkeypatch.delenv("OMDB_API_KEY")
    ratings, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    assert ratings is None and later is None and fake.calls == []


# ---- the background read ----

def test_cold_fill_reads_the_seasons_then_the_current_seasons_votes_capped(omdb, monkeypatch):
    fake = omdb()
    _, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    assert later.plan == {"seasons": [4], "votes": 0, "tmdb": []}
    counts = later()
    assert fake.season_calls() == [4, 1, 2, 3]                    # totalSeasons 4 adds the seasons Jellyfin lacks
    assert counts["seasons"] == 2 and counts["none"] == 2
    assert fake.vote_calls() == ["tt9200401", "tt9200402", "tt9200403", "tt9200404", "tt9200405"]  # S4 only; unaired skipped
    assert er.stored(SERIES)[4][1]["votes"] == 1234
    fake.calls.clear()
    assert er.build_ratings(SHOW, seasons_of(S4), "series")[1] is None and fake.calls == []   # warm: 0 calls
    monkeypatch.setattr(er, "VOTES_MAX", 2)
    with closing(media_store.connect()) as conn, conn:
        conn.execute("UPDATE episode_rating SET votes = NULL, votes_at = NULL")
    _, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    later()
    assert len(fake.vote_calls()) == 2                            # at most VOTES_MAX per view


def test_one_fill_per_show_at_a_time(omdb):
    fake = omdb()
    er._running.add(SERIES)
    assert er.fill(SERIES, None, [4], 4, [], [4]) == {"skipped": 1} and fake.calls == []


def test_a_fill_that_breaks_never_raises_and_frees_the_show(omdb, monkeypatch):
    omdb()
    monkeypatch.setattr(er, "season_ratings", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert er.fill(SERIES, None, [4], 4, [], [4])["failed"] == 1 and SERIES not in er._running


def test_logs_carry_counts_never_the_id_or_key(omdb, caplog):
    omdb()
    caplog.set_level(logging.INFO, logger="hub.media_episode_ratings")
    er.build_ratings(SHOW, seasons_of(S4), "series")[1]()
    text = caplog.text
    assert "season reads" in text and SERIES not in text and "tt92" not in text and KEY not in text


# ---- the context block ----

def stored_show(fake_omdb):
    er.build_ratings(SHOW, seasons_of(S4), "series")[1]()
    fake_omdb.calls.clear()


def test_series_context_shape_best_trend_current(omdb):
    fake = omdb()
    stored_show(fake)
    r, later = er.build_ratings(SHOW, seasons_of(S4), "series", None, lambda i: f"/media/item/{i}")
    assert later is None and fake.calls == []
    assert r["source"] == "IMDb" and [s["n"] for s in r["seasons"]] == [3, 4]
    s3, s4 = r["seasons"]
    assert s3 == {"n": 3, "year": 2025, "avg": 7.9, "votes": 0, "seen": 0, "total": 3, "aired": 3, "eps": s3["eps"]}
    assert s3["eps"][0] == {"number": 1, "rating": 7.9, "votes": 0, "aired": True, "seen": False, "in_progress": False,
                            "jf_id": None, "href": None, "name": "Return"}             # an episode not on the server
    assert s4["eps"][0] == {"number": 1, "rating": 7.8, "votes": 1234, "aired": True, "seen": True, "in_progress": False,
                            "jf_id": "e4x1", "href": "/media/item/e4x1", "name": "Ep 1"}
    assert s4["eps"][3]["in_progress"] is True and s4["eps"][5] == {**s4["eps"][5], "rating": None, "aired": False}
    assert (s4["avg"], s4["seen"], s4["total"], s4["aired"], s4["votes"], s4["year"]) == (8.2, 3, 6, 5, 5 * 1234, 2026)
    assert r["best"] == {"season": 4, "number": 5, "name": "Ep 5", "rating": 9.0}
    assert r["trend"] == "S4 up 0.3 on S3"
    assert r["current"] == 4 and r["episode"] is None              # next-up (S4 E4 in progress)


def test_season_and_episode_context(omdb):
    stored_show(omdb())
    r, _ = er.build_ratings(SHOW, seasons_of(S4), "season", 3)
    assert r["current"] == 3 and r["episode"] is None              # the page's season
    r, _ = er.build_ratings(SHOW, seasons_of(S4), "episode", 4, page_episode=5)
    assert r["current"] == 4 and r["episode"] == {"rating": 9.0, "votes": 1234, "vs_avg": "above"}
    r, _ = er.build_ratings(SHOW, seasons_of(S4), "episode", 4, page_episode=4)
    assert r["episode"] == {"rating": 7.6, "votes": 1234, "vs_avg": "below"}
    r, _ = er.build_ratings(SHOW, seasons_of(S4), "episode", 4, page_episode=6)
    assert r["episode"] == {"rating": None, "votes": 0, "vs_avg": None}     # unaired
    assert er.build_ratings(SHOW, seasons_of(S4), "movie") == (None, None)


def test_current_falls_back_to_the_latest_aired_season():
    def season(n, eps):
        return {"n": n, "aired": sum(1 for e in eps if e["aired"]), "eps": eps}
    done = [{"in_progress": False, "aired": True, "seen": True, "jf_id": "x"}]
    later = [{"in_progress": False, "aired": False, "seen": False, "jf_id": "y"}]
    assert er._current([season(1, done), season(2, done), season(3, later)], None) == 2
    assert er._current([season(1, done)], 7) == 1


def test_trend_needs_two_seasons_with_three_rated_episodes():
    def season(n, ratings):
        eps = [{"aired": True, "rating": x} for x in ratings]
        return {"n": n, "avg": er._avg(eps), "eps": eps}
    assert er._trend([season(1, [8.0, 8.2, 8.4])]) is None
    assert er._trend([season(1, [8.0, 8.2, 8.4]), season(2, [7.0, 7.1])]) is None
    assert er._trend([season(1, [8.0, 8.2, 8.4]), season(2, [7.9, 7.9, 7.9])]) == "S2 down 0.3 on S1"
    assert er._trend([season(1, [8.0, 8.0, 8.0]), season(2, [8.0, 8.0, 8.0])]) == "S2 level with S1"


# ---- the TMDB fallback ----

TMDB_S4 = {"episodes": [{"episodeNumber": 1, "name": "One", "voteAverage": 7.25, "voteCount": 12, "airDate": "2026-09-14"},
                        {"episodeNumber": 2, "name": "Two", "voteAverage": 8.0, "airDate": "2026-09-21"},
                        {"episodeNumber": 6, "name": "Six", "voteAverage": 0, "airDate": "2026-10-26"}]}


@pytest.fixture()
def seerr(monkeypatch, db, frozen):
    monkeypatch.setenv("JELLYSEERR_URL", SEERR_URL)
    monkeypatch.setenv("JELLYSEERR_API_KEY", "k")
    calls = []

    def get(url, headers=None, timeout=None, **kw):
        calls.append(url)
        return R(TMDB_S4) if url == f"{SEERR_URL}/api/v1/tv/100/season/4" else R({}, 404)
    monkeypatch.setattr(requests, "get", get)
    return calls


def test_tmdb_fallback_without_an_imdb_id(seerr, monkeypatch):
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    show = {"kind": "series", "imdb": None, "tmdb": "100"}
    r, later = er.build_ratings(show, seasons_of(S4), "series")
    assert r is None and later.plan == {"seasons": [], "votes": 0, "tmdb": [4]} and seerr == []   # nothing before the render
    later()
    assert seerr == [f"{SEERR_URL}/api/v1/tv/100/season/4"]
    r, later = er.build_ratings(show, seasons_of(S4), "series")
    assert later is None and r["source"] == "TMDB"
    eps = r["seasons"][0]["eps"]
    assert (eps[0]["rating"], eps[0]["votes"], eps[1]["rating"], eps[5]["rating"]) == (7.2, 12, 8.0, None)


def test_tmdb_fallback_when_omdb_has_nothing(seerr, monkeypatch):
    monkeypatch.setenv("OMDB_API_KEY", KEY)
    fake = Omdb(seasons={})

    def route(url, params=None, headers=None, timeout=None, **kw):
        return fake.get(url, params) if url == media_omdb.URL else seerr_get(url, headers=headers)
    seerr_get = requests.get
    monkeypatch.setattr(requests, "get", route)
    _, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    counts = later()
    assert fake.season_calls() == [4] and counts["none"] == 1 and counts["tmdb"] == 1
    r, later = er.build_ratings(SHOW, seasons_of(S4), "series")
    assert r["source"] == "TMDB" and later is None


# ---- the page ----

def wire(env, monkeypatch, tmp_path, imdb=SERIES):
    """The film page env with ser1 carrying an IMDb id, OMDb faked beside Jellyfin / Jellyseerr, and the page's `film`
    captured as rendered (after the route has taken `ratings_later` off it)."""
    monkeypatch.setenv("OMDB_API_KEY", KEY)
    monkeypatch.setenv("META_CACHE_DIR", str(tmp_path / "meta"))
    monkeypatch.setattr(er, "_now", lambda: NOW)
    monkeypatch.setattr(er, "_today", lambda: TODAY)
    if imdb:
        monkeypatch.setitem(ITEMS, "ser1", {**ITEMS["ser1"], "ProviderIds": {"Tmdb": "100", "Imdb": imdb}})
    monkeypatch.setitem(ITEMS, "sea1", {"Id": "sea1", "Type": "Season", "Name": "Season 4", "SeriesId": "ser1",
                                        "SeriesName": "Quiet Show", "IndexNumber": 4, "UserData": {}})
    client, both = env()
    fake = Omdb()
    monkeypatch.setattr(requests, "get", lambda url, **kw: fake.get(url, **kw) if url == media_omdb.URL
                        else both.get(url, **kw))
    seen = []
    real = media_film._render

    def capture(request, src, film, *a, **k):
        resp = real(request, src, film, *a, **k)
        seen.append(dict(film))
        return resp
    monkeypatch.setattr(media_film, "_render", capture)
    return client, fake, seen


def test_series_page_cold_then_warm(env, monkeypatch, tmp_path):
    client, fake, seen = wire(env, monkeypatch, tmp_path)
    with client:
        assert client.get("/media/item/ser1").status_code == 200
        assert seen[-1]["ratings"] is None and "ratings_later" not in seen[-1]   # nothing stored: nothing drawn
        assert fake.season_calls() == [4, 1, 2, 3] and len(fake.vote_calls()) == 5   # the BackgroundTask, after it
        fake.calls.clear()
        assert client.get("/media/item/ser1").status_code == 200
    r = seen[-1]["ratings"]
    assert fake.ep_calls() == []                                                      # warm: no OMDb call
    assert r["source"] == "IMDb" and [s["n"] for s in r["seasons"]] == [3, 4] and r["current"] == 4
    s4 = r["seasons"][1]
    assert [e["jf_id"] for e in s4["eps"]] == ["ep1", "ep2", "ep3", "ep4", "ep5", "ep6"]
    assert [e["seen"] for e in s4["eps"]] == [True, True, True, False, False, False]
    assert s4["eps"][3]["in_progress"] and not s4["eps"][5]["aired"] and s4["eps"][5]["rating"] is None
    assert s4["eps"][0]["href"] == "/media/item/ep1" and s4["eps"][0]["name"] == "One"


def test_season_and_episode_pages_carry_ratings(env, monkeypatch, tmp_path):
    client, fake, seen = wire(env, monkeypatch, tmp_path)
    with client:
        client.get("/media/item/ser1")
        assert client.get("/media/item/sea1").status_code == 200
        season_page = seen[-1]["ratings"]
        assert client.get("/media/item/ep3").status_code == 200
        ep_page = seen[-1]["ratings"]
    assert season_page["current"] == 4 and season_page["episode"] is None
    assert ep_page["current"] == 4 and ep_page["episode"] == {"rating": 8.4, "votes": 1234, "vs_avg": "above"}
    assert [s["n"] for s in ep_page["seasons"]] == [3, 4]                        # every season: the compare chart


def test_a_failing_omdb_never_fails_the_page(env, monkeypatch, tmp_path):
    client, fake, seen = wire(env, monkeypatch, tmp_path)
    fake.exc = requests.Timeout("t")
    with client:
        assert client.get("/media/item/ser1").status_code == 200
        assert fake.season_calls() == [4]
        fake.calls.clear()
        assert client.get("/media/item/ser1").status_code == 200
    assert fake.ep_calls() == [] and seen[-1]["ratings"] is None                     # remembered FAIL_TTL


def test_movie_page_has_no_ratings_and_no_episode_reads(env, monkeypatch, tmp_path):
    client, fake, seen = wire(env, monkeypatch, tmp_path)
    with client:
        assert client.get("/media/item/mov1").status_code == 200
    assert seen[-1]["ratings"] is None and fake.season_calls() == [] and fake.vote_calls() == []


def test_off_server_tv_title_has_no_ratings(env, monkeypatch, tmp_path):
    client, fake, seen = wire(env, monkeypatch, tmp_path)
    media_discover.clear_cache()
    with client:
        client.get("/media/title/tv/555")
    assert (seen[-1] if seen else {}).get("ratings") is None and fake.ep_calls() == []


# ---- JY-119 (2026-10-24, B.: "JY-119: A"): a show that is not on the server gets episode ratings too ----

OFF_IMDB = "tt9100777"
OFF_SHOW = {"id": 777, "name": "Far Show", "firstAirDate": "2021-03-01", "numberOfSeasons": 2, "numberOfEpisodes": 12,
            "posterPath": "/fs.jpg", "mediaInfo": {"status": 1}, "externalIds": {"imdbId": OFF_IMDB},
            "seasons": [{"seasonNumber": 0, "name": "Specials", "episodeCount": 2, "airDate": "2021-01-01"},
                        {"seasonNumber": 1, "name": "Season 1", "episodeCount": 6, "airDate": "2021-03-01"},
                        {"seasonNumber": 2, "name": "Season 2", "episodeCount": 6, "airDate": "2022-03-01"}]}


def wire_off(env, monkeypatch, tmp_path, show=None, seasons=None, tmdb=None):
    """`wire` plus a show Jellyseerr knows (tmdb 777) and Jellyfin does not. `tmdb` = {season n: Jellyseerr season body}."""
    client, fake, seen = wire(env, monkeypatch, tmp_path)
    fake.seasons = {1: fixture("season_s4"), 2: fixture("season_s3")} if seasons is None else seasons
    table = {"/api/v1/tv/777": show or OFF_SHOW}
    for n, body in (tmdb or {}).items():
        table[f"/api/v1/tv/777/season/{n}"] = body
    inner = requests.get

    def route(url, **kw):
        path = url[len(SEERR_URL):] if url.startswith(SEERR_URL) else None
        if path in table:
            return R(table[path])
        return inner(url, **kw)
    monkeypatch.setattr(requests, "get", route)
    media_discover.clear_cache()
    return client, fake, seen


def test_off_server_cold_page_draws_no_block_and_queues_the_reads(env, monkeypatch, tmp_path):
    client, fake, seen = wire_off(env, monkeypatch, tmp_path)
    with client:
        r = client.get("/media/title/tv/777")
    assert r.status_code == 200 and seen[-1]["ratings"] is None and "ratings_later" not in seen[-1]
    assert "Seasons compared" not in r.text and 'id="compare"' not in r.text            # nothing stored: nothing drawn
    assert fake.season_calls()[:2] == [1, 2]                                            # Seerr's seasons, Specials left out: the BackgroundTask
    assert 0 not in fake.season_calls()


def test_off_server_render_reads_nothing_it_only_hands_the_job_to_the_background_task(env, monkeypatch, tmp_path):
    client, fake, seen = wire_off(env, monkeypatch, tmp_path)
    jobs = []
    monkeypatch.setattr(er, "fill", lambda *a: jobs.append(a) or {})
    with client:
        assert client.get("/media/title/tv/777").status_code == 200
    assert fake.season_calls() == [] and [i for i in fake.vote_calls() if i != OFF_IMDB] == [] and len(jobs) == 1
    # ^ no episode read in the render (OFF_IMDB alone is the Metacritic pill's own lookup, as on any title page)
    imdb, tmdb, seasons, current, votes, jf_seasons = jobs[0]
    assert (imdb, tmdb, seasons, jf_seasons) == (OFF_IMDB, 777, [1, 2], [1, 2])


def test_off_server_next_view_draws_seasons_compared_from_stored_rows(env, monkeypatch, tmp_path):
    client, fake, seen = wire_off(env, monkeypatch, tmp_path)
    with client:
        client.get("/media/title/tv/777")
        fake.calls.clear()
        r = client.get("/media/title/tv/777")
    assert fake.ep_calls() == []                                                        # warm: stored rows only
    ratings = seen[-1]["ratings"]
    assert ratings["source"] == "IMDb" and [s["n"] for s in ratings["seasons"]] == [1, 2]
    assert 'id="compare"' in r.text and "Seasons compared" in r.text and "IMDb episode ratings" in r.text
    assert 'id="rating-strip"' in r.text and r.text.count('class="cmprow') == 2


def test_off_server_compare_rows_land_on_the_seasons_list(env, monkeypatch, tmp_path):
    client, fake, seen = wire_off(env, monkeypatch, tmp_path)
    with client:
        client.get("/media/title/tv/777")
        r = client.get("/media/title/tv/777")
    assert 'href="?season=2#season-2"' in r.text and 'id="season-2"' in r.text          # the row's #season-N anchor exists


def test_off_server_ratings_carry_no_watch_state_and_no_episode_links(env, monkeypatch, tmp_path):
    client, fake, seen = wire_off(env, monkeypatch, tmp_path)
    with client:
        client.get("/media/title/tv/777")
        client.get("/media/title/tv/777")
    eps = [e for s in seen[-1]["ratings"]["seasons"] for e in s["eps"]]
    assert eps and not any(e["seen"] or e["in_progress"] or e["jf_id"] or e["href"] for e in eps)
    assert all(s["seen"] == 0 for s in seen[-1]["ratings"]["seasons"])


def test_off_server_tmdb_fallback_with_no_imdb_id(env, monkeypatch, tmp_path):
    show = {**OFF_SHOW, "externalIds": {}}
    s1 = {"episodes": [{"episodeNumber": 1, "name": "One", "voteAverage": 7.25, "voteCount": 12, "airDate": "2021-03-01"},
                       {"episodeNumber": 2, "name": "Two", "voteAverage": 8.0, "voteCount": 30, "airDate": "2021-03-08"}]}
    client, fake, seen = wire_off(env, monkeypatch, tmp_path, show=show, tmdb={1: s1, 2: {"episodes": []}})
    with client:
        client.get("/media/title/tv/777")
        r = client.get("/media/title/tv/777")
    assert fake.ep_calls() == []                                                        # no IMDb id: OMDb is never asked
    assert seen[-1]["ratings"]["source"] == "TMDB" and "TMDB episode ratings" in r.text


def test_off_server_without_an_omdb_key_falls_back_to_tmdb(env, monkeypatch, tmp_path):
    s1 = {"episodes": [{"episodeNumber": 1, "name": "One", "voteAverage": 7.25, "voteCount": 12, "airDate": "2021-03-01"}]}
    client, fake, seen = wire_off(env, monkeypatch, tmp_path, tmdb={1: s1, 2: {"episodes": []}})
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    with client:
        client.get("/media/title/tv/777")
        client.get("/media/title/tv/777")
    assert fake.ep_calls() == [] and seen[-1]["ratings"]["source"] == "TMDB"


def test_off_server_seasons_are_capped_and_specials_left_out(env, monkeypatch, tmp_path):
    many = {**OFF_SHOW, "seasons": [{"seasonNumber": n, "name": f"Season {n}", "episodeCount": 3, "airDate": "2010-01-01"}
                                    for n in range(0, 16)]}
    client, fake, seen = wire_off(env, monkeypatch, tmp_path, show=many, seasons={})
    jobs = []
    monkeypatch.setattr(er, "fill", lambda *a: jobs.append(a) or {})
    with client:
        client.get("/media/title/tv/777")
    assert jobs[0][2] == list(range(1, er.SEASONS_MAX + 1))


def test_off_server_failing_omdb_never_fails_the_page(env, monkeypatch, tmp_path):
    client, fake, seen = wire_off(env, monkeypatch, tmp_path)
    fake.exc = requests.Timeout("t")
    with client:
        assert client.get("/media/title/tv/777").status_code == 200
        fake.calls.clear()
        assert client.get("/media/title/tv/777").status_code == 200
    assert seen[-1]["ratings"] is None and fake.ep_calls() == []                        # remembered FAIL_TTL


def test_on_server_show_page_is_unchanged_by_the_off_server_path(env, monkeypatch, tmp_path):
    client, fake, seen = wire_off(env, monkeypatch, tmp_path, seasons={4: fixture("season_s4"), 3: fixture("season_s3")})
    with client:
        client.get("/media/item/ser1")
        client.get("/media/item/ser1")
    r = seen[-1]["ratings"]
    assert r["source"] == "IMDb" and [s["n"] for s in r["seasons"]] == [3, 4]           # its own show, its Jellyfin seasons
    assert any(e["jf_id"] for s in r["seasons"] for e in s["eps"])
