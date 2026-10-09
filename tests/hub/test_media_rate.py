"""Ratings (2026-10-05) — the rate inbox on /media/history, the write routes with their
same-origin guard, undo, and score chips on every media page. media.db lives in tmp_path;
the hub must also render with NO db file at all."""
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from hub import media_db
from tests.hub.helpers import make_area, make_tile, write_envelope
from tests.hub.conftest import main_raw as main_of

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
JELLY = json.loads((SAMPLES / "jellyfin.json").read_text(encoding="utf-8"))["data"]
ARR = json.loads((SAMPLES / "arr.json").read_text(encoding="utf-8"))["data"]
SEERR = json.loads((SAMPLES / "jellyseerr.json").read_text(encoding="utf-8"))["data"]
HX = {"HX-Request": "true"}


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def recent_row(key, title, days, kind="movie"):
    return {"title": title, "kind": kind, "watched_at": ago(days), "when": f"{days} days ago",
            "poster": "jf:p-" + key.split(":")[1], "item_key": key}


RECENT = [
    recent_row("tmdb:1", "Heat", 1),
    recent_row("jf:s1", "Quiet Show · S01E02 · B", 2, "episode"),
    recent_row("jf:s1", "Quiet Show · S01E01 · A", 3, "episode"),   # same show: one inbox row
    recent_row("tmdb:4", "Already Rated", 4),
    recent_row("tmdb:9", "Long Ago", 60),                            # outside the 30-day window
]


def jelly_data(recent=RECENT):
    return {**JELLY, "history": {**JELLY["history"], "recent": recent}}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["tiles"] += [
        make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/history", owner="you"),
        make_tile("diary-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/diary", owner="you"),
        make_tile("lib-t", snapshot="arr", stale_after_minutes=180, detail="/media/library"),
        make_tile("req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests"),
    ]
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "data" / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    for name in ("JELLYSEERR_URL", "JELLYSEERR_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def build(jelly=None, arr=ARR, seerr=SEERR):
        write_envelope(snaps, "jellyfin", age_minutes=1, data=jelly or jelly_data())
        write_envelope(snaps, "arr", age_minutes=1, data=arr)
        write_envelope(snaps, "jellyseerr", age_minutes=1, data=seerr)
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build, tmp_path / "data" / "media.db"


def rate_form(key="tmdb:1", score=8, **over):
    return {"item_key": key, "score": str(score), "kind": "movie", "title": "Heat", "year": "1995",
            "poster": "jf:p-1", **over}


def test_inbox_lists_unrated_recent_titles_once_each(env):
    build, db_file = env
    media_db.set_rating("tmdb:4", 7, "movie", "Already Rated")
    with build() as client:
        body = main_of(client.get("/media/history").text)
    inbox = body.split(">To rate</div>", 1)[1].split(">Recently watched</div>", 1)[0]
    assert inbox.count('class="ratepick"') == 2           # Heat + the show, once
    assert "Heat" in inbox and "Quiet Show" in inbox and "S01E02" not in inbox
    assert "Already Rated" not in inbox and "Long Ago" not in inbox
    assert 'hx-post="/media/rate"' in inbox and 'name="score" value="10"' in inbox
    assert 'name="item_key" value="jf:s1"' in inbox


def test_inbox_empty_word_and_no_db_file_needed(env):
    build, db_file = env
    with build(jelly_data([])) as client:
        resp = client.get("/media/history")
    assert resp.status_code == 200 and "Nothing waiting to be rated" in resp.text
    assert not db_file.exists()  # reading never creates it


def test_htmx_rate_returns_the_rated_partial_and_persists(env):
    build, db_file = env
    with build() as client:
        resp = client.post("/media/rate", data=rate_form(score=10), headers=HX)
    assert resp.status_code == 200
    assert 'class="stat-number score-9 gold-text-glow"' in resp.text and ">10<" in resp.text
    assert 'hx-delete="/media/rate/tmdb%3A1"' in resp.text and "undo" in resp.text
    assert "<html" not in resp.text  # a partial, not a page
    assert media_db.get_ratings(["tmdb:1"]) == {"tmdb:1": 10}


def test_plain_form_post_redirects_to_history(env):
    build, _ = env
    with build() as client:
        resp = client.post("/media/rate", data=rate_form(score=6), follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/media/history"
    assert media_db.get_ratings(["tmdb:1"]) == {"tmdb:1": 6}


def test_origin_guard(env):
    build, _ = env
    with build() as client:
        bad = client.post("/media/rate", data=rate_form(), headers={"Origin": "https://evil.example"})
        same = client.post("/media/rate", data=rate_form(), headers={"Origin": "http://testserver"},
                           follow_redirects=False)
        htmx_cross = client.post("/media/rate", data=rate_form(score=3),
                                 headers={"Origin": "https://evil.example", **HX})
    assert bad.status_code == 403
    assert same.status_code == 303
    assert htmx_cross.status_code == 200  # the htmx header can't be sent cross-site
    d = client.delete("/media/rate/tmdb:1", headers={"Origin": "https://evil.example"})
    assert d.status_code == 403 and media_db.get_ratings(["tmdb:1"]) == {"tmdb:1": 3}


@pytest.mark.parametrize("over", [{"score": "0"}, {"score": "11"}, {"score": "x"}, {"score": ""},
                                  {"item_key": "nope:1"}, {"item_key": "tmdb:1;drop"}, {"title": ""}])
def test_invalid_input_is_422_and_saves_nothing(env, over):
    build, db_file = env
    with build() as client:
        resp = client.post("/media/rate", data=rate_form(**over), headers=HX)
    assert resp.status_code == 422 and not db_file.exists()


def test_poster_ref_is_validated_not_trusted(env):
    build, _ = env
    with build() as client:
        client.post("/media/rate", data=rate_form(poster="http://evil.example/x.jpg"), headers=HX)
    assert media_db.get_rating("tmdb:1")["poster"] is None


def test_undo_deletes_and_restores_the_picker(env):
    build, _ = env
    media_db.set_rating("tmdb:1", 8, "movie", "Heat", 1995, "jf:p-1")
    with build() as client:
        resp = client.delete("/media/rate/tmdb:1", headers=HX)
        assert resp.status_code == 200 and 'class="ratepick"' in resp.text
        assert 'name="title" value="Heat"' in resp.text
        assert media_db.get_ratings(["tmdb:1"]) == {}
        assert client.delete("/media/rate/tmdb:1", headers=HX).status_code == 200  # nothing left: still fine
        media_db.set_rating("tmdb:1", 5, "movie", "Heat")
        back = client.post("/media/rate/tmdb:1/delete", follow_redirects=False)
    assert back.status_code == 303 and media_db.get_ratings(["tmdb:1"]) == {}


def test_unwritable_db_is_a_503_not_a_crash(env, monkeypatch, tmp_path):
    build, _ = env
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("MEDIA_DB_PATH", str(blocker / "media.db"))  # parent is a file
    with build() as client:
        assert client.post("/media/rate", data=rate_form(), headers=HX).status_code == 503


def test_score_chips_on_history_playing_library_requests_and_the_area(env):
    build, _ = env
    keys = {"hist": "tmdb:1", "play": JELLY["now_playing"][0]["item_key"],
            "lib": ARR["arrived"][0]["item_key"], "req": SEERR["requests"][0]["item_key"]}
    media_db.set_rating(keys["hist"], 8, "movie", "Heat")
    media_db.set_rating(keys["play"], 10, "movie", "Playing")
    media_db.set_rating(keys["lib"], 5, "movie", "Arrived")
    media_db.set_rating(keys["req"], 3, "movie", "Requested")
    with build() as client:
        hist = main_of(client.get("/media/history").text)
        play = main_of(client.get("/media/playing").text)
        lib = main_of(client.get("/media/library").text)
        req = main_of(client.get("/media/requests").text)
        area = main_of(client.get("/a/alpha").text)
    recent = hist.split(">Recently watched</div>", 1)[1]
    assert 'row-score score-8" title="Your rating: 8 out of 10">8<' in recent
    assert 'row-score score-9 gold-text-glow"' in play and "row-poster gold-glow-sm" in play
    assert 'row-score score-5" title="Your rating: 5 out of 10">5<' in lib
    assert 'row-score score-3" title="Your rating: 3 out of 10">3<' in req
    assert 'title="Your rating: 10 out of 10"' in area and "gold-glow" in area


def test_her_view_sees_no_scores_or_inbox(env):
    build, _ = env
    media_db.set_rating(JELLY["now_playing"][0]["item_key"], 9, "movie", "Playing")
    with build() as client:
        play = main_of(client.get("/media/playing?owner_view=her").text)
    assert "Your rating" not in play


def test_pages_render_with_no_db_file(env):
    build, db_file = env
    with build() as client:
        for url in ("/media/history", "/media/playing", "/media/library", "/media/requests", "/a/alpha"):
            assert client.get(url).status_code == 200, url
    assert not db_file.exists()


# ---- Rating level: Show / Season / Episode (2026-10-06) ----

def tv_row(show, season_id, season, ep_id, ep, title, days):
    return {"title": f"Colin from Accounts · S{season:02d}E{ep:02d} · {title}", "kind": "episode",
            "watched_at": ago(days), "when": f"{days} days ago", "poster": "jf:p-" + show,
            "item_key": f"jf:{show}", "show_key": f"jf:{show}", "season_key": f"jf:{season_id}",
            "episode_key": f"jf:{ep_id}", "season": season, "episode": ep,
            "show_title": "Colin from Accounts", "jf_id": ep_id}


TV = [
    tv_row("cfa", "cfas1", 1, "cfae8", 8, "High Needs People", 1),
    tv_row("cfa", "cfas1", 1, "cfae7", 7, "Other", 2),
    tv_row("cfa", "cfas2", 2, "cfae9", 1, "Again", 3),
    recent_row("tmdb:1", "Heat", 4),
]


def inbox_of(html):
    return main_of(html).split(">To rate</div>", 1)[1].split(">Recently watched</div>", 1)[0]


@pytest.mark.parametrize("level, count, titles, key", [
    ("show", 2, ["Colin from Accounts<"], "jf:cfa"),
    ("season", 3, ["Colin from Accounts · Season 1<", "Colin from Accounts · Season 2<"], "jf:cfas1"),
    ("episode", 4, ["Colin from Accounts · S01E08 · High Needs People<"], "jf:cfae8"),
])
def test_inbox_at_each_level_counts_titles_and_keys(env, level, count, titles, key):
    build, db_file = env
    media_db.set_setting("you", "rating_level", level)
    with build(jelly_data(TV)) as client:
        inbox = inbox_of(client.get("/media/history").text)
    assert inbox.count('class="ratepick"') == count
    assert all(t in inbox for t in titles) and f'name="item_key" value="{key}"' in inbox
    assert f'name="level" value="{level}"' in inbox and "Heat" in inbox


def test_inbox_skips_what_is_already_rated_at_the_level(env):
    build, db_file = env
    media_db.set_setting("you", "rating_level", "season")
    media_db.set_rating("jf:cfas1", 7, "tv", "x", level="season")
    with build(jelly_data(TV)) as client:
        inbox = inbox_of(client.get("/media/history").text)
    assert "Season 1<" not in inbox and "Season 2<" in inbox


def test_level_chips_mark_the_active_one_and_post_sets_it(env):
    build, db_file = env
    with build(jelly_data(TV)) as client:
        html = main_of(client.get("/media/history").text)
        assert 'value="show" class="chip on" aria-current="true"' in html
        resp = client.post("/media/settings/rating_level", data={"value": "episode"}, follow_redirects=False)
        assert resp.status_code == 303 and resp.headers["location"] == "/media/history"
        html = main_of(client.get("/media/history").text)
        assert 'value="episode" class="chip on" aria-current="true"' in html
        assert 'value="show" class="chip"' in html
    assert media_db.rating_level("you") == "episode"


def test_level_post_refuses_foreign_origin_and_bad_values(env):
    build, db_file = env
    with build(jelly_data(TV)) as client:
        assert client.post("/media/settings/rating_level", data={"value": "season"},
                           headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/media/settings/rating_level", data={"value": "nope"}).status_code == 422
    assert media_db.rating_level("you") == "show"


def test_rate_post_at_season_level_stores_level_under_the_season_key(env):
    build, db_file = env
    with build(jelly_data(TV)) as client:
        resp = client.post("/media/rate", data=rate_form("jf:cfas1", 9, kind="tv", level="season",
                                                        title="Colin from Accounts · Season 1"), headers=HX)
        assert resp.status_code == 200
        assert client.post("/media/rate", data=rate_form("jf:x1", 5, level="weird"), headers=HX).status_code == 422
    row = media_db.get_rating("jf:cfas1")
    assert row["score"] == 9 and row["level"] == "season"
    assert media_db.get_rating("jf:cfa") is None


def test_show_score_stays_on_shelf_rows_while_episode_score_wins_on_an_episode_row(env):
    build, db_file = env
    media_db.set_rating("jf:cfa", 6, "tv", "Colin from Accounts")
    with build(jelly_data(TV)) as client:
        show_level = main_of(client.get("/media/history").text)
        media_db.set_setting("you", "rating_level", "episode")
        media_db.set_rating("jf:cfae8", 9, "tv", "Colin ep", level="episode")
        ep_level = main_of(client.get("/media/history").text)

    def recent(h):
        return h.split(">Recently watched</div>", 1)[1].split(">Most played shows</div>", 1)[0]
    assert recent(show_level).count('title="Your rating: 6 out of 10"') == 3  # each episode row shows the show score
    r = recent(ep_level)
    assert r.count('title="Your rating: 9 out of 10"') == 1 and r.count('title="Your rating: 6 out of 10"') == 2


# ---- 2026-10-06 regression: to-rate titles rendered one character per line ----
CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def test_to_rate_rows_wrap_so_the_title_keeps_its_width(env):
    build, db_file = env
    with build() as client:
        body = main_of(client.get("/media/history").text)
    inbox = body.split(">To rate</div>", 1)[1].split(">Recently watched</div>", 1)[0]
    rows = inbox.split('<div class="row has-form">')[1:]
    assert len(rows) == 3
    assert all('class="ratepick"' in r for r in rows)
    flat = " ".join(CSS.split())
    # Restyle Phase 3: the row recipe wraps, the title block keeps the width, the picker takes its own line.
    assert ".row.has-form { position: relative; flex-wrap: wrap; }" in flat
    assert ".row-body { flex: 1 1 auto; min-width: 0; }" in flat
    assert ".row .ratepick, .row .rated { flex: 0 0 100%;" in flat


def test_diary_rows_with_a_picker_wrap_too():
    tpl = (Path(__file__).resolve().parents[2] / "hub" / "templates" / "_diary_row.html").read_text(encoding="utf-8")
    assert 'class="row has-form diaryrow"' in tpl
