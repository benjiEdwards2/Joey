"""JY-289 (B. 2026-11-02): "I need the poster to change or show more ... For a season, happy for you to remove the
directors for the season. Only leave them in a singular episode." A season page's hero shows the season's own poster
(Jellyfin's Primary image of the season) at the same hero size as the show page, else the show's poster; its
"Directed by" cards are gone. Jellyfin faked (tests/hub/helpers)."""
import copy
import re

from tests.hub import helpers as tmi
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import env, ITEMS  # noqa: F401

SEASON = {"Id": "sea1", "Type": "Season", "Name": "Season 4", "SeriesId": "ser1", "SeriesName": "Quiet Show",
          "IndexNumber": 4, "UserData": {}}


def hero_poster(html):
    return re.search(r'<img class="poster hero-detail-poster[^"]*" src="([^"]+)"', html).group(1)


def with_directors(monkeypatch):
    eps = copy.deepcopy(tmi.EPISODES)
    for e in eps:
        e["People"] = [{"Name": "Dir A", "Type": "Director"}]
    monkeypatch.setattr(tmi, "EPISODES", eps)


def test_season_page_shows_the_seasons_own_poster_at_the_show_pages_hero_size(env, monkeypatch):
    monkeypatch.setitem(ITEMS, "sea1", {**SEASON, "ImageTags": {"Primary": "p1"}})
    client, _ = env()
    with client:
        season = client.get("/media/item/sea1").text
        show = client.get("/media/item/ser1").text
    assert hero_poster(season).startswith("/img/jf:sea1?h=600")
    assert hero_poster(show).startswith("/img/jf:ser1?h=600")                    # same macro, same size, same class
    cls = re.compile(r'<img class="(poster hero-detail-poster[^"]*)"')
    assert cls.search(season).group(1) == cls.search(show).group(1)


def test_season_page_without_its_own_poster_falls_back_to_the_shows(env, monkeypatch):
    monkeypatch.setitem(ITEMS, "sea1", dict(SEASON))
    client, _ = env()
    with client:
        assert hero_poster(client.get("/media/item/sea1").text).startswith("/img/jf:ser1?h=600")


def test_directors_stay_on_the_show_and_episode_pages_but_leave_the_season_page(env, monkeypatch):
    monkeypatch.setitem(ITEMS, "sea1", dict(SEASON))
    with_directors(monkeypatch)
    client, _ = env()
    with client:
        season = main_of(client.get("/media/item/sea1").text)
        show = main_of(client.get("/media/item/ser1").text)
    assert "makers-directors" not in season
    assert "makers-directors" in show
