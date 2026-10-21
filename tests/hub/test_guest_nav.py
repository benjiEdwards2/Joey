"""Joey TV WP-B3 step 1 (2026-10-21): the guest front's nav and branding. On the media front the guest sees exactly
Overview / Movies / TV shows / Diary / Discover (the WP-M signed-off section row), each with only the sub-tabs
hub.guest.allows() serves; the Joey brand, the area pills and the Hub / Weather tab bar never render there - not on a
page, not on the 404 page, not on /signin (WP-B1 step 5's leftover nav leak). Branding is "Joey Media" + the kangaroo,
page titles read "<page> · Joey Media" (Q32), the user chip carries the name only (no email), the guest manifest offers
Movies / TV Shows / Discover only. Awards renders without Seen marks or the Not seen chip (Q20: no played state for
friends in v1). The private front is unchanged (tests/hub/test_media_nav.py, test_media_phone_nav.py)."""
import json
import re
from contextlib import closing
from types import SimpleNamespace

import pytest

from hub import guest, media_awards_db as adb, media_awards_pages as ap, media_db, media_nav, shell
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import guest_client, links_of, sign_in
from tests.hub.test_awards_db import seed_oscars

FRIEND = "jf:" + FRIEND_ID
PRIVATE_PREFIXES = ("/a/calendar", "/money", "/server", "/weather", "/whoami", "/media/playing", "/media/library",
                    "/media/downloads", "/media/requests", "/media/apps", "/media/server", "/media/following")


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        c.fake = fake
        yield c


@pytest.fixture()
def friend(gc):
    sign_in(gc, gc.fake, FRIEND_ID)
    return gc


def nav_at(path: str) -> dict:
    request = SimpleNamespace(url=SimpleNamespace(path=path), state=SimpleNamespace())
    return media_nav.nav_context(request, shell.registry, {})


def same_origin_paths(html: str) -> list[str]:
    return [u.partition("?")[0].partition("#")[0] for _, u, _ in links_of(html) if u.startswith("/")]


def assert_no_private_link(html: str, where: str) -> None:
    paths = same_origin_paths(html)
    assert "/" not in paths, where
    bad = [p for p in paths if p.startswith(PRIVATE_PREFIXES)]
    assert not bad, (where, bad)


# ---- sections and tabs (the exact lists) ----

def test_nav_sections_and_tabs_on_the_media_front(gc):
    nav = nav_at("/media/movies")
    assert [s["id"] for s in nav["sections"]] == ["home", "movies", "tv", "diary", "discover"]
    assert [s["label"] for s in nav["sections"]] == ["Overview", "Movies", "TV shows", "Diary", "Discover"]
    assert [t["label"] for t in nav["tabs"]] == ["My films", "Watchlist", "Tonight", "To rate", "Awards"]
    assert [t["label"] for t in nav_at("/media/tv")["tabs"]] == ["My shows", "Watchlist", "Tonight", "To rate", "Awards"]
    assert [t["label"] for t in nav_at("/media/discover")["tabs"]] == ["Discover"]   # Following hidden (Q19)
    diary = nav_at("/media/diary")
    assert diary["section"]["id"] == "diary" and [t["label"] for t in diary["tabs"]] == ["Diary", "To rate"]
    assert nav_at("/media/history")["section"]["id"] == "diary"
    assert {s["id"]: s["href"] for s in nav["sections"]}["diary"] == "/media/diary"
    for s in nav["sections"]:   # every section and tab the media front draws is a page it serves
        assert guest.href_allowed(s["href"]), s
    for path in ("/media/movies", "/media/tv", "/media/discover", "/media/diary"):
        assert all(guest.href_allowed(t["href"]) for t in nav_at(path)["tabs"]), path


def test_private_front_sections_are_unchanged(monkeypatch, gc):
    monkeypatch.setenv("JOEY_FRONT", "private")
    assert [s["id"] for s in nav_at("/media/movies")["sections"]] == ["home", "movies", "tv", "server", "discover"]
    assert [t["label"] for t in nav_at("/media/discover")["tabs"]] == ["Discover", "Following"]


def test_the_page_draws_the_guest_section_row_and_tabs(friend):
    html = friend.get("/media/movies").text
    row = re.search(r'<nav class="sectabs sectabs-page"[^>]*>(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r">([^<]+)</a>", row) == ["Overview", "Movies", "TV shows", "Diary", "Discover"]
    sub = re.search(r'<nav class="sectabs sub"[^>]*>(.*?)</nav>', html, re.S).group(1)
    assert [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<a [^>]*>(.*?)</a>", sub, re.S)] == \
        ["My films", "Watchlist", "Tonight", "To rate", "Awards"]
    phone = re.search(r'<nav class="tabbar"[^>]*>(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r'href="([^"]+)"', phone) == ["/a/media", "/media/movies", "/media/tv", "/media/diary",
                                                     "/media/discover"]


# ---- branding, home, 404, sign-in ----

def test_guest_home_has_no_hub_weather_or_server_link(friend):
    r = friend.get(guest.home_path())
    assert r.status_code == 200
    assert 'href="/"' not in r.text and "/weather" not in r.text and 'href="/server' not in r.text
    assert_no_private_link(r.text, "home")


def test_branding_title_home_meta_manifest_and_user_chip(friend):
    html = friend.get("/media/movies").text
    head = html.split("</head>", 1)[0]
    assert '<meta name="joey-home" content="/a/media">' in head
    assert 'href="/static/manifest-guest.webmanifest"' in head and "manifest-media" not in head
    assert re.search(r"<title>[^<]* · Joey Media</title>", head), re.search(r"<title>.*?</title>", head).group(0)
    top = re.search(r'<header class="topbar">(.*?)</header>', html, re.S).group(1)
    brand = re.search(r'<a class="brand"[^>]*>.*?</a>', top, re.S).group(0)
    assert 'href="/a/media"' in brand and "Joey Media" in brand and "/static/icon-192.png" in brand
    assert "brand-back" not in brand and "brand-joey" not in brand        # no "‹ Joey" (DECISIONS C)
    chip = re.search(r'<div class="userchip".*?</div>', top, re.S).group(0)
    assert "Sample Friend" in chip and "@" not in chip and "Local preview" not in chip and "title=" not in chip
    assert '<nav class="toplinks" aria-label="Sections">' not in html        # no Joey area pills


@pytest.mark.parametrize("path", ["/no-such-page", "/server", "/a/calendar"])
def test_the_404_page_lists_no_private_area_and_goes_back_to_joey_media(gc, path):
    r = gc.get(path)
    assert r.status_code == 404
    assert_no_private_link(r.text, path)
    assert "Back to Joey Media" in r.text and "Back to Hub" not in r.text
    assert re.search(r"<title>[^<]* · Joey Media</title>", r.text)


def test_the_signin_page_lists_no_private_area(gc):
    r = gc.get("/signin")
    assert r.status_code == 200
    assert_no_private_link(r.text, "/signin")
    assert "manifest-guest.webmanifest" in r.text


def test_guest_manifest_offers_movies_tv_and_discover_only(gc):
    r = gc.get("/static/manifest-guest.webmanifest")
    assert r.status_code == 200
    m = json.loads(r.text)
    assert m["name"] == "Joey Media" and m["start_url"] == guest.home_path()
    assert [s["name"] for s in m["shortcuts"]] == ["Movies", "TV Shows", "Discover"]
    assert all(guest.href_allowed(s["url"]) for s in m["shortcuts"])
    assert all(i["src"].startswith("/static/") for i in m["icons"])


def test_private_front_keeps_joey_branding(monkeypatch, tmp_path):
    from tests.hub.guest_pages import guest_client as gcl
    client, _ = gcl(monkeypatch, tmp_path)
    monkeypatch.setenv("JOEY_FRONT", "private")
    with client as c:
        html = c.get("/media/movies").text
    assert "manifest-media.webmanifest" in html and "joey-home" not in html
    assert re.search(r"<title>[^<]* · Joey</title>", html)


# ---- Awards (Q20: no Seen marks for friends in v1) ----

def test_awards_has_no_seen_marks_or_not_seen_chip_for_a_friend(friend):
    with closing(adb.ensure()) as db:
        seed_oscars(db)
    media_db.add_manual_watch("tmdb:11", "movie", "Alpha", watched_on="2026-10-20", owner=FRIEND)   # the friend saw it
    c = ap.awards_ctx("movie", "", "", False, {}, FRIEND)[0]
    ballot = c["ballot"]
    assert ballot["rows"] and not any(r["seen"] for r in ballot["rows"])
    assert "unseen" not in [f["key"] for f in ballot["filters"]] and ballot["progress"] is None
    cats = ap.awards_ctx("movie", "", "", False, {}, FRIEND, v="categories")[0]
    assert not any(x["seen"] for cat in cats["cats"] for x in cat["cards"])
    html = friend.get("/media/movies/awards").text
    main = html.split("<main", 1)[1]
    assert "Not seen" not in main and "Seen ✓" not in main and "Seen 0 of" not in main
    assert "Alpha" in main


def test_awards_seen_marks_stay_on_the_private_front(monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "private")
    with closing(adb.ensure()) as db:
        seed_oscars(db)
    media_db.add_manual_watch("tmdb:11", "movie", "Alpha", watched_on="2026-10-20", owner="you")
    ballot = ap.awards_ctx("movie", "", "", False, {}, "you")[0]["ballot"]
    assert any(r["seen"] for r in ballot["rows"]) and "unseen" in [f["key"] for f in ballot["filters"]]
