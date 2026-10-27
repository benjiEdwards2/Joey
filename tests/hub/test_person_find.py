"""JY-118 (2026-10-27): /media/person/find?name= - a tap on a guest or crew name looks the name up ONCE in Seerr
search and redirects to the real person page, else to the Discover search. Nothing is looked up on render. Seerr is
faked (tests/hub/test_media_discover.py Fake for the private front, tests/hub/fake_seerr.py for a friend)."""
import re
from urllib.parse import quote

import pytest

from hub import guest, media_film
from tests.hub.fake_seerr import res
from tests.hub.test_guest_requests import friend  # noqa: F401 - the signed-in friend client with FakeSeerr behind it
from tests.hub.test_media_discover import env, res as drow  # noqa: F401 - the private-front fixture + a result row

PEOPLE = {"results": [
    {"id": 12, "mediaType": "movie", "title": "Ada Actor", "releaseDate": "2001-01-01"},     # a TITLE with the name: ignored
    {"id": 99, "mediaType": "person", "name": "Ada Actors"},                                     # not the same name
    {"id": 55, "mediaType": "person", "name": "ada  actor"},                                     # case/space-insensitive match
    {"id": 56, "mediaType": "person", "name": "Ada Actor"}]}


def person_searches(gets):
    return [g for g in gets if g.startswith("/api/v1/search")]


def test_find_redirects_to_the_person_page_with_one_search(env):
    client, fake = env()
    fake.search_results = PEOPLE
    with client:
        r = client.get("/media/person/find?name=Ada%20Actor", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/media/person/55"
    assert person_searches(fake.gets) == ["/api/v1/search?query=Ada%20Actor"]      # exactly one read, nothing else


def test_find_without_a_person_match_falls_back_to_discover_search(env):
    client, fake = env()
    fake.search_results = {"results": [{"id": 12, "mediaType": "movie", "title": "Ada Actor"}]}
    with client:
        r = client.get("/media/person/find?name=Ada%20Actor", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/media/discover?q=Ada%20Actor"


def test_find_when_seerr_is_down_or_unset_never_500s(env):
    client, fake = env()
    fake.fail = True
    with client:
        r = client.get("/media/person/find?name=Ada%20Actor", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/media/discover?q=Ada%20Actor"


def test_find_empty_or_odd_names_make_no_search(env):
    client, fake = env()
    with client:
        none = client.get("/media/person/find", follow_redirects=False)
        blank = client.get("/media/person/find?name=%20%20", follow_redirects=False)
        long = client.get("/media/person/find?name=" + "x" * 300, follow_redirects=False)
    assert none.status_code == blank.status_code == 404                                              # nothing to look up
    assert long.status_code == 303 and long.headers["location"] == "/media/discover?q=" + "x" * 100   # capped at 100
    assert person_searches(fake.gets) == ["/api/v1/search?query=" + "x" * 100]                       # none for the empty ones


def test_find_is_not_shadowed_by_the_person_id_route(env):
    client, fake = env()
    with client:
        assert client.get("/media/person/find?name=Ada", follow_redirects=False).status_code == 303   # not read as an id
        assert client.get("/media/person/55x").status_code == 404                     # the id route still rejects junk


def test_episode_guests_and_crew_link_the_find_route_and_render_looks_nothing_up():
    ep = {"people": [{"name": "Gus Guest", "type": "GuestStar", "role": "Mailman", "ref": None},
                     {"name": "Eppy O'Director", "type": "Director"}]}
    assert media_film.episode_guests(ep, [], [], None)[0]["href"] == "/media/person/find?name=Gus%20Guest"
    crew = media_film.episode_crew(ep)
    assert crew == [{"role": "Directed by", "people": [
        {"name": "Eppy O'Director", "href": "/media/person/find?name=" + quote("Eppy O'Director", safe="")}]}]


def test_pages_make_no_search_call_on_render(env):
    """An episode / show page with guests and crew shows the find links without calling Seerr search."""
    client, fake = env()
    with client:
        client.get("/media/title/movie/603")
        client.get("/media/discover")
    assert person_searches(fake.gets) == []


def test_friend_tap_reaches_the_person_page_media_only(friend):
    friend.seerr.search = [res(700, "Ada Actor"), {"id": 55, "mediaType": "person", "name": "Ada Actor"}]
    r = friend.get("/media/person/find?name=Ada%20Actor", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/media/person/55"
    assert guest.allows("GET", "/media/person/find") and not guest.allows("POST", "/media/person/find")
    assert guest.allows("GET", r.headers["location"])


def test_friend_find_falls_back_to_discover(friend):
    friend.seerr.search = []
    r = friend.get("/media/person/find?name=Nobody%20Known", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/media/discover?q=Nobody%20Known"
