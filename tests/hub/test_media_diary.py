"""Watch diary (2026-10-05): sync from Jellyfin history, manual logging, filter,
pagination, search proxy, on-this-day + milestones, and rendering with no DB file."""
import json
from datetime import date, timedelta

import pytest
import requests

from hub import media_db
from tests.hub.conftest import main_raw as main_of  # noqa: F401
from tests.hub.test_media_rate import HX, JELLY, RECENT, env, jelly_data  # noqa: F401

SEARCH = {"results": [
    {"id": 603, "mediaType": "movie", "title": "The Matrix", "releaseDate": "1999-03-30",
     "posterPath": "/matrix.jpg"},
    {"id": 1396, "mediaType": "tv", "name": "Breaking Bad", "firstAirDate": "2008-01-20", "posterPath": None},
    {"id": 6384, "mediaType": "person", "name": "Keanu Reeves"},
]}


def pick(**over):
    return json.dumps({"item_key": "tmdb:603", "kind": "movie", "title": "The Matrix", "year": 1999,
                       "poster": "tmdb:/matrix.jpg", **over})


def log_form(**over):
    return {"pick": pick(), "watched_on": date.today().isoformat(), "place": "Cinema", "note": "", **over}


def test_diary_syncs_jellyfin_history_idempotently_across_gets(env):
    build, _ = env
    with build() as client:
        first = client.get("/media/diary")
        n = len(media_db.list_diary())
        second = client.get("/media/diary")
    assert first.status_code == second.status_code == 200
    assert n == 5 and len(media_db.list_diary()) == n  # two episodes on DIFFERENT days stay two rows
    body = main_of(second.text)
    assert "Quiet Show" in body and "S01E02" not in body    # the diary is per show
    assert "Jellyfin" in body


def test_stats_strip_in_words_and_month_grouping(env):
    build, _ = env
    with build() as client:
        body = main_of(client.get("/media/diary").text)
    assert "this week · " in body and "this month · " in body and "all time · " in body
    assert "-day streak" in body or "no current streak" in body
    assert date.today().strftime("%B %Y") in body or (date.today() - timedelta(days=60)).strftime("%B %Y") in body


def test_place_suggestions_come_from_media_write_places(env):
    """M-05 (W2): the log form's <datalist> is rendered from media_write.PLACES, not a second hand-written list."""
    from hub.media_write import PLACES
    build, _ = env
    with build() as client:
        html = client.get("/media/diary").text
    assert '<datalist id="places">' + "".join(f'<option value="{p}">' for p in PLACES).replace("'", "&#39;") in html


def test_manual_log_appears_month_grouped_with_place(env):
    build, _ = env
    with build() as client:
        resp = client.post("/media/log", data=log_form(), headers=HX)
        assert resp.status_code == 200 and "The Matrix (1999)" in resp.text
        assert "Logged · Cinema" in resp.text and 'class="ratepick"' in resp.text  # unrated: picker
        dup = client.post("/media/log", data=log_form(), headers=HX)
        assert "Already in the diary" in dup.text
        body = main_of(client.get("/media/diary").text)
    month = body.split(f">{date.today().strftime('%B %Y')}</div>", 1)[1]
    assert "The Matrix (1999)" in month and "Film" in month and "Logged · Cinema" in month


def test_log_validation_and_plain_form_redirect(env):
    build, db_file = env
    with build() as client:
        for over in ({"pick": "nonsense"}, {"pick": pick(item_key="bad")}, {"watched_on": "not-a-date"},
                     {"watched_on": (date.today() + timedelta(days=3)).isoformat()}):
            assert client.post("/media/log", data=log_form(**over), headers=HX).status_code == 422
        assert not db_file.exists()
        assert client.post("/media/log", data=log_form(), headers={"Origin": "https://evil.example"}).status_code == 403
        ok = client.post("/media/log", data=log_form(), follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/media/diary"


def test_rated_diary_rows_show_the_chip_unrated_show_a_picker(env):
    build, _ = env
    media_db.add_manual_watch("tmdb:1", "movie", "Heat", watched_on=date.today().isoformat())
    media_db.add_manual_watch("tmdb:2", "movie", "Ronin", watched_on=date.today().isoformat())
    media_db.set_rating("tmdb:1", 10, "movie", "Heat")
    with build(jelly_data([])) as client:
        body = main_of(client.get("/media/diary").text)
    assert 'title="Your rating: 10 out of 10"' in body and "row-poster gold-glow-sm" in body
    assert body.count('class="ratepick"') == 1


def test_filter_chips(env):
    build, _ = env
    media_db.add_manual_watch("tmdb:1", "movie", "Heat", watched_on=date.today().isoformat())
    media_db.add_manual_watch("tmdb:3", "tv", "Severance", watched_on=date.today().isoformat())
    with build(jelly_data([])) as client:
        films = main_of(client.get("/media/diary?kind=movie").text)
        tv = main_of(client.get("/media/diary?kind=tv").text)
        every = main_of(client.get("/media/diary").text)
    assert ">Heat</div>" in films and "Severance" not in films and 'aria-current="true">Films' in films
    assert ">Severance</div>" in tv and ">Heat</div>" not in tv
    assert ">Heat</div>" in every and ">Severance</div>" in every


def test_older_link_pages_fifty_at_a_time(env):
    build, _ = env
    start = date.today() - timedelta(days=200)
    for i in range(55):
        media_db.add_manual_watch(f"tmdb:{i + 1}", "movie", f"Title{i:02d}", watched_on=(start + timedelta(days=i)).isoformat())
    with build(jelly_data([])) as client:
        first = main_of(client.get("/media/diary").text)
        second = main_of(client.get("/media/diary?offset=50").text)
    assert 'href="/media/diary?offset=50">Older' in first and first.count("diaryrow") == 50
    assert "Older</a>" not in second and second.count("diaryrow") == 5


def test_on_this_day_and_milestones_live_on_the_diary_not_history(env):
    build, _ = env
    media_db.add_manual_watch("tmdb:1", "movie", "Heat", watched_on="2025-03-01")
    with build() as client:
        diary = main_of(client.get("/media/diary").text)
        history = main_of(client.get("/media/history").text)
    assert ">On this day</div>" in diary and "Salt Flats" in diary
    assert "Milestones: " in diary and "First watch of 2025: Heat" in diary
    assert "On this day" not in history


def test_diary_renders_with_no_snapshot_and_no_db_file(env):
    build, db_file = env
    with build(jelly_data([])) as client:
        (db_file.parent.parent / "snaps" / "jellyfin.json").unlink()
        resp = client.get("/media/diary")
    assert resp.status_code == 200 and "Nothing in the diary yet" in resp.text
    assert "Jellyfin not connected" in resp.text
    assert not db_file.exists()


def test_diary_tile_and_area_strip_link(env):
    build, _ = env
    with build() as client:
        body = main_of(client.get("/a/alpha").text)
    assert 'href="/media/diary"' in body


def test_search_without_env_says_unavailable(env):
    build, _ = env
    with build() as client:
        resp = client.get("/media/search?q=matrix")
        short = client.get("/media/search?q=m")
    assert "Search unavailable" in resp.text and "Type at least two letters" in short.text


def test_search_returns_movie_and_tv_rows_only(env, monkeypatch):
    build, _ = env
    monkeypatch.setenv("JELLYSEERR_URL", "http://seerr.example.invalid:5055/")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "SEERRSECRETkey")
    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return SEARCH

    def fake_get(url, headers=None, timeout=None, **kw):
        calls.append((url, headers))
        return Resp()

    monkeypatch.setattr(requests, "get", fake_get)
    with build() as client:
        resp = client.get("/media/search?q=the matrix")
    assert calls[0][0] == "http://seerr.example.invalid:5055/api/v1/search?query=the%20matrix"
    assert calls[0][1] == {"X-Api-Key": "SEERRSECRETkey"}
    assert "The Matrix (1999)" in resp.text and "Breaking Bad (2008)" in resp.text
    assert "Keanu" not in resp.text and "SEERRSECRETkey" not in resp.text
    assert "tmdb:603" in resp.text and "tmdb:1396" in resp.text and 'type="radio"' in resp.text


def test_search_failure_is_words_never_the_url_or_key(env, monkeypatch, caplog):
    build, _ = env
    monkeypatch.setenv("JELLYSEERR_URL", "http://seerr.example.invalid:5055")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "SEERRSECRETkey")

    def boom(*a, **kw):
        raise requests.ConnectionError("failed to reach http://seerr.example.invalid:5055 key=SEERRSECRETkey")

    monkeypatch.setattr(requests, "get", boom)
    with build() as client:
        resp = client.get("/media/search?q=matrix")
    assert "Search unavailable" in resp.text
    assert "seerr.example" not in resp.text + caplog.text and "SECRETkey" not in resp.text + caplog.text


# ---- Per-episode diary lines + larger posters (F8, 2026-10-06) ----

from pathlib import Path  # noqa: E402

from tests.hub.test_media_rate import ago  # noqa: E402

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def ep_row(n, days, season=4, show="jf:sh1"):
    return {"title": f"Slow Horses · S{season:02d}E{n:02d} · Name{n}", "kind": "episode", "watched_at": ago(days),
            "when": "x", "poster": "jf:sh1", "item_key": show, "show_key": show, "episode_key": f"jf:ep{season}{n}",
            "season_key": f"jf:ses{season}", "season": season, "episode": n, "show_title": "Slow Horses"}


def test_diary_page_folds_episodes_into_one_line_with_names(env):
    build, _ = env
    with build(jelly_data([ep_row(1, 2), ep_row(2, 2), ep_row(3, 2)])) as client:
        body = main_of(client.get("/media/diary").text)
    assert body.count("diaryrow") == 1
    assert "S4 E1–E3" in body and "Name1 · Name2 · Name3" in body
    assert "↻ rewatch" not in body
    assert "3 episodes this year" in body and "0 films" in body


def test_diary_page_shows_rewatch_chip_and_keeps_owners_apart(env):
    build, _ = env
    media_db.sync_diary_from_history([ep_row(1, 10)])
    with build(jelly_data([ep_row(1, 1)])) as client:
        body = main_of(client.get("/media/diary").text)
    assert "↻ rewatch" in body and "S4 E1" in body
    assert media_db.list_diary(owner="her") == []  # B.'s sync never lands in her diary


def test_poster_sizes_are_pinned_in_css():
    # Restyle Phase 3: rows use the guide's 44 px .row-poster; carousel cards are 116 px, 144 px from 640 px.
    assert ".poster.row-poster { width: 44px;" in CSS
    assert ".carousel > * { flex: 0 0 116px; width: 116px;" in CSS
    assert ".carousel > * { flex-basis: 144px; width: 144px; }" in CSS
