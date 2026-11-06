"""JY-288 (B., 2026-11-02: "Can you average the rated season votings and show them as you would with movies. It would be
nice to see my highest ratings first."): a show's score is the mean of your rated seasons (else your rated episodes),
shown where a film shows its score - the show page's Scores card ("Yours 8.5 avg"), the TV hero's facts line and the
My shows tiles / rows, which already sort by your score, highest first. Your own whole-show rating wins."""
import re

from fastapi.testclient import TestClient

from hub import media_db
from tests.hub.film_page import whole
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import env  # noqa: F401
from tests.hub.test_media_library_pages import body, jelly, row_titles, ARRV
from tests.hub.test_media_library_pages import env as lib_env  # noqa: F401
from tests.hub.test_tv_series_episodes import tvc  # noqa: F401
from tests.hub.test_tv_p3_jy259 import tv_whole
from tests.hub.fake_jellyfin import FRIEND_ID


def _rate(key, score, title, level, owner="you"):
    media_db.set_rating(key, score, "tv", title, owner=owner, level=level)


# ---- the rule ----

def test_mean_of_rated_seasons_one_decimal(lib_env):
    lib_env(jellyfin=jelly())
    _rate("jf:s1", 8, "Echo Show · Season 1", "season")
    _rate("jf:s2", 9, "Echo Show · Season 2", "season")
    _rate("jf:e1", 2, "Echo Show · S01E01 · Pilot", "episode")      # seasons rated: episodes are not counted
    _rate("jf:s9", 3, "Echo Show · Season 1", "season", owner="her")   # another owner's never counts
    assert media_db.show_averages([("tmdb:21", "Echo Show")]) == {"tmdb:21": 8.5}


def test_episodes_when_no_season_is_rated(lib_env):
    lib_env(jellyfin=jelly())
    for i, s in enumerate((7, 8, 8), 1):
        _rate(f"jf:e{i}", s, f"Golf Show · S01E0{i} · Ep {i}", "episode")
    assert media_db.show_averages([("tmdb:23", "Golf Show")]) == {"tmdb:23": 7.7}


def test_title_with_a_dot_and_no_match(lib_env):
    lib_env(jellyfin=jelly())
    _rate("jf:a", 6, "A · B · Season 1", "season")
    _rate("jf:b", 10, "A · Season 1", "season")
    got = media_db.show_averages([("k1", "A · B"), ("k2", "A"), ("k3", "Nothing")])
    assert got == {"k1": 6.0, "k2": 10.0}
    assert media_db.show_averages([]) == {}


# ---- My shows: the score on the tile and row, highest first ----

def test_my_shows_show_the_average_and_sort_highest_first(lib_env):
    main = lib_env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _rate("jf:s1", 6, "Echo Show · Season 1", "season")
        _rate("jf:s2", 7, "Echo Show · Season 2", "season")       # Echo 6.5
        _rate("jf:e1", 9, "Golf Show · S01E01 · One", "episode")    # Golf 9 (episodes only)
        assert row_titles(body(c, "/media/tv?view=list")[1]) == ["Golf Show", "Echo Show", "Foxtrot Show"]
        b = body(c, "/media/tv?view=list")[1]
        assert 'class="row-score score-6" title="Your rating: 6.5 out of 10">6.5<' in b
        g = body(c, "/media/tv?view=grid")[1]
        assert re.search(r'class="poster-score score-9"[^>]*>9<', g) and ">6.5<" in g


def test_a_whole_show_rating_wins_over_the_average(lib_env):
    main = lib_env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _rate("jf:s1", 4, "Echo Show · Season 1", "season")
        _rate("jf:jtmdb-21", 10, "Echo Show", "show")      # the show page's key (jf:<series id>)
        b = body(c, "/media/tv?view=list")[1]
        assert row_titles(b)[0] == "Echo Show" and "Your rating: 10 out of 10" in b and ">4<" not in b


# ---- the show page ----

def test_show_page_scores_card_says_yours_avg(env):
    client, _ = env()
    with client:
        _rate("jf:sea1", 8, "Quiet Show · Season 4", "season")
        _rate("jf:sea0", 9, "Quiet Show · Season 3", "season")
        b = main_of(whole(client, "/media/item/ser1"))
    pill = b.split('class="scorepill sp-you"', 1)[1].split("</a>", 1)[0]
    assert ">8.5<" in pill and ">avg<" in pill and "score-8" in pill
    assert "Rated 8.5" not in b      # the hero button still offers Rate for the whole show


def test_show_page_own_rating_beats_avg_and_season_page_has_none(env):
    client, _ = env()
    with client:
        _rate("jf:sea1", 4, "Quiet Show · Season 4", "season")
        _rate("jf:ser1", 9, "Quiet Show", "show")
        b = main_of(whole(client, "/media/item/ser1"))
        assert ">avg<" not in b and "Your rating: 9 out of 10" in b
        s = main_of(whole(client, "/media/item/sea1"))
    # JY-316 d (2026-11-06): a season page still never shows the SHOW mean; its own pill is the season's episode mean
    # (media_db.season_average), none here as no episode of the season is rated (tests/hub/test_season_page_jy316.py)
    assert ">avg<" not in s


def test_tv_hero_facts_say_yours_avg(tvc):
    owner = f"jf:{FRIEND_ID}"
    _rate("jf:x1", 7, "Sample Show · Season 1", "season", owner=owner)
    _rate("jf:x2", 8, "Sample Show · Season 2", "season", owner=owner)
    from tests.hub.test_tv_series_episodes import SHOW
    html = tv_whole(tvc, f"/media/item/{SHOW}")
    facts = re.search(r'<div class="facts-line tv-facts">(.*?)</div>', html, flags=re.S)
    assert facts and "Yours 7.5 avg" in facts.group(1)
