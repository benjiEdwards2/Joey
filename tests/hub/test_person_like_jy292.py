"""JY-292 (option C, B. 2026-11-06; first slice = source A): "If you like them you may like" on the person page - a
deferred part (/media/person/{id}/like) that reads the cast of the person's top acting titles through the long meta
cache and shows the co-stars they share 2+ titles with, each with a reason line. No new call on the page render;
friends on the TV never get it; the owner on the TV gets TV person tiles. No network: Seerr is faked."""
import re
from pathlib import Path

from hub import guest, media_person
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import env  # noqa: F401
from tests.hub.test_media_person import seed
from tests.hub.tv_css import design_px

ROOT = Path(__file__).resolve().parents[2]


def cast(*people):
    return {"credits": {"cast": [{"id": i, "name": n, "profilePath": p, "character": "x"} for i, n, p in people]}}


BEN, CY, DOT = (60, "Ben Bloom", "/ben.jpg"), (61, "Cy Crane", None), (62, "Dot Day", "/dot.jpg")
ADA = (55, "Ada Actor", "/ada.jpg")


def seed_casts(both):
    t = both.seerr.table
    t["/api/v1/movie/603"] = cast(ADA, BEN, CY, DOT)       # Harbour Lights
    t["/api/v1/movie/800"] = cast(BEN, ADA, CY)            # Old Film
    t["/api/v1/movie/801"] = cast(DOT, BEN)                # Both Roles
    t["/api/v1/tv/900"] = cast(CY)                          # Other Show
    t["/api/v1/movie/901"] = cast()                         # Already There


def like(client):
    return client.get("/media/person/55/like", headers={"HX-Request": "true"})


def title_reads(both):
    return [u for u in both.calls if re.search(r"/api/v1/(movie|tv)/\d+$", u)]


def test_pick_titles_skips_self_talk_and_bonus_rows():
    credits = {"cast": [
        {"id": 1, "mediaType": "movie", "title": "Big", "voteCount": 900, "character": "Ann"},
        {"id": 2, "mediaType": "tv", "name": "Late Talk", "voteCount": 5000, "genreIds": [10767], "character": "Guest"},
        {"id": 3, "mediaType": "movie", "title": "Doc", "voteCount": 800, "character": "Herself"},
        {"id": 4, "mediaType": "movie", "title": "Extra", "voteCount": 700, "video": True},
        {"id": 5, "mediaType": "tv", "name": "Show", "voteCount": 100, "character": "Bo"}],
        "crew": [{"id": 6, "mediaType": "movie", "title": "Directed", "voteCount": 9999, "job": "Director"}]}
    assert media_person._like_titles(credits) == [("movie", 1, "Big"), ("tv", 5, "Show")]


def test_part_ranks_shared_co_stars_with_reasons(env):
    client, both = env()
    seed(both)
    seed_casts(both)
    with client:
        b = like(client).text
    cards = re.findall(r'<a class="castcard" href="([^"]+)">(.*?)<span class="castname">([^<]+)</span>'
                       r'<span class="castrole likewhy">([^<]+)</span><span class="castrole liketitles">([^<]+)</span>',
                       b, re.S)
    assert [(c[0], c[2], c[3]) for c in cards] == [
        ("/media/person/60", "Ben Bloom", "Cast together in 3 films"),
        ("/media/person/61", "Cy Crane", "Cast together in 3 titles"),
        ("/media/person/62", "Dot Day", "Cast together in 2 films")]
    assert "Ada Actor" not in b                                            # never the person themselves
    assert 'src="/img/tmdb:/ben.jpg?h=270"' in cards[0][1]
    assert 'class="castpic initials" aria-hidden="true">CC' in cards[1][1]
    assert cards[2][4] == "Both Roles, Harbour Lights"
    assert '<h2 class="seclabel">If you like them you may like</h2>' in b
    assert 'class="sec castsec casttiles personlike"' in b


def test_part_needs_two_shared_titles_and_is_empty_otherwise(env):
    client, both = env()
    seed(both)
    both.seerr.table["/api/v1/movie/603"] = cast(ADA, BEN)
    with client:
        r = like(client)
    assert r.status_code == 200 and r.text == ""


def test_part_without_seerr_is_empty_and_bad_id_404(env):
    client, _both = env()
    with client:
        assert like(client).text == ""
        assert client.get("/media/person/0/like").status_code == 404


def test_title_reads_are_cached(env):
    client, both = env()
    seed(both)
    seed_casts(both)
    with client:
        like(client)
        first = len(title_reads(both))
        like(client)
    assert 0 < first <= media_person.LIKE_TITLES and len(title_reads(both)) == first   # the second load reads none


def test_page_defers_the_shelf_and_makes_no_title_read(env):
    client, both = env()
    seed(both)
    seed_casts(both)
    with client:
        b = main_of(client.get("/media/person/55").text)
    assert re.search(r'<div class="personlike-wait" hidden hx-get="/media/person/55/like" hx-trigger="load"', b)
    assert "If you like them" not in b and title_reads(both) == []
    assert b.index('<h2 class="seclabel">On server</h2>') < b.index("personlike-wait") < b.index(
        '<h2 class="seclabel">Films</h2>')


def test_guest_may_load_the_part():
    assert guest.allows("GET", "/media/person/55/like") and not guest.allows("POST", "/media/person/55/like")


def test_tv_tiles_template_and_pins():
    src = (ROOT / "hub" / "templates" / "_person_like.html").read_text(encoding="utf-8")
    assert 'tvt.person({"name": p.name, "role": p.why, "ref": p.ref, "href": p.href})' in src
    assert 'class="carousel tvt-row tvt-row-person"' in src
    tv = design_px((ROOT / "hub" / "static" / "tv.css").read_text(encoding="utf-8"))
    assert "html.tv .carousel.tvt-row-person > * { flex: 0 0 80px; width: 80px; }" in tv     # JY-323 width kept
    page = (ROOT / "hub" / "templates" / "media_person.html").read_text(encoding="utf-8")
    before = page.split('class="personlike-wait"', 1)[0]
    assert before.rfind("{% if not tvf %}") > before.rfind("{% endif %}{% endfor %}")   # friends on the TV never load it
