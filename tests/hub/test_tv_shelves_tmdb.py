"""JY-193 (U7; TV_UI_EVALUATION P2, D1, N1; B.'s Gate 1 pick "2A", 2026-10-25): on the friends' TV, title-page shelves
show on-server titles only (one "More on Joey" shelf), a title that is not on the server is a request page (Request
focused first, Back), and the person page has a TV layout with the on-server shelf only. Desktop / phone (TV mode
off) and the private front are unchanged. Seerr and Jellyfin are the fakes of tests/hub/fake_seerr.py and
fake_jellyfin.py; no network."""
import re
from pathlib import Path

import pytest

from hub import media_person
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.fake_seerr import res
from tests.hub.film_page import whole
from tests.hub.guest_pages import TV_UA, sign_in
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


def test_tv_page_makes_no_more_upstream_calls_than_the_phone_page(friend):
    page(friend, "/media/title/movie/603", tv=False)
    page(friend, "/media/title/movie/701", tv=False)
    friend.seerr.calls.clear()
    page(friend, "/media/title/movie/603", tv=False)
    page(friend, "/media/title/movie/701", tv=False)
    phone = sorted(c[1] for c in friend.seerr.calls)
    friend.seerr.calls.clear()
    page(friend, "/media/title/movie/603", tv=True)
    page(friend, "/media/title/movie/701", tv=True)
    assert sorted(c[1] for c in friend.seerr.calls) == phone


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
