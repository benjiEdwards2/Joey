"""JY-193 (U7; TV_UI_EVALUATION P2, D1, N1; B.'s Gate 1 pick "2A", 2026-10-25): on the friends' TV, title-page shelves
show on-server titles only (one "More on Joey" shelf), a title that is not on the server is a request page (Request
focused first, Back), and the person page has a TV layout with the on-server shelf only. Desktop / phone (TV mode
off) and the private front are unchanged. Seerr and Jellyfin are the fakes of tests/hub/fake_seerr.py and
fake_jellyfin.py; no network."""
import os
import re
import threading
from pathlib import Path

import pytest

from hub import media_person
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.fake_seerr import res
from tests.hub.film_page import parts_href, whole
from tests.hub.guest_pages import TV_UA, sign_in
from tests.hub.helpers import env  # noqa: F401 - the private (household) front fixture
from tests.hub.test_guest_requests import FRIEND_SEERR, WAITING, post, start

TV = {"User-Agent": TV_UA}
ON, ON2, OFF, OFF2 = 801, 802, 803, 804


def shelves(seerr):
    """603 (on the server) has a Similar and a Recommended shelf mixing on- and off-server titles; 801 is in both."""
    seerr.shelves["/api/v1/movie/603/similar"] = [res(ON, "Kept Lantern", status=5, year="2021"),
                                                   res(OFF, "Far Signal", year="2022")]
    seerr.shelves["/api/v1/movie/603/recommendations"] = [res(OFF2, "Lost Harbour", year="2023"),
                                                           res(ON, "Kept Lantern", status=5, year="2021"),
                                                           res(ON2, "Second Reel", status=5, year="2020")]
    for t, name in ((ON, "Kept Lantern"), (ON2, "Second Reel")):
        seerr.titles[("movie", t)] = {**res(t, name, status=5), "genres": []}


@pytest.fixture()
def friend(monkeypatch, tmp_path):
    client, fake, seerr, uid = start(monkeypatch, tmp_path)
    shelves(seerr)
    with client as c:
        c.fake, c.seerr = fake, seerr
        sign_in(c, fake, uid)
        yield c


def page(c, url, tv):
    """The page with its deferred parts in place (tests/hub/film_page.whole), as the TV or the phone."""
    c.headers.update(TV) if tv else c.headers.pop("User-Agent", None)
    try:
        return whole(c, url)
    finally:
        c.headers.pop("User-Agent", None)


def labels(html):
    return re.findall(r'<h2 class="seclabel">([^<]*)</h2>', html)


# ---- P2 / pick 2A: one "More on Joey" shelf of on-server titles ----

def test_tv_friend_title_shelf_is_more_on_joey_on_server_only(friend):
    b = page(friend, "/media/title/movie/603", tv=True)
    assert "More on Joey" in labels(b)
    assert "Similar" not in labels(b) and "Recommended" not in labels(b)
    more = b.split('<h2 class="seclabel">More on Joey</h2>', 1)[1].split("</section>", 1)[0]
    assert more.count('href="/media/title/movie/801"') == 1                  # in both shelves, drawn once
    assert 'href="/media/title/movie/802"' in more
    assert "/media/title/movie/803" not in more and "/media/title/movie/804" not in more
    assert "Not on server" not in more and "On server" not in more            # caption: title, then the year
    assert re.findall(r'<img class="poster[^"]*" src="/img/[^"]*\?h=(\d+)&amp;', more) == ["600", "600"]


def test_tv_friend_title_with_nothing_on_server_draws_no_shelf(friend):
    friend.seerr.shelves["/api/v1/movie/603/similar"] = [res(OFF, "Far Signal")]
    friend.seerr.shelves["/api/v1/movie/603/recommendations"] = [res(OFF2, "Lost Harbour")]
    b = page(friend, "/media/title/movie/603", tv=True)
    assert "More on Joey" not in b and "/media/title/movie/803" not in b and "/media/title/movie/804" not in b


def test_phone_friend_title_shelves_are_unchanged(friend):
    b = page(friend, "/media/title/movie/603", tv=False)
    assert "Similar" in labels(b) and "Recommended" in labels(b) and "More on Joey" not in b
    assert "/media/title/movie/803" in b and ">Not on server<" in b and "?h=600&amp;" not in b.split("Similar", 1)[1]


def cold_calls(c, url, tv, meta_dir, monkeypatch):
    """The Seerr reads of ONE cold render (every Media cache emptied first): the page, then its deferred part request,
    as htmx makes it, with the background read drained. Returns (the set of call paths, the page's part href).
    JY-249 (2026-10-25, failed once in CI: href None): the page starts the title's background read before its Jellyfin
    reads and peeks the caches after them, so a read that lands in between leaves nothing pending and no part request.
    The read is held until the page has rendered, as on a real cold page where Seerr is slower than Jellyfin."""
    from hub import media_film
    from tests.hub.conftest import clear_media_caches
    media_film.drain_extras()
    clear_media_caches()
    os.environ["META_CACHE_DIR"] = str(meta_dir)   # a fresh on-disk meta cache too (ratings, biographies)
    c.seerr.calls.clear()
    rendered, real = threading.Event(), media_film._load_extras

    def held(*args):
        rendered.wait(media_film.EXTRAS_WAIT)
        return real(*args)
    monkeypatch.setattr(media_film, "_load_extras", held)
    c.headers.update(TV) if tv else c.headers.pop("User-Agent", None)
    try:
        href = parts_href(c.get(url).text)
        rendered.set()
        if href:
            assert c.get(href).status_code == 200
        media_film.drain_extras()
    finally:
        rendered.set()
        monkeypatch.setattr(media_film, "_load_extras", real)
        c.headers.pop("User-Agent", None)
    return {x[1] for x in c.seerr.calls}, href


def test_tv_page_makes_no_more_upstream_calls_than_the_phone_page(friend, monkeypatch, tmp_path):
    """No live call on render: a cold TV render reads exactly what a cold phone render reads, and the shelves still
    come from the deferred part (not the page render)."""
    monkeypatch.setenv("META_CACHE_DIR", str(tmp_path / "meta0"))   # restored after the test
    tv, tv_href = cold_calls(friend, "/media/title/movie/603", True, tmp_path / "meta-tv", monkeypatch)
    phone, phone_href = cold_calls(friend, "/media/title/movie/603", False, tmp_path / "meta-phone", monkeypatch)
    assert phone, "a cold render reads Seerr"
    assert tv == phone
    assert "/api/v1/movie/603/similar" in tv and "/api/v1/movie/603/recommendations" in tv
    for href in (phone_href, tv_href):
        assert href and "/part/all?p=" in href and "shelves" in href.split("?p=", 1)[1].split(","), href


# ---- D1: the TMDB title page is a request page, Request focused first ----

def hero(html):
    return html.split('<header class="pagehead hero-detail', 1)[1].split("</header>", 1)[0]


def test_tv_friend_off_server_title_is_the_request_page(friend):
    b = page(friend, "/media/title/movie/701", tv=True)
    assert '<header class="pagehead hero-detail tv-reqpage"' in b
    h = hero(b)
    assert "Not in the library yet" in h and "Not on Joey yet, so there is nothing to play." in h
    req = re.search(r'<a class="btn btn-white"[^>]*>Request</a>', h)
    assert req and "data-first" in req.group(0)
    assert re.search(r'<button type="button" class="btn btn-glass tv-back"[^>]*onclick="history\.back\(\)[^"]*"[^>]*>Back</button>', h)
    assert h.index(">Request</a>") < h.index(">Back</button>")               # Request leads, Back after it


def test_tv_friend_request_page_after_a_request_says_waiting_and_keeps_back(friend):
    friend.seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    post(friend, "/media/title/movie/701/request")
    h = hero(page(friend, "/media/title/movie/701", tv=True))
    assert WAITING in h and ">Request</a>" not in h and "data-first" not in h and ">Back</button>" in h


def test_tv_friend_on_server_title_is_not_a_request_page(friend):
    b = page(friend, "/media/title/movie/603", tv=True)
    assert "tv-reqpage" not in b and "tv-back" not in b and "Not in the library yet" not in b


def test_phone_friend_off_server_title_is_unchanged(friend):
    b = page(friend, "/media/title/movie/701", tv=False)
    assert "tv-reqpage" not in b and "tv-back" not in b and "Not in the library yet" not in b
    req = re.search(r'<a class="btn btn-white"[^>]*>Request</a>', b)
    assert req and "data-first" not in req.group(0) and "data-first" not in hero(b)


# ---- N1: the person page on the TV ----

def person(shelf, films):
    return {"down": False, "tmdb": 55, "name": "Sample Actor", "ref": None, "dept": "Acting", "life": "Born 1970",
            "bio": {"lead": "A short biography.", "more": "More of it."}, "shelf": shelf, "films": films, "shows": [],
            "tv_maker": False, "head": "2 titles · 1 on server"}


def row(tmdb, title, href, on):
    return {"tmdb_id": tmdb, "kind": "movie", "title": title, "year": "2021", "role": "as Someone", "poster": None,
            "href": href, "item_href": href if on else None, "on_server": on, "word": "On server" if on else "Not on server"}


@pytest.fixture()
def actor(friend, monkeypatch):
    on, off = row(ON, "Kept Lantern", "/media/item/" + "ab" * 16, True), row(OFF, "Far Signal", "/media/title/movie/803", False)
    monkeypatch.setattr(media_person, "build_person", lambda tmdb_id, snaps=None: person([on], [off]))
    return friend


def test_tv_friend_person_page_shows_the_on_server_shelf_only(actor):
    b = page(actor, "/media/person/55", tv=True)
    assert "On server" in labels(b) and not [x for x in labels(b) if x.startswith("Everything else")]
    assert "/media/title/movie/803" not in b and "Far Signal" not in b
    on = b.split('<h2 class="seclabel">On server</h2>', 1)[1].split("</section>", 1)[0]
    assert "?h=600&amp;" in on and "Sample Actor" in b


def test_tv_friend_person_with_nothing_on_server_says_so(actor, monkeypatch):
    monkeypatch.setattr(media_person, "build_person",
                        lambda tmdb_id, snaps=None: person([], [row(OFF, "Far Signal", "/media/title/movie/803", False)]))
    b = page(actor, "/media/person/55", tv=True)
    assert "Nothing with Sample Actor is on Joey yet." in b and "Far Signal" not in b


def test_phone_friend_person_page_is_unchanged(actor):
    b = page(actor, "/media/person/55", tv=False)
    assert "Everything else · Films" in labels(b) and "Far Signal" in b and "?h=600&amp;" not in b


# ---- tv.css: the JY-193 block ----

def test_tv_css_has_the_jy193_block():
    root = Path(__file__).resolve().parents[2] / "hub" / "static"
    raw = (root / "tv.css").read_text(encoding="utf-8")
    m = re.search(r"/\* ==== JY-193.*?\*/(.*?)/\* ==== end JY-193", raw, re.S)
    assert m, "a commented JY-193 block"
    block = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    sels = [s.strip() for rule in re.findall(r"([^{}]+)\{", block) for s in rule.split(",")]
    assert sels and all(s.startswith("html.tv ") for s in sels), sels
    assert ":hover" not in block
    assert ".tv-reqpage" in block and ".personhead" in block
    assert re.search(r"html\.tv \.tv-reqpage \.hero-detail-poster \{[^}]*width: 220px", block)
    assert "JY-193" not in (root / "control-surface.css").read_text(encoding="utf-8")


# ---- review should-fixes (2026-10-25): where data-first may appear; the household front ----

def render_block(on_server, episode=None, req_primary=True, tv=True, monkeypatch=None):
    from hub import shell
    g = shell.templates.env.globals
    monkeypatch.setitem(g, "tv_mode", lambda request: tv)
    monkeypatch.setitem(g, "guest", lambda request=None: True)
    t = {"kind": "movie", "tmdb_id": 701, "title": "X", "year": 2024, "code": 1, "seasons": []}
    film = {"t": t, "on_server": on_server, "episode": episode}
    return shell.templates.env.get_template("_request_block.html").render(
        request=None, t=t, state="idle", req_primary=req_primary, film=film)


@pytest.mark.parametrize("on_server, episode, req_primary, tv, first", [
    (False, None, True, True, True),       # the TV request page: the one place
    (True, None, True, True, False),       # an on-server title (a show with no Play) keeps the normal first focus
    (False, {"code": "S1E1"}, True, True, False),
    (False, None, False, True, False),     # Request beside Play (under More) is never first
    (False, None, True, False, False),     # off the TV
])
def test_data_first_is_only_on_the_tv_request_page(monkeypatch, on_server, episode, req_primary, tv, first):
    html = render_block(on_server, episode, req_primary, tv, monkeypatch)
    assert (">Request</a>" in html) and (("data-first" in html) is first)


def test_request_route_fragments_never_carry_data_first(friend):
    for step in ("idle", "confirm"):
        r = friend.get(f"/media/title/movie/701/request?step={step}", headers={**TV, "HX-Request": "true"})
        assert r.status_code == 200 and "data-first" not in r.text, step


def test_household_front_tv_title_pages_are_unchanged(env):
    """The private (household) front ignores the TV user agent and cookie (tv_mode is media-front only), so the guest
    gate keeps its title pages exactly as before: Similar / Recommended with their words, no request page."""
    from tests.hub.conftest import main_of
    client, _ = env()
    with client:
        for url in ("/media/title/movie/603", "/media/title/movie/701"):
            whole(client, url)   # warm: both renders below then draw from the same caches
            plain = main_of(whole(client, url))
            client.cookies.set("tv", "1")
            tv = main_of(page(client, url, tv=True))
            client.cookies.delete("tv")
            assert tv == plain, url
            assert "More on Joey" not in tv and "tv-reqpage" not in tv and "data-first" not in tv and "tv-back" not in tv
        assert "Similar" in main_of(whole(client, "/media/title/movie/603"))
