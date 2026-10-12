"""Person pages (F11): /media/person/{id}. Jellyfin and Jellyseerr are faked at `requests.get` via the film
page's fixtures; no network."""
import html as htmllib
import re

from tests.hub.film_page import whole
from tests.hub.helpers import env, FILM, prow, SEERR_URL as SEERR, SKEY
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.test_media_film import KEY, URL

PERSON = {"id": 55, "name": "Ada Actor", "knownForDepartment": "Acting", "birthday": "1976-03-12", "deathday": None,
          "placeOfBirth": "Dublin", "profilePath": "/ada.jpg", "biography": "Ada began on the stage. " + "Long story. " * 60}
CREDITS = {
    "cast": [
        {"id": 603, "mediaType": "movie", "title": "Harbour Lights", "releaseDate": "2019-05-05", "posterPath": "/hl.jpg",
         "character": "Pilot", "mediaInfo": {"status": 5}},
        {"id": 800, "mediaType": "movie", "title": "Old Film", "releaseDate": "1999-01-01", "posterPath": "/o.jpg", "character": "Sarah"},
        {"id": 801, "mediaType": "movie", "title": "Both Roles", "releaseDate": "2022-02-02", "character": "Sarah",
         "mediaInfo": {"status": 2}},
        {"id": 100, "mediaType": "tv", "name": "Quiet Show", "firstAirDate": "2020-01-01", "character": "Narrator"},
        {"id": 900, "mediaType": "tv", "name": "Other Show", "firstAirDate": "2023-06-01", "character": "Dr Who",
         "mediaInfo": {"status": 3}},
        {"id": 901, "mediaType": "movie", "title": "Already There", "releaseDate": "2010-01-01", "mediaInfo": {"status": 5}},
    ],
    "crew": [{"id": 801, "mediaType": "movie", "title": "Both Roles", "releaseDate": "2022-02-02", "job": "Director"}],
}


def seed(both, person=PERSON, credits=CREDITS):
    both.seerr.table["/api/v1/person/55"] = person
    both.seerr.table["/api/v1/person/55/combined_credits"] = credits


def test_header_frame_bio_and_life(env):
    client, both = env()
    seed(both)
    with client:
        html = client.get("/media/person/55").text
    b = main_of(html)
    assert 'href="/media/discover" aria-current="page"' in b          # Discover is the active section
    assert "Ada Actor" in b and "Acting" in b and "Born 12 Mar 1976 · Dublin" in b
    assert 'src="/img/tmdb:/ada.jpg?h=240"' in b
    assert "Ada began on the stage." in b and "<summary>More</summary>" in b
    bio = re.search(r'class="overview">(Ada.*?)</p>', b, re.S).group(1) + re.search(r'<details.*?</details>', b, re.S).group(0)
    assert len(re.sub(r"<[^>]+>|…|More", "", bio)) <= 1210


def test_died_line_and_initials_fallback(env):
    client, both = env()
    seed(both, {**PERSON, "profilePath": None, "deathday": "2020-01-03", "biography": ""})
    with client:
        b = main_of(client.get("/media/person/55").text)
    assert "Born 12 Mar 1976 · Dublin · Died 3 Jan 2020" in b
    assert 'class="personpic initials" aria-hidden="true">AA' in b and "<details" not in b


def test_on_your_server_shelf_first_with_library_matches_only(env):
    client, both = env()
    seed(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    shelf, rest = b.split("Everything else", 1)
    assert "On server" in shelf and 'href="/media/item/mov1"' in shelf and 'href="/media/item/ser1"' in shelf
    assert "Harbour Lights" in shelf and "as Pilot" in shelf and "Quiet Show" in shelf
    assert "Old Film" not in shelf and "Harbour Lights" not in rest and "Quiet Show" not in rest
    assert "3 titles" not in b and "6 titles · 2 on server" in b


def test_grid_groups_newest_first_roles_joined_and_status_words(env):
    client, both = env()
    seed(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    rest = b.split("Everything else", 1)[1]
    assert rest.index("Films") < rest.index("TV")
    films, tv = rest.split("TV", 1)
    assert films.index("Both Roles") < films.index("Already There") < films.index("Old Film")  # 2022, 2010, 1999
    assert "as Sarah · Director" in films and films.count("Both Roles") == 1
    assert 'href="/media/title/movie/801"' in films and 'href="/media/title/tv/900"' in tv
    assert ">Requested<" in films and ">Not on server<" in films and ">On server<" in films   # Already There: Available
    assert ">Processing<" in tv and "as Dr Who" in tv


def test_unknown_or_bad_id_404_without_upstream_call(env):
    client, both = env()
    with client:
        for bad in ("abc", "0", "-3", "5x"):
            assert client.get(f"/media/person/{bad}").status_code == 404
    assert not [c for c in both.calls if c.startswith(SEERR)]


def test_upstream_failure_words_page_still_200(env):
    client, both = env()
    both.fail_seerr = True
    with client:
        r = client.get("/media/person/55")
    assert r.status_code == 200 and "Couldn't reach Seerr — nothing to show for this person yet" in htmllib.unescape(r.text)


def test_cast_links_on_film_page_point_to_person(env):
    client, both = env()
    both.seerr.table["/api/v1/movie/603"] = {**FILM, "credits": {
        "cast": [{"id": 55, "name": "Ada Actor", "character": "Pilot", "profilePath": "/ada.jpg"},
                 {"name": "Bo Bit", "character": "Deckhand"}],
        "crew": [{"id": 77, "name": "Dee Director", "job": "Director"}]}}
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    assert 'class="castcard" href="/media/person/55"' in b and 'href="/media/person/77">Dee Director</a>' in b
    assert "/media/discover?q=Dee" not in b and '<div class="castcard">' in b       # no id -> plain text, no link


def test_no_url_or_key_in_html(env):
    client, both = env()
    seed(both)
    with client:
        html = client.get("/media/person/55").text
    assert SEERR not in html and SKEY not in html and "secret-host" not in html and KEY not in html and URL not in html
