"""Season state words (WP-T1, 2026-10-19): Sonarr's episodes-to-come / aired-not-downloaded words on the show, season and
episode pages, My shows, Activity › Library and Requests; and the on-server rule - a show is "On server" only with an
episode file, a series Jellyfin lists with 0 episodes (Sonarr's folder before the first file) reads "Requested ·
waiting for the first episode". Sonarr is faked at `requests.get` (the kept "arr" session goes through it in tests);
Jellyfin / Jellyseerr through tests/hub/helpers."""
import html
import logging
import re
from datetime import date, datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient

from hub import media_season_state as mss, media_text, media_watchlist, shell
from tests.hub import helpers
from tests.hub.conftest import main_of
from tests.hub.helpers import FakeResponse, env  # noqa: F401  (env: the film-page fixture)
from tests.hub.test_media_frame import env as frame_env  # noqa: F401

SONARR = "http://sonarr.secret-host.invalid:8989"
SKEY = "sonarr-SECRET-key-99"
NOW = datetime.now(timezone.utc)
YEAR = date.today().year


def at(days, hour=1):
    """An airDateUtc `days` from now, at 01:00 UTC (midday at home - the same calendar day)."""
    d = (NOW + timedelta(days=days)).date()
    return f"{d.isoformat()}T{hour:02d}:00:00Z"


def words(days):
    """The page's words for the air day `days` from now ('2 Nov', the year only when it is not this one)."""
    return media_text.short_date(mss._day(at(days)))


def season(n, files, total, aired=None, nxt=None, prev=True):
    return {"seasonNumber": n, "monitored": True,
            "statistics": {"episodeFileCount": files, "episodeCount": files if aired is None else aired,
                           "totalEpisodeCount": total, "nextAiring": nxt,
                           "previousAiring": at(-30) if prev else None}}


def series(sid, title, seasons, tvdb=None, tmdb=None, status="continuing"):
    return {"id": sid, "title": title, "tvdbId": tvdb, "tmdbId": tmdb, "status": status, "seasons": seasons}


def episode(n, s, has_file, air_days):
    return {"seasonNumber": s, "episodeNumber": n, "hasFile": has_file, "monitored": True,
            "airDateUtc": at(air_days) if air_days is not None else None}


QUIET = series(1, "Quiet Show", [season(0, 0, 3, prev=False), season(4, 5, 8, nxt=at(3))], tmdb=100)
QUIET_EPS = [episode(i, 4, True, -20 + i) for i in range(1, 6)] + [episode(6, 4, False, 3), episode(7, 4, False, 10),
                                                                    episode(8, 4, False, None)]
EMPTY = series(2, "Empty Show", [season(1, 0, 9, aired=0, nxt=at(47), prev=False)], tvdb=7700, tmdb=300)
WAR = series(3, "WAR", [season(1, 3, 8, nxt=at(5))], tvdb=8800, tmdb=400)


class SonarrFake:
    def __init__(self, entries=(QUIET, EMPTY, WAR), episodes=None):
        self.entries, self.episodes = list(entries), episodes if episodes is not None else {(1, 4): QUIET_EPS}
        self.calls, self.status = [], 200

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert url.startswith(SONARR) and headers == {"X-Api-Key": SKEY}
        path = url[len(SONARR):]
        self.calls.append((path, dict(params or {})))
        if self.status != 200:
            return FakeResponse({}, self.status)
        if path == "/api/v3/series":
            return FakeResponse(self.entries)
        if path == "/api/v3/episode":
            return FakeResponse(self.episodes.get((params["seriesId"], params["seasonNumber"]), []))
        return FakeResponse({}, 404)


@pytest.fixture()
def sonarr(monkeypatch):
    """Sonarr connected and faked; other hosts go to whatever `requests.get` was before (or fail)."""
    monkeypatch.setenv("SONARR_URL", SONARR)
    monkeypatch.setenv("SONARR_API_KEY", SKEY)
    fake = SonarrFake()

    def install():
        before = requests.get

        def get(url, *a, **kw):
            return fake.get(url, *a, **kw) if str(url).startswith(SONARR) else before(url, *a, **kw)
        monkeypatch.setattr(requests, "get", get)
        return fake
    fake.install = install
    install()
    return fake


def prime():
    """The background read, run now: the series list, then every incomplete season's episode list."""
    mss.refresh([], True, [])
    for key in ((None, 100), (7700, 300), (8800, 400)):
        entry = mss._entry(*key)
        if entry:
            mss.refresh([], False, [(entry["id"], n) for n in mss._seasons_due(entry)])


# ---- 1. the words (pure) ----

def test_season_words_for_each_case():
    nov2 = f"{YEAR}-11-02"
    assert mss.season_word(1, 6, 6, 6, 0, 0, None) == "Complete"
    assert mss.season_word(1, 3, 8, 3, 5, 0, nov2) == "5 to come · next airs 2 Nov"
    assert mss.season_word(1, 3, 8, 3, 5, 0, None) == "5 to come · date TBA"
    assert mss.season_word(1, 4, 6, 6, 0, 2, None) == "2 aired, not downloaded"
    assert mss.season_word(1, 1, 8, 3, 5, 2, nov2) == "2 aired, not downloaded · 5 to come · next airs 2 Nov"
    assert mss.season_word(1, 0, 9, 0, 9, 0, f"{YEAR}-12-05") == "Waiting for the first episode · airs 5 Dec"
    assert mss.season_word(1, 0, 9, 0, 9, 0, None) == "Waiting for the first episode · date TBA"
    assert mss.season_word(3, 0, 1, 0, 1, 0, None) == "Season 3 announced"
    assert mss.season_word(4, 0, 0, 0, 0, 0, None) is None
    assert mss.season_word(1, 3, 8, 3, 5, 0, f"{YEAR + 1}-01-04") == f"5 to come · next airs 4 Jan {YEAR + 1}"


def test_build_from_series_statistics_alone():
    war = mss.build(WAR)
    s1 = war["by_n"][1]
    assert (s1["files"], s1["total"], s1["aired"], s1["to_come"], s1["missing"]) == (3, 8, 3, 5, 0)
    assert s1["word"] == f"5 to come · next airs {words(5)}" and war["word"] == s1["word"]
    assert (war["files"], war["total"], war["status"]) == (3, 8, "continuing")
    empty = mss.build(EMPTY)
    assert empty["word"] == f"Waiting for the first episode · airs {words(47)}" and mss.waiting(empty)
    assert 0 not in mss.build(QUIET)["by_n"]          # specials never count


def test_series_words_complete_up_to_date_announced_and_missing():
    done = [season(1, 8, 8), season(2, 7, 7)]
    assert mss.build(series(9, "x", done, status="ended"))["word"] == "Complete"
    assert mss.build(series(9, "x", done, status="continuing"))["word"] == "Up to date"
    landman = mss.build(series(9, "x", done + [season(3, 0, 1, aired=0, prev=False)]))
    assert landman["word"] == "Season 3 announced" and landman["by_n"][3]["word"] == "Season 3 announced"
    assert landman["to_come"] == 0                     # a placeholder season is not "1 to come"
    lioness = mss.build(series(9, "x", [season(1, 8, 8), season(2, 8, 8), season(3, 8, 19, aired=19)]))
    assert lioness["word"] == "11 aired, not downloaded"


def test_episode_lists_give_exact_counts():
    state = mss.build(QUIET, {4: QUIET_EPS})
    s4 = state["by_n"][4]
    assert (s4["files"], s4["total"], s4["aired"], s4["to_come"], s4["missing"]) == (5, 8, 5, 3, 0)
    assert s4["next_air"] == mss._day(at(3)) and s4["word"] == f"3 to come · next airs {words(3)}"
    late = [episode(1, 4, True, -9), episode(2, 4, False, -2), episode(3, 4, False, 4)]
    s = mss.build(QUIET, {4: late})["by_n"][4]
    assert s["word"] == f"1 aired, not downloaded · 1 to come · next airs {words(4)}"


# ---- 2. the cache, the memo, the BackgroundTask plan ----

def test_no_call_until_the_background_job_and_then_words(sonarr):
    assert mss.season_states(None, 100) is None and sonarr.calls == []
    job = mss.later([(None, 100)])
    assert job is not None and job.plan == {"index": True, "seasons": [], "detail": False} and sonarr.calls == []
    assert job() == {"index": 1, "seasons": 0, "failed": 0}
    assert [c[0] for c in sonarr.calls] == ["/api/v3/series"]
    assert mss.season_states(None, 100)["word"] == f"3 to come · next airs {words(3)}"   # from the statistics
    assert mss.later([(None, 100)]) is None            # warm: nothing due, no task
    detail = mss.later([(None, 100)], detail=True)     # a show page wants the incomplete season's episode list
    assert detail.plan["seasons"] == [(1, 4)]
    detail()
    assert sonarr.calls[-1] == ("/api/v3/episode", {"seriesId": 1, "seasonNumber": 4})
    assert mss.season_states(None, 100)["by_n"][4]["word"] == f"3 to come · next airs {words(3)}"
    assert mss.later([(None, 100)], detail=True) is None


def test_detail_on_a_cold_cache_reads_the_list_then_the_seasons(sonarr):
    job = mss.later([(8800, None)], detail=True)
    assert job.plan["index"] is True
    assert job() == {"index": 1, "seasons": 1, "failed": 0}
    assert [c[0] for c in sonarr.calls] == ["/api/v3/series", "/api/v3/episode"]


def test_episode_reads_are_capped_per_show(sonarr):
    many = series(5, "Long", [season(n, 0, 10) for n in range(1, 7)], tvdb=5500)
    sonarr.entries = [many]
    mss.refresh([], True, [])
    assert mss._seasons_due(mss._entry(5500)) == [6, 5, 4]        # the latest EP_SEASONS_MAX incomplete seasons


def test_matched_by_tvdb_then_tmdb_never_by_title(sonarr):
    mss.refresh([], True, [])
    assert mss.season_states(8800, None)["series_id"] == 3
    assert mss.season_states(None, 400)["series_id"] == 3
    assert mss.season_states(1, 999) is None                       # unknown ids: nothing, whatever the title


def test_a_failed_read_keeps_the_last_good_answer_and_is_not_retried_at_once(sonarr, caplog):
    mss.refresh([], True, [])
    good = mss.season_states(8800)["word"]
    mss._index["at"] -= mss.TTL + 1                                 # stale
    sonarr.status = 503
    with caplog.at_level(logging.WARNING):
        assert mss.later([(8800, None)])() == {"index": 0, "seasons": 0, "failed": 1}
    assert mss.season_states(8800)["word"] == good                 # last good, served however old
    assert mss.later([(8800, None)]) is None                       # FAIL_TTL: no second ask yet
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "HTTP 503" in logged and SONARR not in logged and SKEY not in logged and "secret-host" not in logged


def test_failure_never_raises(sonarr, monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError(f"{SONARR}/api/v3/series?apikey={SKEY}")
    monkeypatch.setattr(requests, "get", boom)
    assert mss.later([(8800, None)], detail=True)()["failed"] == 1
    assert mss.season_states(8800) is None


def test_not_connected_means_no_state_and_no_task(monkeypatch):
    monkeypatch.delenv("SONARR_URL", raising=False)
    monkeypatch.delenv("SONARR_API_KEY", raising=False)
    assert mss.season_states(8800, 400) is None and mss.later([(8800, 400)], detail=True) is None


# ---- 3. show / season / episode pages ----

def status(page):
    return html.unescape(re.search(r'id="status-line">([^<]*)<', page).group(1))


def test_show_page_never_calls_sonarr_before_the_render_then_has_the_words(env, sonarr, monkeypatch):
    client, both = env()
    sonarr.install()
    order = []
    real = shell.render_page

    def render(*a, **kw):
        order.append("render")
        return real(*a, **kw)
    monkeypatch.setattr(shell, "render_page", render)
    real_get = sonarr.get
    sonarr.get = lambda *a, **kw: (order.append("sonarr"), real_get(*a, **kw))[1]
    with client:
        first = client.get("/media/item/ser1").text
        assert status(first) == "On server · 6 episodes · 2 left · S4 E4 next"     # cold: the words of before
        assert order[0] == "render" and "sonarr" in order                          # the reads ran AFTER the render
        assert [c[0] for c in sonarr.calls] == ["/api/v3/series", "/api/v3/episode"]
        second = client.get("/media/item/ser1").text
    nxt = words(3)
    assert status(second) == f"On server · 5 of 8 episodes · 2 left · S4 E4 next · 3 to come · next airs {nxt}"
    body = main_of(second)
    assert f'<span class="seasoncount">3 of 6 watched</span> · <span class="seasonstate">3 to come · next airs {nxt}</span>' in body
    assert len(sonarr.calls) == 2                                                 # warm: no further call


def test_all_watched_is_never_the_last_word_while_episodes_are_due(env, sonarr, monkeypatch):
    eps = [dict(e, UserData={"Played": True}) for e in helpers.EPISODES]
    monkeypatch.setattr(helpers, "EPISODES", eps)
    client, _ = env()
    sonarr.install()
    prime()
    with client:
        line = status(client.get("/media/item/ser1").text)
    assert "all watched" in line and not line.endswith("all watched")
    assert line.endswith(f"3 to come · next airs {words(3)}")


def test_complete_only_when_sonarr_agrees(env, sonarr):
    sonarr.entries = [series(1, "Quiet Show", [season(4, 6, 6)], tmdb=100, status="ended")]
    client, _ = env()
    sonarr.install()
    prime()
    with client:
        assert status(client.get("/media/item/ser1").text) == "On server · 6 episodes · 2 left · S4 E4 next · Complete"


def test_words_unchanged_without_sonarr_or_when_it_fails(env, sonarr, monkeypatch):
    client, _ = env()
    sonarr.install()
    sonarr.status = 500
    with client:
        r1 = client.get("/media/item/ser1")
        r2 = client.get("/media/item/ser1")
    assert r1.status_code == r2.status_code == 200
    assert status(r2.text) == "On server · 6 episodes · 2 left · S4 E4 next"
    assert "seasonstate" not in r2.text


def test_episode_and_season_pages_carry_the_season_state(env, sonarr, monkeypatch):
    monkeypatch.setitem(helpers.ITEMS, "sea1", {"Id": "sea1", "Type": "Season", "Name": "Season 4", "SeriesId": "ser1",
                                                "SeriesName": "Quiet Show", "IndexNumber": 4,
                                                "UserData": {"Played": False}})
    client, _ = env()
    sonarr.install()
    prime()
    nxt = words(3)
    with client:
        ep_page = main_of(client.get("/media/item/ep3").text)
        season_page = main_of(client.get("/media/item/sea1").text)
    for page in (ep_page, season_page):
        line = re.search(r'class="partof-line">(.*?)</p>', page).group(1)
        assert line.endswith(f" · 3 of 6 watched · 3 to come · next airs {nxt}")


# ---- 4. the on-server rule: a series with 0 episodes, a Sonarr-only show ----

EMPTY_ITEM = {"Id": "ser0", "Type": "Series", "Name": "Empty Show", "ProductionYear": 2026, "Genres": ["Drama"],
              "ProviderIds": {"Tmdb": "300", "Tvdb": "7700"}, "Overview": "Not yet.", "UserData": {"Played": False}}
EMPTY_ROW = {"item_key": "tmdb:300", "jf_id": "ser0", "title": "Empty Show", "year": 2026, "episodes": 0,
             "unplayed": 0, "poster": "jf:ser0"}


def empty_jellyfin(monkeypatch, both):
    monkeypatch.setitem(helpers.ITEMS, "ser0", EMPTY_ITEM)
    real = both.jf.get

    def get(url, params=None, headers=None, timeout=None, **kw):
        if url.endswith("/Shows/ser0/Episodes") or url.endswith("/Shows/ser0/Seasons"):
            return FakeResponse({"Items": []})
        return real(url, params=params, headers=headers, timeout=timeout)
    both.jf.get = get


def test_a_series_jellyfin_lists_with_no_episode_is_not_on_server(env, sonarr, monkeypatch):
    monkeypatch.delenv("SONARR_URL")                                # without Sonarr: the bare words
    client, both = env(jelly_extra={"shows": helpers.LIB_SHOWS + [EMPTY_ROW]})
    empty_jellyfin(monkeypatch, both)
    with client:
        page = client.get("/media/item/ser0").text
    assert status(page) == "Requested · waiting for the first episode"
    assert "statusline st-good" not in page and "Play ▶" not in page


def test_an_empty_series_reads_sonarrs_air_date(env, sonarr, monkeypatch):
    client, both = env(jelly_extra={"shows": helpers.LIB_SHOWS + [EMPTY_ROW]})
    empty_jellyfin(monkeypatch, both)
    sonarr.install()
    prime()
    with client:
        assert status(client.get("/media/item/ser0").text) == f"Requested · waiting for the first episode · airs {words(47)}"


def test_title_page_skips_the_empty_library_row_and_seerr_available_is_not_enough(env, sonarr, monkeypatch):
    client, both = env(jelly_extra={"shows": helpers.LIB_SHOWS + [EMPTY_ROW]},
                       seerr_snap=[{"id": 5, "kind": "tv", "tmdb_id": 300, "title": "Empty Show",
                                    "status_text": "Available", "when": "3 days ago", "tvdb_id": 7700}])
    both.seerr.table["/api/v1/tv/300"] = {"id": 300, "name": "Empty Show", "firstAirDate": f"{YEAR}-12-05",
                                          "mediaInfo": {"status": 5}, "externalIds": {"tvdbId": 7700}}
    sonarr.install()
    prime()
    with client:
        page = client.get("/media/title/tv/300").text
    assert status(page) == f"Requested 3 days ago · waiting for the first episode · airs {words(47)}"
    assert "statusline st-good" not in page and "On server" not in status(page)


def test_a_partly_downloaded_show_says_how_many_of_how_many(env, sonarr):
    sonarr.entries = [series(1, "Quiet Show", [season(4, 3, 8, nxt=at(5))], tmdb=100)]
    sonarr.episodes = {}
    client, _ = env()
    sonarr.install()
    mss.refresh([], True, [])
    with client:
        line = status(client.get("/media/item/ser1").text)
    assert line.startswith("On server · 3 of 8 episodes · ") and line.endswith(f"5 to come · next airs {words(5)}")


def test_on_server_keys_leave_out_an_empty_series():
    jelly = {"shows": helpers.LIB_SHOWS + [EMPTY_ROW, {"item_key": "tmdb:301", "title": "Old row, no count"}]}
    assert media_watchlist.on_server_keys(jelly, "tv") == {"tmdb:100", "tmdb:301"}


# ---- 5. My shows, Activity › Library, Requests ----

def lib_show(title, key, eps, unplayed, jf):
    return {"title": title, "year": 2026, "jf_id": jf, "item_key": key, "poster": f"jf:{jf}", "backdrop": None,
            "status_word": "Continuing", "episodes": eps, "unplayed": unplayed, "played": unplayed == 0,
            "last_played_at": None, "added_at": NOW.isoformat(), "community_rating": None, "genres": []}


SHOWS = [lib_show("Quiet Show", "tmdb:100", 6, 0, "ser1"), lib_show("Busy Show", "tmdb:101", 4, 2, "ser5"),
         lib_show("Empty Show", "tmdb:300", 0, 0, "ser0")]


def test_my_shows_leaves_the_empty_series_out_and_lists_it_as_waiting(frame_env, sonarr):
    main = frame_env(jellyfin={**helpers.JELLY, "server_id": "srv", "shows": SHOWS, "movies": []})
    sonarr.install()
    with TestClient(main.app) as c:
        cold = main_of(c.get("/media/tv?view=list").text)
        warm = main_of(c.get("/media/tv?view=list").text)
    library = cold.split('id="waiting"')[0]
    assert "Empty Show" not in library and "2 shows ·" in cold
    waiting = cold.split('id="waiting"')[1]
    assert "Waiting for the first episode · 1" in waiting and "Requested · waiting for the first episode<" in waiting
    assert f"Requested · waiting for the first episode · airs {words(47)}" in warm.split('id="waiting"')[1]
    assert [c[0] for c in sonarr.calls] == ["/api/v3/series"]      # one list read serves the whole page, after it


def test_my_shows_calls_a_watched_show_caught_up_while_more_is_due(frame_env, sonarr):
    main = frame_env(jellyfin={**helpers.JELLY, "server_id": "srv", "shows": SHOWS, "movies": []})
    sonarr.install()
    mss.refresh([], True, [])
    with TestClient(main.app) as c:
        grid = main_of(c.get("/media/tv").text)
        rows = main_of(c.get("/media/tv?view=list").text)
    assert ">Caught up · more to come · 1<" in grid and ">Caught up</span>" in grid
    assert f'card-progress">3 to come · next airs {words(3)}</span>' in grid
    assert "6 episodes · All watched · 3 to come" in rows
    assert "1 caught up · 0 finished" in rows


def test_activity_library_does_not_link_to_an_empty_series(frame_env):
    week = {"title": "Empty Show · S01E01 · Pilot", "kind": "episode", "date": date.today().isoformat(),
            "label": "Premiere", "item_key": "tvdb:7700", "poster": None}
    main = frame_env(jellyfin={**helpers.JELLY, "server_id": "srv", "shows": SHOWS, "movies": []},
                     arr={"summary": "x", "this_week": [week]})
    with TestClient(main.app) as c:
        body = main_of(c.get("/media/library").text)
    assert "Empty Show · S01E01 · Pilot" in body and "/media/item/ser0" not in body


def request_row(rid, title, tmdb, tvdb, status_text):
    return {"id": rid, "kind": "tv", "tmdb_id": tmdb, "tvdb_id": tvdb, "title": title, "year": 2026,
            "requested_by": "Ben", "status_text": status_text, "when": "3 days ago", "href": "http://x.invalid",
            "poster": None, "item_key": f"tmdb:{tmdb}"}


def test_requests_page_says_requested_and_waiting_and_how_much_is_to_come(frame_env, sonarr):
    rows = [request_row(1, "Empty Show", 300, 7700, "Available"), request_row(2, "WAR", 400, 8800, "Partly available"),
            request_row(3, "Unknown To Sonarr", 500, 9900, "Approved")]
    main = frame_env(jellyfin={**helpers.JELLY, "server_id": "srv", "shows": SHOWS, "movies": []},
                     jellyseerr={"summary": "x", "requests": rows, "counts": {"approved": 3}})
    sonarr.install()
    with TestClient(main.app) as c:
        cold = main_of(c.get("/media/requests").text)
        warm = main_of(c.get("/media/requests").text)
    assert ">Available</span>" in cold and "Waiting for the first episode" not in cold      # cold: Seerr's words only
    assert ">Available</span>" not in warm
    assert f">Requested</span> · Waiting for the first episode · airs {words(47)} · TV" in warm
    assert f">Partly available</span> · 3 of 8 episodes · 5 to come · next airs {words(5)} · TV" in warm
    assert ">Approved</span> · TV" in warm                                                   # not in Sonarr: unchanged
    assert [c[0] for c in sonarr.calls] == ["/api/v3/series"]
