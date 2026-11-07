"""JY-285 (B. 2026-11-06: "A on desktop, tv etc if you click into it. C on TV app where we have the space underneath"):
web - the maker chips stay person links, one "Director and Writer" chip for the same person, the person page lands on
"On server" (else Films) when opened from a chip; the TV app - a deferred "More from <name>" poster shelf per maker under
the cast and above Scores. No network: Jellyfin and Seerr are faked."""
import re

import pytest

from hub import guest, media_person
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.film_page import whole
from tests.hub.helpers import env, FILM  # noqa: F401
from tests.hub.test_episode_flow_nav import show  # noqa: F401  (fixture: season items sea1 / sea2)
from tests.hub.test_episode_flow_templates import ENV
from tests.hub.test_media_film import chips, hero
from tests.hub.test_media_person import seed

GUY, WREN = {"id": 77, "name": "Guy Maker"}, {"id": 78, "name": "Wren Writer"}


def film_with(*crew):
    return {**FILM, "credits": {**FILM["credits"], "crew": list(crew)}}


def credit(i, title, date, job="Director", kind="movie", **extra):
    name = "title" if kind == "movie" else "name"
    day = "releaseDate" if kind == "movie" else "firstAirDate"
    return {"id": i, "mediaType": kind, name: title, day: date, "posterPath": f"/p{i}.jpg", "job": job,
            "department": "Directing" if job == "Director" else "Writing", "voteCount": 500, **extra}


def seed_makers(both):
    t = both.seerr.table
    t["/api/v1/movie/603"] = film_with({**GUY, "job": "Director"}, {**GUY, "job": "Screenplay"},
                                       {**WREN, "job": "Writer"}, {"id": 79, "name": "Cy Camera", "job": "Cinematographer"})
    t["/api/v1/person/77/combined_credits"] = {
        "cast": [{"id": 500, "mediaType": "movie", "title": "Cameo Film", "releaseDate": "2025-01-01", "voteCount": 900,
                  "character": "Waiter"}],
        "crew": [credit(1000 + n, f"Film {n:02d}", f"20{n:02d}-01-01") for n in range(1, 15)]
        + [credit(603, "Harbour Lights", "2019-05-05", job="Screenplay"),        # the page's own title: left out
           credit(100, "Quiet Show", "2024-06-01", job="Creator", kind="tv"),    # on the server -> On Joey
           credit(990, "Making Of", "2026-01-01", video=True)]}                  # a bonus video: left out
    t["/api/v1/person/78/combined_credits"] = {"crew": [credit(2001, "Wren's Film", "2018-01-01", job="Writer")]}


def makers(client, path="/media/title/movie/603/makers"):
    return client.get(path, headers={"HX-Request": "true"})


def shelves(body):
    return [(name, re.findall(r'<a class="card-poster tvt tvt-poster[^"]*" href="([^"]+)">.*?<span class="row-title">'
                              r'([^<]+)</span>', sec, re.S))
            for name, sec in re.findall(r'<h2 class="seclabel">More from ([^<]+)</h2>(.*?)</section>', body, re.S)]


# ---- A. web ----

def test_same_person_directing_and_writing_is_one_chip(env):
    client, both = env()
    seed_makers(both)
    with client:
        h = hero(main_of(whole(client, "/media/title/movie/603")))
    assert chips(h) == [("Director and Writer", "Guy Maker", "/media/person/77?from=title#land"),
                        ("Writer", "Wren Writer", "/media/person/78?from=title#land")]


def test_chip_landing_anchors_on_server_first(env):
    client, both = env()
    seed(both)
    with client:
        b = main_of(client.get("/media/person/55?from=title").text)
        plain = main_of(client.get("/media/person/55").text)
    assert '<section class="sec" id="land">\n  <h2 class="seclabel">On server</h2>' in b and b.count('id="land"') == 1
    assert 'id="land"' not in plain                                         # other entry points unchanged


def test_chip_landing_falls_back_to_films(env):
    client, both = env()
    seed(both)
    both.seerr.table["/api/v1/person/55/combined_credits"] = {"crew": [credit(1001, "Film 01", "2001-01-01")]}
    with client:
        b = main_of(client.get("/media/person/55?from=title").text)
    assert '<section class="sec" id="land">\n  <h2 class="seclabel">Films</h2>' in b and b.count('id="land"') == 1


def test_find_link_keeps_the_landing_flag(monkeypatch, env):
    client, _ = env()
    monkeypatch.setattr(media_person, "find_person_id", lambda name: 55)
    with client:
        r = client.get("/media/person/find?name=Guy%20Maker&from=title", follow_redirects=False)
        plain = client.get("/media/person/find?name=Guy%20Maker", follow_redirects=False)
    assert r.headers["location"] == "/media/person/55?from=title" and plain.headers["location"] == "/media/person/55"


def test_web_pages_carry_no_maker_shelf(env, show):
    client, both = env()
    seed_makers(both)
    with client:
        for path in ("/media/title/movie/603", "/media/title/tv/100", "/media/item/sea1", "/media/item/ep3"):
            b = whole(client, path) if path.startswith("/media/title/") else client.get(path).text
            assert "tvmakers-wait" not in b and "More from" not in b, path


# ---- C. the TV app ----

@pytest.mark.parametrize("path, href", [("/media/title/movie/603", "/media/title/movie/603/makers"),
                                        ("/media/title/tv/100", "/media/title/tv/100/makers"),
                                        ("/media/item/sea1", "/media/title/tv/100/makers"),
                                        ("/media/item/ep3", "/media/title/tv/100/makers")])
def test_tv_title_pages_defer_the_shelf_under_the_cast(env, show, monkeypatch, path, href):
    monkeypatch.setitem(ENV.globals, "tv_mode", lambda request: True)
    client, both = env()
    seed_makers(both)
    with client:
        b = whole(client, path) if path.startswith("/media/title/") else client.get(path).text
    wait = (f'<div class="tvmakers-wait" hidden hx-get="{href}" hx-trigger="load" hx-target="this" hx-select="unset" '
            f'hx-swap="outerHTML" hx-push-url="false"></div>')
    assert wait in b and "More from" not in b, path                        # never drawn on render
    if 'class="sec tv-cast"' in b:
        assert b.index('class="sec tv-cast"') < b.index(wait), path
    if 'aria-label="Scores"' in b:
        assert b.index(wait) < b.index('aria-label="Scores"'), path


def test_shelf_is_twelve_newest_without_the_title_with_on_joey(env):
    client, both = env()
    seed_makers(both)
    with client:
        r = makers(client)
    assert r.status_code == 200
    got = shelves(r.text)
    assert [n for n, _ in got] == ["Guy Maker", "Wren Writer"]                # one shelf for Director and Writer
    guy = got[0][1]
    assert len(guy) == media_person.MAKER_MAX == 12
    assert [t for _, t in guy] == ["Quiet Show", "Film 14", "Film 13", "Film 12", "Film 11", "Film 10", "Film 09",
                                   "Film 08", "Film 07", "Film 06", "Film 05", "Film 04"]   # films and shows, newest first
    assert "Harbour Lights" not in r.text and "Cameo Film" not in r.text and "Making Of" not in r.text
    show = re.search(r'<a class="card-poster tvt tvt-poster tvt-request" href="/media/item/ser1">.*?</a>', r.text, re.S)
    assert show and '<span class="tvt-band tvt-band-lib">On Joey</span>' in show.group(0)
    assert r.text.count("On Joey") == 1 and "Request" not in r.text and "Requested" not in r.text
    assert '<a class="card-poster tvt tvt-poster" href="/media/title/movie/1014">' in r.text
    assert got[1][1] == [("/media/title/movie/2001", "Wren&#39;s Film")]


def test_credits_are_one_cached_read_per_person(env):
    client, both = env()
    seed_makers(both)
    with client:
        makers(client)
        makers(client)
    reads = [u for u in both.calls if "/combined_credits" in u]
    assert sorted(reads) == sorted(set(reads)) and len(reads) == 2


def test_empty_or_seerr_down_is_an_empty_200(env):
    client, both = env()
    with client:
        assert makers(client).text == "" and makers(client).status_code == 200        # nobody has credits
        both.fail_seerr = True
        r = makers(client, "/media/title/movie/701/makers")
        assert r.status_code == 200 and r.text == ""
        assert client.get("/media/title/film/603/makers").status_code == 404
        assert client.get("/media/title/movie/0/makers").status_code == 404


def test_one_deadline_bounds_the_reads(monkeypatch):
    clock = {"t": 0.0}
    reads = []
    body = film_with({**GUY, "job": "Director"}, {**WREN, "job": "Writer"})

    def cget(path):
        reads.append(path)
        if "combined_credits" in path:
            clock["t"] += 30                                       # the first person's read used up the budget
            return {"crew": [credit(1001, "Film 01", "2001-01-01")]}
        return body

    monkeypatch.setattr(media_person, "_cget", cget)
    monkeypatch.setattr(media_person.time, "monotonic", lambda: clock["t"])
    got = media_person.maker_shelves("movie", 603, snaps={})
    assert [s["name"] for s in got] == ["Guy Maker"] and len([u for u in reads if "combined" in u]) == 1
    assert media_person.MAKER_DEADLINE_S == 12


def test_friends_get_the_same_read_only_shelf():
    assert guest.allows("GET", "/media/title/movie/603/makers") and not guest.allows("POST", "/media/title/movie/603/makers")


def test_friend_session_loads_the_part(monkeypatch, tmp_path):
    from tests.hub.guest_pages import TV_UA, guest_client, sign_in
    from tests.hub.fake_jellyfin import FRIEND_ID
    client, fake = guest_client(monkeypatch, tmp_path, {})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        r = c.get("/media/title/movie/603/makers", headers={"User-Agent": TV_UA, "HX-Request": "true"})
    assert r.status_code == 200 and "Request" not in r.text
