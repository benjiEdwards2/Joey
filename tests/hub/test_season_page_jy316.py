"""JY-316 (B. 2026-11-04, Plan 2 phase 2.3: "Only the chips. No need for that view."): the season page says where you
are in words ("3 of 6 watched · next S4 E4"), keeps Mark season watched (owner "you" only), lists this season's
actors first, and its Rate / "Yours" / score pills are the season's. Jellyfin faked (tests/hub/helpers); no network."""
import copy
import re

import pytest

from hub import media_db, media_film
from tests.hub import helpers as tmi
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.helpers import env, ITEMS, EPISODES  # noqa: F401
from tests.hub.test_tv_p3_jy259 import tv_whole
from tests.hub.test_tv_series_episodes import tvc  # noqa: F401

SEASON = {"Id": "sea1", "Type": "Season", "Name": "Season 4", "SeriesId": "ser1", "SeriesName": "Quiet Show",
          "IndexNumber": 4, "UserData": {}}
CAST = ["Cast Alpha", "Cast Bravo", "Cast Charlie", "Cast Delta", "Cast Echo"]


@pytest.fixture()
def season(monkeypatch):
    monkeypatch.setitem(ITEMS, "sea1", dict(SEASON))


def flat(html):
    return re.sub(r"<[^>]+>", " ", html.replace('<span class="sep"> · </span>', " · "))


def with_cast(monkeypatch, in_season):
    """The show lists all five actors; this season's episodes name only `in_season` of them."""
    show = copy.deepcopy(ITEMS["ser1"])
    show["People"] = [{"Name": n, "Type": "Actor", "Role": "Role"} for n in CAST]
    monkeypatch.setitem(ITEMS, "ser1", show)
    eps = copy.deepcopy(EPISODES)
    for e in eps:
        e["People"] = [{"Name": n, "Type": "Actor"} for n in in_season]
    monkeypatch.setattr(tmi, "EPISODES", eps)


# ---- a. progress in words ----

def test_head_line_names_the_next_unwatched_episode(env, season):
    client, _ = env()
    with client:
        b = flat(client.get("/media/item/sea1").text)
        show = flat(client.get("/media/item/ser1").text)
    assert re.search(r"3 of 6 watched\s*·\s*next S4 E4", b)          # E4 is part-watched
    assert re.search(r"3 of 6 watched\s*·\s*next S4 E4", show)       # same row on the show page


def test_head_line_has_no_next_when_every_aired_episode_is_watched(env, season, monkeypatch):
    monkeypatch.setattr(tmi, "EPISODES", [tmi.ep(1, "One", True), tmi.ep(2, "Two", True),
                                          tmi.ep(3, "Three", premiere=tmi.TOMORROW)])
    client, _ = env()
    with client:
        b = flat(client.get("/media/item/sea1").text)
    assert "2 of 3 watched" in b and "next S" not in b


def test_next_code_is_per_season_card():
    s = [{"n": 1, "id": "a", "episodes": [{"number": 1, "aired": True, "played": True, "jf_id": "x", "name": "A"}]},
         {"n": 2, "id": "b", "episodes": [{"number": 1, "aired": True, "played": True, "jf_id": "y", "name": "B"},
                                          {"number": 2, "aired": True, "played": False, "jf_id": "z", "name": "C"}]}]
    s[0]["name"], s[1]["name"] = "Season 1", "Season 2"
    cards = media_film.tv_shelves(s, 2)["seasons"]
    assert [c["next_code"] for c in cards] == [None, "S2 E2"]


# ---- b. Mark season watched: tests/hub/test_media_watched.py (season page, owner "you" only) ----


# ---- c. season cast ----

def cast_names(html):
    sec = html.split('class="sec castsec', 1)[1].split("</section>", 1)[0] if 'class="sec castsec' in html else ""
    return [n for n in CAST if n in sec]


def test_season_cast_lists_this_seasons_actors_and_drops_the_rest(env, season, monkeypatch):
    with_cast(monkeypatch, CAST[:3])
    client, _ = env()
    with client:
        sea = client.get("/media/item/sea1").text
        ser = client.get("/media/item/ser1").text
    assert cast_names(sea) == CAST[:3]
    assert cast_names(ser) == CAST                                   # the show page keeps the whole cast


def test_season_cast_falls_back_to_the_show_cast_under_three_matches(env, season, monkeypatch):
    with_cast(monkeypatch, CAST[3:])
    client, _ = env()
    with client:
        sea = client.get("/media/item/sea1").text
    assert cast_names(sea) == CAST


def test_season_cast_filter_is_pure():
    cast = [{"name": n} for n in CAST]
    assert media_film.season_cast(cast, None) is cast
    assert [c["name"] for c in media_film.season_cast(cast, set(CAST[1:4]))] == CAST[1:4]
    assert media_film.season_cast(cast, set(CAST[:2])) is cast


# ---- d. season scores ----

def test_rate_on_a_season_page_is_the_seasons_rating(env, season):
    client, _ = env()
    with client:
        media_db.set_rating("jf:sea1", 8, "tv", "Quiet Show · Season 4", owner="you", level="season")
        sea = main_of(client.get("/media/item/sea1").text)
        ser = main_of(client.get("/media/item/ser1").text)
    assert 'action="/media/rate/jf%3Asea1/delete"' in sea and "Your rating: 8 out of 10" in sea
    assert "/media/rate/jf%3Asea1/" not in ser and "Your rating: 8 out of 10" not in ser


def test_unrated_season_shows_the_episode_mean_and_the_imdb_season_mean(env, season, monkeypatch):
    for i, s in ((1, 8), (2, 9)):
        media_db.set_rating(f"jf:e{i}", s, "tv", f"Quiet Show · S04E0{i} · Ep", owner="you", level="episode")
    media_db.set_rating("jf:x", 2, "tv", "Quiet Show · S03E01 · Old", owner="you", level="episode")   # another season
    media_db.set_rating("jf:y", 1, "tv", "Quiet Show · S04E01 · Her", owner="her", level="episode")   # another owner
    monkeypatch.setattr(media_film.media_episode_ratings, "build_ratings",
                        lambda *a, **k: ({"seasons": [{"n": 4, "year": 2025, "avg": 8.2, "votes": 9, "seen": 3,
                                                        "total": 5, "aired": 5, "eps": []}],
                                          "current": 4, "episode": None}, None))
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/sea1").text)
    pill = b.split('class="scorepill sp-you"', 1)[1].split("</a>", 1)[0]
    assert ">8.5<" in pill and ">avg<" in pill and "Your episodes average" in pill
    assert "8.2 avg" in b and "IMDb season" in b


def test_season_average_rule(env):
    client, _ = env()
    with client:
        assert media_db.season_average("Quiet Show", 4) is None
        for i, s in enumerate((7, 8, 8), 1):
            media_db.set_rating(f"jf:e{i}", s, "tv", f"Quiet Show · S04E0{i} · Ep", owner="you", level="episode")
        assert media_db.season_average("Quiet Show", 4) == 7.7
        assert media_db.season_average("Quiet Show", 5) is None
        assert media_db.season_average("Other", 4) is None


# ---- TV page: no new web blocks ----

def test_tv_season_page_has_no_progress_words_or_score_pills(tvc):
    from tests.hub.test_tv_series_episodes import S1
    media_db.set_rating("jf:e1", 8, "tv", "Sample Show · S01E01 · Ep", owner="jf:" + FRIEND_ID, level="episode")
    html = tv_whole(tvc, f"/media/item/{S1}")
    assert "tl-epsub" not in html and "tl-seasonacts" not in html and "Your episodes average" not in html
    assert "tv-eps" in html                                          # the TV still draws its own Episodes row


def test_show_page_with_rate_tv_by_season_has_no_season_pills(env, monkeypatch):
    """Review fix (2026-11-06): the IMDb season pill and "Your episodes average" are season-PAGE words, not a rating-level word."""
    media_db.set_setting("you", "rating_level", "season")
    media_db.set_rating("jf:e1", 8, "tv", "Quiet Show · S04E01 · Ep", owner="you", level="episode")
    monkeypatch.setattr(media_film.media_episode_ratings, "build_ratings",
                        lambda *a, **k: ({"seasons": [{"n": 4, "year": 2025, "avg": 8.2, "votes": 9, "seen": 3,
                                                        "total": 5, "aired": 5, "eps": []}],
                                          "current": 4, "episode": None}, None))
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    assert "IMDb season" not in b and "Your episodes average" not in b and "8.2 avg" not in b


def test_season_names_use_the_seasons_id_not_its_number():
    seasons = [{"id": "a", "number": None, "episodes": [{"people_names": ["A"]}]},
               {"id": "b", "number": 2, "episodes": [{"people_names": ["B"]}]}]
    item = {"kind": "season", "id": "a", "season_no": 2}
    assert media_film.season_names(item, seasons) == {"A"}


# ---- round 2 (B. 2026-11-06, Sweep 34): one seasons row (the chips), the episodes under it, 2:3 cast ----

def test_round2_season_chips_are_the_one_seasons_row_with_episodes_under(env, season, monkeypatch):
    with_cast(monkeypatch, CAST[:3])
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/sea1").text)
    assert b.count('<nav class="tl-chips" aria-label="Seasons">') == 1 and "seasonseg" not in b
    assert b.index('class="tl-chips"') < b.index('class="tl-track"')
    assert 'class="sec castsec casttiles"' in b
