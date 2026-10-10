"""TV directors (2026-10-10): TMDB's show-level crew has no directors, so a TV page's Director / Writer rows come
from Jellyfin — the episode's own People on an episode page, everyone who directed / wrote an episode on a show page."""
import copy
import re

from hub import media_film
from tests.hub import helpers as tmi
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import env  # noqa: F401


def crew(body):
    return {dt: re.findall(r">([^<]+)</a>", dd)
            for dt, dd in re.findall(r'<div class="kv"><dt>([^<]+)</dt><dd>(.*?)</dd></div>',
                                     re.findall(r'<dl class="crewgrid">.*?</dl>', body, re.S)[0])}


def test_episode_and_show_pages_name_their_directors(env, monkeypatch):
    items = copy.deepcopy(tmi.ITEMS)   # 35 guest stars first: the 30-person cap must not cut the crew
    items["ep3"]["People"] = [{"Name": f"Guest {i}", "Type": "GuestStar"} for i in range(35)] + [
        {"Name": "Eppy Director", "Type": "Director"}, {"Name": "Eppy Writer", "Type": "Writer"}]
    monkeypatch.setattr(tmi, "ITEMS", items)
    eps = copy.deepcopy(tmi.EPISODES)
    for i, e in enumerate(eps):
        e["People"] = [{"Name": "Dir B" if i < 2 else "Dir A", "Type": "Director"}, {"Name": "X", "Type": "GuestStar"}]
    monkeypatch.setattr(tmi, "EPISODES", eps)
    client, _ = env()
    with client:
        ep_page = main_of(client.get("/media/item/ep3").text)
        show_page = main_of(client.get("/media/item/ser1").text)
    assert crew(ep_page)["Director"] == ["Eppy Director"] and crew(ep_page)["Writer"] == ["Eppy Writer"]
    assert crew(show_page)["Director"] == ["Dir A", "Dir B"]          # most episodes first
    assert "Writer" not in crew(show_page)


def test_show_crew_prefers_the_series_own_people():
    item = {"people": [{"name": "Series Dir", "type": "Director"}, {"name": "A", "type": "Actor"}]}
    seasons = [{"episodes": [{"crew": [{"name": "Ep Dir", "type": "Director"}]}]}]
    assert media_film.show_crew(item, seasons) == [{"name": "Series Dir", "type": "Director"}]
    assert media_film.show_crew({"people": []}, seasons) == [{"name": "Ep Dir", "type": "Director"}]
    assert media_film.show_crew(None, []) == []
