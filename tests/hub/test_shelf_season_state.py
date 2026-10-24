"""JY-114 (2026-10-24): the Media home's Recently added and Continue watching cards carry Sonarr's season-state word
("3 to come · next airs 2 Nov") on the grid card's own line (`row-meta card-progress`), from the cached series list
only; the page's BackgroundTask re-reads the list after the render. Sonarr is faked at `requests.get`
(tests/hub/test_season_state.py)."""
import re

from fastapi.testclient import TestClient

from hub import media_home
from tests.hub import helpers
from tests.hub.conftest import main_of
from tests.hub.test_media_frame import env as frame_env  # noqa: F401
from tests.hub.test_season_state import NOW, QUIET, WAR, lib_show, season, series, sonarr, words  # noqa: F401

DONE = series(4, "Done Show", [season(1, 6, 6)], tvdb=9100, status="ended")       # complete: no line

JELLY = {**helpers.JELLY, "server_id": "srv", "movies": [],
         "shows": [lib_show("Quiet Show", "tmdb:100", 6, 2, "ser1"), lib_show("Done Show", "tvdb:9100", 6, 0, "ser4")],
         "up_next": [{"title": "Quiet Show · S04E05", "remaining_text": "31 min left", "poster": None, "jf_id": "ep5",
                      "item_key": "jf:ser1", "show_key": "jf:ser1", "season_key": "jf:s4", "episode_key": "jf:ep5"}],
         "latest": [{"title": "Quiet Show - S04E05", "type": "Episode", "item_key": "jf:ser1", "jf_id": "ep5",
                     "poster": None, "added_at": NOW.isoformat()},
                    {"title": "War Film", "type": "Movie", "item_key": "tmdb:400", "jf_id": "film1", "poster": None,
                     "added_at": NOW.isoformat()},          # a film's TMDB id is never looked up in Sonarr (WAR is 400)
                    {"title": "Done Show", "type": "Series", "item_key": "tvdb:9100", "jf_id": "ser4", "poster": None,
                     "added_at": NOW.isoformat()}]}
ARR = {"summary": "x", "arrived": [{"item_key": "tvdb:8800", "kind": "season", "title": "WAR · S01 · 3 episodes",
                                    "when": "3 hours ago", "poster": None}]}


def card(page, title):
    """The one poster card whose title is `title`, inside its shelf section of <main>."""
    hits = [c for c in re.findall(r'<a class="card-poster".*?</a>', page, re.S) if f'class="row-title">{title}<' in c]
    assert len(hits) >= 1, title
    return hits[0]


def section(page, name):
    return page.split(f">{name}", 1)[1].split("</section>", 1)[0]


def test_shelf_cards_carry_the_season_state_once_the_list_is_read(frame_env, sonarr):
    main = frame_env(jellyfin=JELLY, arr=ARR)
    sonarr.install()
    with TestClient(main.app) as c:
        cold = main_of(c.get("/a/alpha").text)
        calls_after_cold = [x[0] for x in sonarr.calls]
        warm = main_of(c.get("/a/alpha").text)
    assert "card-progress" not in cold                                   # cache-only render: nothing on a cold cache
    assert calls_after_cold == ["/api/v3/series"]                        # one list read, after the response
    added = section(warm, "Recently added")
    quiet = f'card-progress">3 to come · next airs {words(3)}</span>'
    assert quiet in card(added, "Quiet Show - S04E05")
    assert f'card-progress">5 to come · next airs {words(5)}</span>' in card(added, "WAR · S01 · 3 episodes")
    assert "card-progress" not in card(added, "War Film")                # films never
    assert "card-progress" not in card(added, "Done Show")               # complete: as before
    cont = card(section(warm, "Continue watching"), "Quiet Show · S04E05")
    assert "31 min left · 2 left" in cont and quiet in cont              # the progress words stay, the line is added
    assert [x[0] for x in sonarr.calls] == ["/api/v3/series"]            # warm: the list is fresh, no new read


def test_no_sonarr_means_no_line_and_no_task(frame_env, sonarr, monkeypatch):
    monkeypatch.delenv("SONARR_URL")
    main = frame_env(jellyfin=JELLY, arr=ARR)
    sonarr.install()
    with TestClient(main.app) as c:
        page = main_of(c.get("/a/alpha").text)
    assert "card-progress" not in page and "Quiet Show - S04E05" in page
    assert sonarr.calls == []


def test_shelf_words_skip_films_and_unknown_rows():
    by_jf = {"ser1": {"item_key": "tmdb:100", "jf_id": "ser1"}}
    keys = media_home.show_keys_of                                       # pure mapping, no Sonarr needed
    assert keys({"type": "Episode", "item_key": "jf:ser1"}, by_jf) == (None, "100")
    assert keys({"show_key": "jf:ser1", "item_key": "jf:ser1"}, by_jf) == (None, "100")
    assert keys({"kind": "season", "item_key": "tvdb:8800"}, by_jf) == ("8800", None)
    assert keys({"type": "Movie", "item_key": "tmdb:400"}, by_jf) is None
    assert keys({"kind": "movie", "item_key": "tmdb:400"}, by_jf) is None
    assert keys({"title": "No type", "item_key": "tmdb:400"}, by_jf) is None
    assert keys({"type": "Episode", "item_key": "jf:unknown"}, by_jf) is None
