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
    # TV episode flow (2026-10-16): an episode page's Crew block is its own rows ("Directed by" / "Written by"); the
    # show-level Director / Writer block is skipped there so the names never appear twice
    assert crew(ep_page)["Directed by"] == ["Eppy Director"] and crew(ep_page)["Written by"] == ["Eppy Writer"]
    assert "<dt>Director</dt>" not in ep_page
    assert crew(show_page)["Director"] == ["Dir A", "Dir B"]          # most episodes first
    assert "Writer" not in crew(show_page)


def makers(body, label):
    """The headshot-card names under one hero microlabel ("Created by" / "Directed by"), in order."""
    block = re.search(r'<div class="microlabel">' + re.escape(label) + r'</div>\s*<div class="makerrow">(.*?)</div>', body, re.S)
    return re.findall(r'<span class="makername">([^<]+)</span>', block.group(1)) if block else None


def test_show_page_has_directed_by_cards_like_a_film(env, monkeypatch):
    """2026-10-11: a show page gets a second card row, "Directed by", with the directors of the most episodes first,
    a Jellyfin headshot when the person has one, and a Discover-search link (no TMDB person id). An episode page
    keeps only the Crew row; the film page is unchanged."""
    eps = copy.deepcopy(tmi.EPISODES)
    for i, e in enumerate(eps):
        e["People"] = [{"Name": "Dir B" if i < 2 else "Dir A", "Type": "Director",
                        **({"Id": "person-a", "PrimaryImageTag": "t1"} if i >= 2 else {})},
                       {"Name": "X", "Type": "GuestStar"}]
    monkeypatch.setattr(tmi, "EPISODES", eps)
    client, _ = env()
    with client:
        show_page = main_of(client.get("/media/item/ser1").text)
        ep_page = main_of(client.get("/media/item/ep3").text)
        film_page = main_of(client.get("/media/item/mov1").text)
    assert makers(show_page, "Directed by") == ["Dir A", "Dir B"]       # most episodes first
    assert 'class="makers makers-directors"' in show_page
    assert 'src="/img/jf:person-a?h=' in show_page                          # Dir A's Jellyfin headshot
    assert 'href="/media/person/find?name=Dir%20A"' in show_page                  # no TMDB person id → person-find link
    assert makers(ep_page, "Directed by") is None and "makers-directors" not in ep_page
    assert "makers-directors" not in film_page and makers(film_page, "Directed by")   # the film's own row stays


def test_show_directors_rank_and_refs():
    seasons = [{"episodes": [{"crew": [{"name": "Ep Dir", "type": "Director", "ref": None}]},
                             {"crew": [{"name": "Ep Dir", "type": "Director", "ref": "jf:p1"}]},
                             {"crew": [{"name": "Other", "type": "Director", "ref": None},
                                       {"name": "W", "type": "Writer", "ref": "jf:w"}]}]}]
    assert media_film.show_directors(None, seasons) == [{"name": "Ep Dir", "id": None, "ref": "jf:p1"},
                                                        {"name": "Other", "id": None, "ref": None}]
    own = {"people": [{"name": "Series Dir", "type": "Director", "ref": "jf:s"}]}
    assert [d["name"] for d in media_film.show_directors(own, seasons)] == ["Series Dir", "Ep Dir", "Other"]
    assert media_film.show_directors(None, []) == []
    many = [{"episodes": [{"crew": [{"name": f"D{i}", "type": "Director"}]} for i in range(9)]}]
    assert len(media_film.show_directors(None, many)) == media_film.MAKERS_MAX


def test_show_crew_prefers_the_series_own_people():
    item = {"people": [{"name": "Series Dir", "type": "Director"}, {"name": "A", "type": "Actor"}]}
    seasons = [{"episodes": [{"crew": [{"name": "Ep Dir", "type": "Director"}]}]}]
    assert media_film.show_crew(item, seasons) == [{"name": "Series Dir", "type": "Director"}]
    assert media_film.show_crew({"people": []}, seasons) == [{"name": "Ep Dir", "type": "Director"}]
    assert media_film.show_crew(None, []) == []
