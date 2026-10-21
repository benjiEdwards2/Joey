"""Joey TV WP-B3 step 6 (2026-10-21; Q34, Q41, D-P8, DECISIONS D): TV mode.

`tv_mode(request)` is true ONLY on the media front, when the user agent carries the shell's token `JoeyTV/` (D-P8:
` JoeyTV/<semver> (<versionCode>)`) or the `tv=1` cookie is present; `?tv=1` sets that cookie (1 year, SameSite=Lax)
and `?tv=0` clears it - handled in GuestGate, so it works on every media-front page, the 404 page and /signin. In TV
mode `<html>` carries class `tv` and the page links /static/tv.css + /static/tv.js (vendored, no external asset). The
private front ignores all of it. tv.js exposes `window.joeyTV.back()` (the shell's BackPolicy asks it first, WP-B7)."""
import re

import pytest

from hub import guest
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import TV_UA, guest_client, sign_in


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def is_tv(html: str) -> bool:
    head = html.split("</head>", 1)[0]
    on = bool(re.search(r'<html lang="en" class="tv"', html))
    assets = bool(re.search(r'href="/static/tv\.css\?v=\w+"', head)) and bool(re.search(r'src="/static/tv\.js\?v=\w+"', head))
    assert on == assets, "class tv and the TV assets go together"
    return on


def tv_cookie(r) -> list[str]:
    return [h for h in r.headers.get_list("set-cookie") if h.startswith("tv=")]


@pytest.mark.parametrize("path", ["/a/media", "/media/movies", "/no-such-page", "/signin"])
def test_ua_and_cookie_triggers(gc, path):
    assert not is_tv(gc.get(path).text)
    assert is_tv(gc.get(path, headers={"User-Agent": TV_UA}).text), path
    gc.cookies.set("tv", "1")
    assert is_tv(gc.get(path).text), path


def test_query_sets_and_clears_the_cookie(gc):
    r = gc.get("/media/movies?tv=1")
    assert is_tv(r.text)
    (line,) = tv_cookie(r)
    assert line.startswith("tv=1;") and "Max-Age=31536000" in line and "Path=/" in line and "SameSite=Lax" in line
    assert is_tv(gc.get("/media/tv").text)                      # persists
    r = gc.get("/media/tv?tv=0")
    assert not is_tv(r.text)
    (line,) = tv_cookie(r)
    assert line.startswith("tv=;") and "Max-Age=0" in line
    assert not is_tv(gc.get("/media/movies").text)              # cleared


def test_the_query_works_before_sign_in(monkeypatch, tmp_path):
    client, _ = guest_client(monkeypatch, tmp_path)
    with client as c:
        r = c.get("/signin?tv=1")
        assert is_tv(r.text) and tv_cookie(r)
        redirect = c.get("/media/movies?tv=1", follow_redirects=False)
        assert redirect.status_code == 303 and tv_cookie(redirect)


def test_the_private_front_ignores_tv_mode(monkeypatch, tmp_path):
    client, _ = guest_client(monkeypatch, tmp_path)
    monkeypatch.setenv("JOEY_FRONT", "private")
    with client as c:
        c.cookies.set("tv", "1")
        r = c.get("/media/movies?tv=1", headers={"User-Agent": TV_UA})
    assert not is_tv(r.text) and not tv_cookie(r)


def test_the_tv_assets_are_served_and_self_contained(gc):
    js = gc.get("/static/tv.js")
    css = gc.get("/static/tv.css")
    assert js.status_code == 200 and css.status_code == 200
    assert "window.joeyTV" in js.text and "back" in js.text
    for body in (js.text, css.text):
        assert not re.search(r"https?://", body.replace("http://www.w3.org/", "")), "no external asset"
        assert "@import" not in body


def test_tv_token_is_the_frozen_substring():
    assert guest.TV_UA_TOKEN == "JoeyTV/" and guest.TV_UA_TOKEN in TV_UA
