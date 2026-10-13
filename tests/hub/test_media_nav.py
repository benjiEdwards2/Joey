"""media-ux5 item 1 (2026-10-09): on desktop the Media section row docks into the top bar once it scrolls under it.
The docked copy is rendered server-side inside the top bar on Media pages only (same sections, counts and active
section as the page's own row), the row carries the sentinel, base.html carries the observer, CSS does the swap."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hub import media_nav
from tests.hub.conftest import shell_script
from tests.hub.helpers import ARR, JELLY
from tests.hub.test_media_frame import current, env, LABELS, nav_html, ROUTES  # noqa: F401


CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def topbar(html):
    return re.search(r'<header class="topbar">.*?</header>', html, re.S).group(0)


def dock(html):
    found = re.findall(r'<nav class="toplinks topdock" aria-label="Media sections \(docked\)">(.*?)</nav>', topbar(html), re.S)
    assert len(found) == 1
    return found[0]


def links(nav):
    return re.findall(r'<a href="([^"]+)"([^>]*)>([^<]*?)(?: <span|</a>)', nav)


@pytest.mark.parametrize("route", list(ROUTES))
def test_media_pages_render_the_docked_row_in_the_top_bar(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    bar = topbar(html)
    assert '<div class="topswap">' in bar
    assert bar.index('<nav class="toplinks" aria-label="Sections">') < bar.index("topdock") < bar.index("userchip")
    got = links(dock(html))
    assert [label for _, _, label in got] == list(LABELS.values())
    on = [label for _, attrs, label in got if 'class="on"' in attrs]
    assert on == [LABELS[ROUTES[route][0]]]                       # the active section carried across
    assert "aria-current" not in dock(html)                        # the bar keeps ONE aria-current (its Media pill)
    assert '<a class="brand" href="/" aria-label="Joey home">' in bar  # brand stays: Joey home is one click


def test_docked_row_carries_the_same_hrefs_and_counts_as_the_section_row(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get("/media/movies").text
    row = re.search(r'<nav class="sectabs" aria-label="Media sections">.*?</nav>', html, re.S).group(0)
    d = dock(html)
    assert [h for h, _, _ in links(d)] == [h for h, _, _ in links(row)]
    counts = lambda s: re.findall(r'<span class="waitcount">(\d+)<span class="vh"> ([a-z ]+)</span>', s)
    assert counts(d) == counts(row)


@pytest.mark.parametrize("route", list(ROUTES))
def test_section_row_carries_the_sentinel_once(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    row = re.search(r'<nav class="sectabs" aria-label="Media sections">.*?</nav>', html, re.S).group(0)
    assert html.count('class="dock-sentinel"') == 1
    assert '<span class="dock-sentinel" aria-hidden="true"></span>' in row


@pytest.mark.parametrize("route", ["/", "/a/beta", "/weather"])
def test_non_media_pages_have_no_dock(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    body = html.split("</head>", 1)[1]
    assert "topdock" not in body and "topswap" not in body and "dock-sentinel" not in body


def test_observer_script_hook_in_base(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        script = shell_script(c, c.get("/media/movies").text)   # H-57: /static/joey.js
    assert "new IntersectionObserver(" in script and "document.querySelector('.dock-sentinel')" in script
    assert "bar.classList.toggle('is-docked'" in script
    assert "addEventListener('htmx:afterSettle', init)" in script and "addEventListener('htmx:load', init)" in script
    assert "rootMargin: '-56px 0px 0px 0px'" in script            # the 56 px sticky bar


def test_dock_css_swaps_in_one_cell_with_reduced_motion():
    assert ".topswap { display: none; }" in CSS                    # phone: no dock, the bottom bar stays
    m = re.search(r"@media \(min-width: 768px\) \{\n  \.topswap \{ display: grid;.*?\n\}\n", CSS, re.S)
    assert m and "grid-area: 1 / 1" in m.group(0)                  # pills and dock share a cell: no height change
    assert ".topbar.is-docked .topswap > .topdock { visibility: visible; opacity: 1; transform: none;" in m.group(0)
    assert ".topbar.is-docked .topswap > .toplinks:not(.topdock) { visibility: hidden; opacity: 0;" in m.group(0)
    rm = re.search(r"@media \(prefers-reduced-motion: reduce\) \{\n  \.topbar \.topswap > \.toplinks.*?\}\n\}", CSS, re.S)
    assert rm and "transition: none; transform: none;" in rm.group(0)
    assert ".dock-sentinel { display: block; height: 1px; margin-top: -1px;" in CSS


# ---- merged from test_media_ux5_no_zoom.py ----
# media-ux5 item 5 (B.'s explicit choice, 2026-10-09): zoom kept getting stuck on the iPhone, so the page cannot zoom.
# Viewport meta forbids scaling (viewport-fit=cover kept), CSS turns off double-tap zoom and text inflation and gives
# every form control 16 px on a phone (iOS zooms in on focus below 16 px), and base.html cancels Safari's pinch events
# (Safari ignores user-scalable=no). The accessibility trade-off is documented in hub/README.md.


ROOT = Path(__file__).resolve().parents[2]
CSS_ux5_no_zoom = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
META = ('<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, '
        'viewport-fit=cover">')


@pytest.mark.parametrize("route", ["/", "/a/alpha", "/media/movies", "/media/diary", "/weather"])
def test_viewport_meta_forbids_zoom_on_every_page(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        head = c.get(route).text.split("</head>", 1)[0]
    assert re.findall(r'<meta name="viewport"[^>]*>', head) == [META]


def test_css_turns_off_double_tap_zoom_and_text_inflation():
    assert "html { touch-action: manipulation; -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }" in CSS_ux5_no_zoom


def test_form_controls_are_16px_on_a_phone_after_the_base_rules():
    rule = "@media (max-width: 767px) { input, select, textarea, .input, .select { font-size: 16px; } }"
    assert rule in CSS_ux5_no_zoom
    # the phone rule must come AFTER the 14 px .input / .select rules or they would win
    assert CSS_ux5_no_zoom.index(rule) > CSS_ux5_no_zoom.index(".input { width: 100%;") and CSS_ux5_no_zoom.index(rule) > CSS_ux5_no_zoom.index(".select { height: 36px;")
    after = CSS_ux5_no_zoom[CSS_ux5_no_zoom.index(rule) + len(rule):]
    assert not re.search(r"(?:input|select|textarea|\.input|\.select|\.textarea)[^{}]*\{[^}]*font-size", after)


def test_base_cancels_safari_pinch_gestures(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        head = shell_script(c, c.get("/media/movies").text)   # H-57: /static/joey.js
    assert "['gesturestart', 'gesturechange'].forEach(function (t) {" in head
    assert "document.addEventListener(t, function (e) { e.preventDefault(); }, {passive: false});" in head


def test_trade_off_documented():
    readme = (ROOT / "hub" / "README.md").read_text(encoding="utf-8")
    assert "No zoom (media-ux5" in readme and "accessibility" in readme and "2026-10-09" in readme


# ---- merged from test_media_ux5_phone_fit.py ----
# media-ux5 items 2 + 4 (2026-10-09): on a phone nothing is wider than the screen and the bottom bar stays put.
# Phone library grids are exactly three minmax(0, 1fr) columns, grid children may shrink, html + body clip sideways
# overflow (clip, never hidden: sticky must keep working), and the fixed tab bar is a direct child of <body> with no
# transformed / filtered ancestor. Browser measurements (320/375/390/430 px) are in the media-ux5 report.


def rules(selector):
    """Every declaration block whose selector list is exactly `selector` (any media query)."""
    return re.findall(r"(?:^|[}\n]\s*)" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)


def test_phone_library_grid_is_three_shrinkable_columns():
    assert ("@media (max-width: 639px) { .poster-grid.libgrid { grid-template-columns: repeat(3, minmax(0, 1fr)); "
            "gap: 16px 10px; } }") in CSS
    assert ".poster-grid > *, .awnoms > * { min-width: 0; }" in CSS
    assert ".poster-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));" in CSS
    # 320 px page: 16 px gutters, so 288 px for three columns and two 10 px gaps
    assert 3 * ((320 - 32 - 2 * 10) / 3) + 2 * 10 <= 288


def test_posters_scale_to_their_column():
    for sel in (".card-poster img", ".card-pic > img, .card-cell .card-pic > img"):
        block = " ".join(rules(sel))
        assert "width: 100%" in block and "height: auto" in block and "aspect-ratio: 2 / 3" in block


def test_html_and_body_clip_sideways_overflow_without_hidden():
    assert "html { overflow-x: clip; }" in CSS
    body = " ".join(rules("body"))
    assert "overflow-x: clip;" in body
    for sel in ("html", "body"):
        block = " ".join(rules(sel))
        assert "overflow-x: hidden" not in block and "overflow: hidden" not in block


def test_long_titles_and_chip_rows_cannot_widen_the_page():
    assert "text-overflow: ellipsis; white-space: nowrap;" in " ".join(rules(".row-title"))
    assert "flex-wrap: wrap" in " ".join(rules(".chips")) and "flex-wrap: wrap" in " ".join(rules(".toolbar"))
    assert "overflow-x: auto" in " ".join(rules(".sectabs")) and "overflow-x: auto" in " ".join(rules(".carousel"))


def test_tab_bar_is_fixed_to_the_screen_edges():
    bar = " ".join(rules(".tabbar"))
    assert "position: fixed; left: 0; right: 0; bottom: 0;" in bar
    assert "padding-bottom: calc(env(safe-area-inset-bottom) + var(--tab-lift));" in bar
    page = " ".join(rules(".page"))
    assert "calc(7rem + env(safe-area-inset-bottom))" in page        # content clears the bar
    for sel in ("html", "body", ".page"):                             # no ancestor that re-anchors position: fixed
        block = " ".join(rules(sel))
        assert "transform" not in block and "filter" not in block and "contain:" not in block


@pytest.mark.parametrize("route", ["/a/alpha", "/media/movies", "/media/discover", "/", "/weather"])
def test_tab_bar_is_a_direct_child_of_body(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    body = html.split("</head>", 1)[1]
    after_main = body.split("</main>", 1)[1]
    assert re.match(r'\s*(?:\{#.*?#\}\s*)?<nav class="tabbar"', after_main, re.S)   # straight after </main>
    assert after_main.split("</nav>")[-1].strip().startswith("</body>") or "</body>" in after_main
    opened = body.split('<nav class="tabbar"', 1)[0]
    assert opened.count("<main") == opened.count("</main>") == 1      # not nested inside the page frame


# ---- merged from test_media_nav_ux2.py ----
# media-ux2 item 3 (2026-10-08): "By year" is gone from the Movies and TV Shows tab rows.
# By-year rankings removed 2026-10-09 (decision 1): /media/years and its pages are gone (404).


def test_movies_and_tv_tabs_have_no_by_year():
    tabs = {s["id"]: [label for label, _ in s["tabs"]] for s in media_nav.SECTIONS}
    assert tabs["movies"] == ["My films", "To rate", "Awards"]   # nav-tidy (2026-10-13): Watchlist + Tonight left the nav
    assert tabs["tv"] == ["My shows", "To rate", "Awards"]
    assert not [h for s in media_nav.SECTIONS for _, h in s["tabs"] if h.startswith("/media/years")]


# ---- nav-tidy (2026-10-13, B.): five sections, Diary folded into Activity, sentence-case labels ----

def test_five_sections_and_no_diary():
    assert [(s["id"], s["label"], s["short"]) for s in media_nav.SECTIONS] == [
        ("home", "Overview", "Overview"), ("movies", "Movies", "Movies"), ("tv", "TV shows", "TV"),
        ("server", "Activity", "Activity"), ("discover", "Discover", "Discover")]
    home = media_nav.SECTIONS[0]
    assert (home["icon"], home["href"]) == ("house", None)   # Overview: label only, id / href / icon unchanged


def test_movies_and_tv_have_exactly_three_tabs():
    tabs = {s["id"]: s["tabs"] for s in media_nav.SECTIONS}
    assert tabs["movies"] == [("My films", "/media/movies"), ("To rate", "/media/movies/to-rate"), ("Awards", "/media/movies/awards")]
    assert tabs["tv"] == [("My shows", "/media/tv"), ("To rate", "/media/tv/to-rate"), ("Awards", "/media/tv/awards")]


def test_activity_has_seven_tabs_with_history_on_the_diary():
    server = next(s for s in media_nav.SECTIONS if s["id"] == "server")
    assert server["tabs"] == [("Live", "/media/playing"), ("History", "/media/diary"), ("To rate", "/media/history"),
                              ("Library", "/media/library"), ("Downloads", "/media/downloads"),
                              ("Requests", "/media/requests"), ("Health", "/media/apps")]
    assert {"/media/diary", "/media/history"} <= set(server["prefixes"])
    assert not [h for s in media_nav.SECTIONS for _, h in s["tabs"] if h == "/media/server/history"]   # play stats: no tab


def test_every_section_and_tab_label_is_sentence_case():
    """docs/style-guide.md: sentence case for labels; "TV" stays an acronym."""
    labels = [s["label"] for s in media_nav.SECTIONS] + [label for s in media_nav.SECTIONS for label, _ in s["tabs"]]
    for label in labels:
        words = label.split()
        assert words[0] == "TV" or (words[0][0].isupper() and words[0][1:] == words[0][1:].lower()), label
        assert all(w == "TV" or w == w.lower() for w in words[1:]), label


def test_to_rate_count_sits_on_activity_and_its_to_rate_tab():
    req = SimpleNamespace(url=SimpleNamespace(path="/media/history", query=""))
    reg = SimpleNamespace(areas=[SimpleNamespace(layout="shelves", id="alpha")])
    ctx = media_nav.nav_context(req, reg, {"to_rate": 3, "to_rate_movie": 2, "to_rate_tv": 1})
    assert {s["id"]: s["count"] for s in ctx["sections"]} == {"home": 0, "movies": 0, "tv": 0, "server": 3, "discover": 0}
    tabs = {t["href"]: (t["label"], t["on"], t["count"], t["what"]) for t in ctx["tabs"]}
    assert tabs["/media/history"] == ("To rate", True, 3, "to rate")
    assert tabs["/media/diary"] == ("History", False, 0, "to get")
    movies = media_nav.nav_context(SimpleNamespace(url=SimpleNamespace(path="/media/movies", query="")), reg,
                                   {"to_rate": 3, "to_rate_movie": 2, "to_rate_tv": 1})
    assert [(t["label"], t["count"], t["what"]) for t in movies["tabs"]] == [
        ("My films", 0, "to get"), ("To rate", 2, "to rate"), ("Awards", 0, "to get")]


def test_activity_section_shows_the_to_rate_count_on_the_page(env):
    main = env(jellyfin=JELLY, arr=ARR)   # the fixture history carries titles nobody has rated yet
    with TestClient(main.app) as c:
        html = c.get("/media/history").text
    row = nav_html(html, "sectabs")
    assert re.search(r'href="/media/playing"[^>]*>Activity <span class="waitcount">\d+<span class="vh"> to rate</span>', row)
    sub = nav_html(html, "sectabs sub")
    assert re.search(r'href="/media/history" aria-current="page">To rate <span class="waitcount">\d+', sub)
    assert "Diary" not in row


@pytest.mark.parametrize("route", ["/media/movies", "/media/tv", "/media/movies/tonight", "/media/tv/watchlist"])
def test_movies_tv_pages_link_nowhere_to_years(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    assert "By year" not in html and "/media/years" not in html


@pytest.mark.parametrize("route", ["/media/years", "/media/years/2020", "/media/years/2020/countdown"])
def test_years_pages_are_gone(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        assert c.get(route).status_code == 404
        assert c.post(route + "/reset", headers={"HX-Request": "true"}).status_code in (404, 405)
