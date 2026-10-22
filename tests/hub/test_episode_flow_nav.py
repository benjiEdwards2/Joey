"""TV episode flow, WP-E3 (2026-10-16; review/2026-10-16-episodes-ux/EPISODES_CONTRACT.md section 2): the season and
episode pages' `nav` (show / season links, the S4 / S5 switch, Previous / Next, "E3 of 6"), the episode's `guests`
("k eps this season") and `crew_ep`. Checked on the page's `film` dict (captured at render), with Jellyfin and
Jellyseerr faked at `requests.get` (tests/hub/helpers.py env)."""
import copy

import pytest

from hub import media_film, media_item
from tests.hub import helpers as tmi
from tests.hub.helpers import env  # noqa: F401  (fixture)

EP_FIELDS = "UserData,PremiereDate,RunTimeTicks,People"
FLOW_KEYS = ("nav", "guests", "crew_ep")


def s5(i, name):
    """A Season 5 episode (its own ids, so it never collides with Season 4's ep1..ep6)."""
    return {**tmi.ep(i, name, season="sea2"), "Id": f"s5e{i}"}


@pytest.fixture()
def show(monkeypatch):
    """Quiet Show with two seasons (4: ep1..ep6, 5: s5e1..s5e2), season items, and People: Gus Guest guests in
    S4 E1 and E3 and is listed (as an Actor) in E2 - and in S5 E1, which must not count; Main Mira is a series
    regular (the series' Actor People) whom E3 also lists as a guest star."""
    monkeypatch.setitem(tmi.SEASON_NO, "sea2", 5)
    items = copy.deepcopy(tmi.ITEMS)
    items["ser1"]["People"] = [{"Name": "Main Mira", "Type": "Actor", "Role": "Mira"}]
    items["ep3"]["People"] = [
        {"Name": "Gus Guest", "Type": "GuestStar", "Role": "Mailman", "Id": "person-gus", "PrimaryImageTag": "t1"},
        {"Name": "Main Mira", "Type": "GuestStar", "Role": "Mira"},
        {"Name": "Nora New", "Type": "GuestStar"},
        {"Name": "Eppy Director", "Type": "Director"}, {"Name": "Eppy Director", "Type": "Director"},
        {"Name": "Wren Writer", "Type": "Writer"}, {"Name": "Wes Writer", "Type": "Writer"}]
    for i in (1, 6):
        items[f"ep{i}"] = {**copy.deepcopy(items["ep3"]), "Id": f"ep{i}", "IndexNumber": i, "Name": f"Episode {i}",
                           "People": []}
    items["sea1"] = {"Id": "sea1", "Type": "Season", "Name": "Season 4", "SeriesId": "ser1", "SeriesName": "Quiet Show",
                     "IndexNumber": 4}
    items["sea2"] = {"Id": "sea2", "Type": "Season", "Name": "Season 5", "SeriesId": "ser1", "SeriesName": "Quiet Show",
                     "IndexNumber": 5}
    monkeypatch.setattr(tmi, "ITEMS", items)
    eps = copy.deepcopy(tmi.EPISODES) + [s5(1, "Five One"), s5(2, "Five Two")]
    gus = {"Name": "Gus Guest", "Type": "GuestStar"}
    eps[0]["People"] = [gus]
    eps[1]["People"] = [{"Name": "Gus Guest", "Type": "Actor"}]
    eps[2]["People"] = [gus, {"Name": "Nora New", "Type": "GuestStar"}]
    eps[6]["People"] = [gus]
    monkeypatch.setattr(tmi, "EPISODES", eps)


@pytest.fixture()
def film_of(env, monkeypatch):
    """GET a page and return the `film` dict it rendered (plus the fake, for its Jellyfin calls)."""
    seen = []
    real = media_film._render

    def capture(request, src, film, *a, **kw):
        seen.append(film)
        return real(request, src, film, *a, **kw)
    monkeypatch.setattr(media_film, "_render", capture)

    def get(url):
        client, both = env()
        with client:
            assert client.get(url).status_code == 200
        media_film.drain_extras()
        return seen[-1], both
    return get


# ---- nav ----

def test_nav_for_a_middle_episode(show, film_of):
    film, _ = film_of("/media/item/ep3")
    assert film["nav"] == {
        "show": {"title": "Quiet Show", "href": "/media/item/ser1"},
        "season": {"n": 4, "href": "/media/item/sea1", "total": 6},
        "seasons": [{"n": 4, "href": "/media/item/sea1", "on": True}, {"n": 5, "href": "/media/item/sea2", "on": False}],
        "prev": {"number": 2, "name": "Two", "href": "/media/item/ep2"},
        "next": {"number": 4, "name": "Four", "href": "/media/item/ep4"},
        "position": "E3 of 6"}


def test_nav_first_episode_has_no_previous(show, film_of):
    nav = film_of("/media/item/ep1")[0]["nav"]
    assert nav["prev"] is None and nav["next"] == {"number": 2, "name": "Two", "href": "/media/item/ep2"}
    assert nav["position"] == "E1 of 6"


def test_nav_last_episode_has_no_next(show, film_of):
    nav = film_of("/media/item/ep6")[0]["nav"]   # unaired: it is still listed, so still the season's last
    assert nav["next"] is None and nav["prev"] == {"number": 5, "name": "Five", "href": "/media/item/ep5"}
    assert nav["position"] == "E6 of 6"


def test_season_page_switch_marks_its_season(show, film_of):
    film, _ = film_of("/media/item/sea2")
    assert film["nav"] == {"show": {"title": "Quiet Show", "href": "/media/item/ser1"},
                           "seasons": [{"n": 4, "href": "/media/item/sea1", "on": False},
                                       {"n": 5, "href": "/media/item/sea2", "on": True}],
                           "season": None, "prev": None, "next": None, "position": None}
    assert "guests" not in film and "crew_ep" not in film          # episode-only keys


# ---- guests / crew_ep ----

def test_guests_exclude_main_cast_and_count_the_season(show, film_of):
    film, _ = film_of("/media/item/ep3")
    assert film["guests"] == [
        {"name": "Gus Guest", "role": "Mailman", "poster": "jf:person-gus", "href": None, "eps_this_season": 3},
        {"name": "Nora New", "role": None, "poster": None, "href": None, "eps_this_season": 1}]


def test_guests_exclude_the_pages_cast_too():
    ep = {"people": [{"name": "Carl Cast", "type": "GuestStar", "role": "", "ref": None},
                     {"name": "Gus", "type": "GuestStar", "role": "Mailman", "ref": None},
                     {"name": "Gus", "type": "GuestStar", "role": "Mailman", "ref": None}]}
    season = {"episodes": [{"people_names": ["Gus", "Carl Cast"]}, {"people_names": []}]}
    got = media_film.episode_guests(ep, [{"name": "Carl Cast"}], [], season)
    assert got == [{"name": "Gus", "role": "Mailman", "poster": None, "href": None, "eps_this_season": 1}]
    assert media_film.episode_guests({"people": []}, None, None, None) == []


def test_crew_ep_rows(show, film_of):
    film, _ = film_of("/media/item/ep3")
    assert film["crew_ep"] == [
        {"role": "Directed by", "people": [{"name": "Eppy Director", "href": None}]},
        {"role": "Written by", "people": [{"name": "Wren Writer", "href": None}, {"name": "Wes Writer", "href": None}]}]
    first = film_of("/media/item/ep1")[0]   # an episode with no People: both lists empty, never absent
    assert first["crew_ep"] == [] and first["guests"] == []


# ---- absent elsewhere; no extra Jellyfin reads ----

@pytest.mark.parametrize("url", ["/media/item/mov1", "/media/item/ser1", "/media/title/movie/603",
                                 "/media/title/tv/100"])
def test_films_shows_and_off_server_pages_carry_none_of_the_keys(show, film_of, url):
    film, _ = film_of(url)
    assert not any(k in film for k in FLOW_KEYS)


def test_episode_page_makes_no_extra_jellyfin_reads(show, film_of, monkeypatch):
    _, both = film_of("/media/item/ep3")
    with_flow = [path for path, _ in both.jf.calls]
    monkeypatch.setattr(media_film, "episode_flow", lambda *a, **kw: {})   # the page as it was before WP-E3
    _, both = film_of("/media/item/ep3")
    assert with_flow == [path for path, _ in both.jf.calls]
    # the season list's ONE episodes read, with today's fields (the other /Episodes read is the series' file summary)
    assert [p["Fields"] for path, p in both.jf.calls if path == "/Shows/ser1/Episodes"].count(EP_FIELDS) == 1


def test_season_list_carries_each_episodes_people_names(show, env):
    client, _ = env()
    with client:
        data = media_item._data("ser1")
    s4 = next(s for s in data["seasons"] if s["number"] == 4)
    assert [e["people_names"] for e in s4["episodes"][:4]] == [["Gus Guest"], ["Gus Guest"], ["Gus Guest", "Nora New"], []]
