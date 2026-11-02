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
        {"id": 800, "mediaType": "movie", "title": "Old Film", "releaseDate": "1999-01-01", "posterPath": "/o.jpg", "character": "Sarah", "voteCount": 50},
        {"id": 801, "mediaType": "movie", "title": "Both Roles", "releaseDate": "2022-02-02", "character": "Sarah",
         "voteCount": 50, "mediaInfo": {"status": 2}},
        {"id": 100, "mediaType": "tv", "name": "Quiet Show", "firstAirDate": "2020-01-01", "character": "Narrator"},
        {"id": 900, "mediaType": "tv", "name": "Other Show", "firstAirDate": "2023-06-01", "character": "Dr Who",
         "mediaInfo": {"status": 3}},
        {"id": 901, "mediaType": "movie", "title": "Already There", "releaseDate": "2010-01-01", "voteCount": 50, "mediaInfo": {"status": 5}},
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


def test_writer_credits_get_their_own_writing_row(env):
    # JY-280 (P1, AC 4): the film's Writer chip lands on a page listing their writing (writer jobs only)
    client, both = env()
    seed(both, credits={**CREDITS, "crew": CREDITS["crew"] + [
        {"id": 802, "mediaType": "movie", "title": "Penned Film", "releaseDate": "2021-03-03", "job": "Screenplay"},
        {"id": 803, "mediaType": "movie", "title": "Story Only", "releaseDate": "2018-03-03", "job": "Story"}]})
    with client:
        b = main_of(client.get("/media/person/55").text)
    sec = b.split('<section class="sec personwriting">', 1)[1].split("</section>", 1)[0]
    assert "Penned Film" in sec and "Story Only" in sec and "Screenplay" in sec
    assert "Both Roles" not in sec and "Harbour Lights" not in sec          # directing / acting stay out of Writing


def test_no_writing_row_without_writer_jobs(env):
    client, both = env()
    seed(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    assert "personwriting" not in b and ">Writing</h2>" not in b


# JY-293: tiered order - on server, released films, film series, bonus and other, then TV.
from hub import media_person as mp  # noqa: E402


def _m(i, title, date="2015-01-01", votes=500, **kw):
    return {"id": i, "mediaType": "movie", "title": title, "releaseDate": date, "voteCount": votes, **kw}


def _order(cast, lib=None):
    return [(r["tier"], r["title"]) for r in mp._credits({"cast": cast}, lib or {})]


def test_tiers_server_released_series_bonus_in_order():
    cast = [_m(4, "Making Of Thing", video=True), _m(3, "Storm Rider 2", "2020-01-01"), _m(5, "Storm Rider", "2001-01-01"),
            _m(2, "Lone Film", "2018-01-01"), _m(1, "Home Copy", "1990-01-01", votes=0)]
    assert _order(cast, {"tmdb:1": "jf1"}) == [("server", "Home Copy"), ("films", "Lone Film"), ("series", "Storm Rider 2"),
                                               ("series", "Storm Rider"), ("bonus", "Making Of Thing")]


def test_bonus_rules_low_votes_no_date_future_documentary():
    cast = [_m(1, "Few Votes", votes=9), _m(2, "No Date", date=""), _m(3, "Future", "2999-01-01"),
            _m(4, "Small Doc", votes=40, genreIds=[99]), _m(5, "Big Doc", votes=150, genreIds=[99]),
            _m(6, "Ten Votes", votes=10)]
    tiers = dict((t, k) for k, t in _order(cast))
    assert tiers == {"Few Votes": "bonus", "No Date": "bonus", "Future": "bonus", "Small Doc": "bonus",
                     "Big Doc": "films", "Ten Votes": "films"}


def test_tie_breaks_date_then_votes_then_title_then_id():
    cast = [_m(4, "Beta"), _m(3, "Alpha", votes=900), _m(2, "Alpha"), _m(1, "Alpha"), _m(5, "Zed", "2016-01-01")]
    rows = mp._credits({"cast": cast}, {})
    assert [r["tmdb_id"] for r in rows] == [5, 3, 1, 2, 4]


def test_tv_after_all_films_and_cap_after_ordering():
    cast = [{"id": 9, "mediaType": "tv", "name": "Show", "firstAirDate": "2030-01-01"}] +            [_m(100 + i, f"Bonus {i}", "2025-01-01", votes=0) for i in range(mp.CREDITS_MAX)] + [_m(1, "Real Film", "1980-01-01")]
    rows = mp._credits({"cast": cast}, {})
    assert len(rows) == mp.CREDITS_MAX and rows[0]["title"] == "Real Film" and rows[-1]["tier"] == "bonus"
    assert [r["tier"] for r in mp._credits({"cast": cast[:2] + cast[-1:]}, {})] == ["films", "bonus", "tv"]


def test_page_renders_tier_sections_in_order(env):
    client, both = env()
    seed(both, credits={"cast": [_m(603, "Harbour Lights", "2019-05-05"), _m(2, "Lone Film", "2018-01-01"),
                                 _m(3, "Storm Rider 2", "2020-01-01"), _m(5, "Storm Rider", "2001-01-01"),
                                 _m(4, "Making Of Thing", video=True)]})
    with client:
        b = main_of(client.get("/media/person/55").text)
    i = [b.index(w) for w in ("On server", "Harbour Lights", "Lone Film", "Film series", "Storm Rider 2", "Bonus and other",
                              "Making Of Thing")]
    assert i == sorted(i) and "5 titles · 1 on server" in b and b.count("Storm Rider 2") == 1


def test_featurette_with_same_prefix_does_not_promote_film_to_series():
    cast = [_m(1, "Storm Rider", "2001-01-01"), _m(2, "Storm Rider Making Of", video=True)]
    assert _order(cast) == [("films", "Storm Rider"), ("bonus", "Storm Rider Making Of")]
