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
from tests.hub.fake_seerr import FakeSeerr, res
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


# ---- the look (WP-B3 follow-on): tv.css is the WP-M mockup; none of it leaks into the shared sheet ----

def test_tv_css_has_no_hover_rule_and_keeps_the_floor(gc):
    css = re.sub(r"/\*.*?\*/", "", gc.get("/static/tv.css").text, flags=re.S)       # rules, not comments
    assert ":hover" not in css, "WP-M spec: no hover states anywhere in the TV UI"
    assert "(hover" not in css
    sizes = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", css)]
    assert sizes and min(sizes) >= 16, "WP-M spec: nothing under 16 px"
    assert re.search(r"\.brand b \{[^}]*font-size: 22px; font-weight: 700", css)        # brand text, 22 px bold
    assert "--tv-bar-fill: #f97316" in css                                              # the mockup's progress colour


def test_the_shared_sheet_carries_no_tv_rule(gc):
    shared = gc.get("/static/control-surface.css").text
    assert "html.tv" not in shared and ".tv-focus" not in shared
    assert gc.get("/static/control-surface.css", headers={"User-Agent": TV_UA}).text == shared   # TV mode adds a sheet, never edits one


def test_tv_overview_drops_the_head_band_and_paints_the_port(gc):
    plain = gc.get("/a/media").text
    tv = gc.get("/a/media", headers={"User-Agent": TV_UA}).text
    assert '<header class="pagehead">' in plain and '<header class="pagehead">' not in tv
    for html in (plain, tv):
        assert "<em>:8443</em>" in html and 'aria-label="Server address https://' in html and html.count("setup-addr") == 1


def test_tv_title_page_has_synopsis_and_rating_chips_only_in_tv_mode(gc):
    item = "f11f" * 8
    gc.fake.items[item] = {"Id": item, "Type": "Movie", "Name": "Chip Film", "ProductionYear": 2001,
                           "Overview": "A synopsis line.", "ProviderIds": {"Tmdb": "777"}, "RunTimeTicks": 100 * 600_000_000}
    plain = gc.get(f"/media/item/{item}").text
    tv = gc.get(f"/media/item/{item}", headers={"User-Agent": TV_UA}).text
    assert "tv-syn" not in plain and "tv-rate" not in plain and "Chip Film (2001)" in plain
    assert tv.count('name="score"') == 10 and "Your rating" in tv
    assert 'id="rate"' not in tv                                                         # no second picker below the fold
    assert 'class="tv-syn">A synopsis line.' in tv and "Chip Film (2001)" not in tv


def test_tv_discover_is_the_six_column_grid_with_chips_and_the_panel(monkeypatch, tmp_path):
    """WP-B4 follow-on: Discover in TV mode = WP-M screen 10. The grid takes tv.css's six-column helper, every poster has
    its chip, the panel is the dialog; the rules are tv.css's own (html.tv scope, no :hover) - the page carries none."""
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyseerr": {"summary": "x", "requests": []}})
    seerr = FakeSeerr().install(monkeypatch)
    seerr.add_user(7, FRIEND_ID)
    seerr.titles[("movie", 701)] = {**res(701, "Harvest Moon Rising"), "tagline": "", "genres": []}
    seerr.shelves = {"/api/v1/discover/trending": [res(701, "Harvest Moon Rising"), res(603, "Salt and Static", status=5),
                                                   res(702, "Pale Horizon", status=2)],
                     "/api/v1/discover/movies": [], "/api/v1/discover/tv": [],
                     "/api/v1/discover/movies/upcoming": [], "/api/v1/discover/tv/upcoming": []}
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        tv = c.get("/media/discover", headers={"User-Agent": TV_UA}).text
        assert is_tv(tv) and 'class="poster-grid reqgrid"' in tv
        for tid, word in (("movie-701", "Request"), ("movie-603", "In library"), ("movie-702", "Requested")):
            assert re.search(rf'id="chip-{tid}"[^>]*>{word}<', tv)
        assert '<dialog id="req-dialog"' in tv and "data-req-open" in tv
        inline = "".join(re.findall(r"<style>(.*?)</style>", tv, flags=re.S))
        assert "html.tv" not in inline and ":hover" not in inline          # the TV look lives in tv.css only
        css = re.sub(r"/\*.*?\*/", "", c.get("/static/tv.css").text, flags=re.S)
        assert re.search(r"\.poster-grid\.reqgrid \{ grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)", css)
        assert ".reqdlg" in css and ".reqchip" in css and ":hover" not in css
        # the answer keeps the poster / title / overview and says it is waiting (screen 10: Done focused)
        done = c.post("/media/title/movie/701/request", content="panel=1", headers={
            "HX-Request": "true", "content-type": "application/x-www-form-urlencoded"}).text
        assert "Requested — waiting for approval" in done and "Harvest Moon Rising" in done and "Overview of Harvest Moon Rising." in done
        assert re.search(r"<button[^>]*data-close data-first[^>]*>Done</button>", done)


def test_focus_growth_and_ring_stay_inside_the_overscan_margin(gc):
    """W5 2026-10-22 (real TCL): a focused poster (scale 1.06 + 4 px ring 3 px out) reached 96 % of the height and
    4.6 % from the left. tv.js now keeps room for that growth when it scrolls a row into view, and grows first/last
    column posters inward; its constants must match tv.css."""
    js = gc.get("/static/tv.js").text
    css = gc.get("/static/tv.css").text
    scale = float(re.search(r"\.card-poster\.tv-focus \{[^}]*transform: scale\(([\d.]+)\)", css).group(1))
    ring = re.search(r"\.card-poster\.tv-focus \.card-pic \{[^}]*outline: (\d+)px solid[^}]*outline-offset: (\d+)px", css)
    assert re.search(r"POSTER_GROW = ([\d.]+)", js) and abs(float(re.search(r"POSTER_GROW = ([\d.]+)", js).group(1))
                                                           - (scale - 1) / 2) < 1e-9
    assert int(re.search(r"RING = (\d+)", js).group(1)) == int(ring.group(1)) + int(ring.group(2))
    assert "var bottom = window.innerHeight - OVERSCAN_Y - grow;" in js and "PAD + grow" in js
    assert re.search(r"OVERSCAN_Y = 27, OVERSCAN_X = 48", js) and "--tv-mx: 48px; --tv-my: 27px" in css
    assert "transformOrigin = b.left - grow < OVERSCAN_X ? 'left center'" in js and "'right center'" in js
    assert js.index("centreInShelf(el);") < js.index("edgeOrigin(el);   /*") < js.index("keepRowInView(el);\n  }")
