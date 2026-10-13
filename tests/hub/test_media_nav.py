"""nav-tidy items 1, 3, 7 (B., 2026-10-13; supersedes media-ux5 item 1's scroll-docking): inside Media the top bar is
docked from the start, permanently — brand + the Media section row (the active section aria-current="page", the filled
pill) + user chip, and NO Joey section pills. The in-page section row carries .sectabs-page (hidden from 768 px); the
scroll-docking machinery (sentinel, .is-docked, the observer) is gone. Non-Media pages keep the Joey pills."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import media_nav
from tests.hub.conftest import shell_script
from tests.hub.helpers import ARR, JELLY
from tests.hub.test_media_frame import current, env, LABELS, nav_html, ROUTES  # noqa: F401


CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
PAGE_ROW = r'<nav class="sectabs sectabs-page" aria-label="Media sections">.*?</nav>'


def topbar(html):
    return re.search(r'<header class="topbar">.*?</header>', html, re.S).group(0)


def media_row(html):
    found = re.findall(r'<nav class="toplinks" aria-label="Media sections">(.*?)</nav>', topbar(html), re.S)
    assert len(found) == 1
    return found[0]


def links(nav):
    return re.findall(r'<a href="([^"]+)"([^>]*)>([^<]*?)(?: <span|</a>)', nav)


@pytest.mark.parametrize("route", list(ROUTES))
def test_media_pages_render_the_media_row_in_the_top_bar_without_joey_pills(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    bar = topbar(html)
    assert 'aria-label="Sections"' not in bar and "topswap" not in bar and "topdock" not in bar   # no Joey pills
    assert bar.index('class="brand"') < bar.index('aria-label="Media sections"') < bar.index("userchip")
    got = links(media_row(html))
    assert [label for _, _, label in got] == list(LABELS.values())
    on = [label for _, attrs, label in got if 'aria-current="page"' in attrs]
    assert on == [LABELS[ROUTES[route][0]]]                       # the active section carries aria-current
    assert bar.count("aria-current") == 1                         # ... and the bar has exactly one
    assert 'class="on"' not in bar
    assert '<a class="brand" href="/" aria-label="Joey home">' in bar  # brand stays: Joey home is the way out


def test_media_row_in_the_bar_carries_the_same_hrefs_and_counts_as_the_page_row(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get("/media/movies").text
    row = re.search(PAGE_ROW, html, re.S).group(0)
    d = media_row(html)
    assert [h for h, _, _ in links(d)] == [h for h, _, _ in links(row)]
    counts = lambda s: re.findall(r'<span class="waitcount">(\d+)<span class="vh"> ([a-z ]+)</span>', s)
    assert counts(d) == counts(row)


@pytest.mark.parametrize("route", list(ROUTES))
def test_page_section_row_carries_the_hide_class_and_the_sub_row_does_not(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    assert html.count('class="sectabs sectabs-page"') == 1
    assert re.search(PAGE_ROW, html, re.S)
    assert "sectabs-page" not in re.sub(PAGE_ROW, "", html, flags=re.S)   # the sub-tab row (if any) never carries it
    assert "dock-sentinel" not in html


@pytest.mark.parametrize("route", ["/", "/a/beta", "/weather"])
def test_non_media_pages_keep_the_joey_pills_and_have_no_media_row(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        html = c.get(route).text
    bar = topbar(html)
    assert '<nav class="toplinks" aria-label="Sections">' in bar and "Media sections" not in bar
    body = html.split("</head>", 1)[1]
    assert "topdock" not in body and "topswap" not in body and "dock-sentinel" not in body


def test_joey_pills_on_a_media_page_are_not_rendered_at_all(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        media = topbar(c.get("/media/movies").text)
        hub = topbar(c.get("/").text)
    assert '<a href="/weather"' in hub and '<a href="/weather"' not in media


def test_scroll_docking_script_is_gone(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        script = shell_script(c, c.get("/media/movies").text)   # H-57: /static/joey.js
    assert "IntersectionObserver" not in script and "dock-sentinel" not in script and "is-docked" not in script


def test_bar_css_is_plain_and_the_docking_css_is_gone():
    for gone in (".topswap", ".topdock", ".is-docked", ".dock-sentinel"):
        assert gone not in CSS, gone
    assert ".toplinks a[aria-current] { background: var(--pill-on); color: var(--text-1); }" in CSS
    assert ".toplinks { display: none; }" in CSS                      # phone: neither pills nor Media row in the bar
    assert ".topbar-in { display: flex; align-items: center; gap: 16px; height: 56px;" in CSS
    assert ".toplinks { display: flex; gap: 4px; min-width: 0; overflow: hidden; }" in CSS   # no wrap


def test_page_section_row_is_hidden_from_768_and_the_sub_row_is_underlined_not_pilled():
    head, _, tail = CSS.partition("@media (min-width: 768px) {\n  .sectabs-row {")
    assert tail
    block = tail.split("\n}\n", 1)[0]
    assert "  .sectabs-page { display: none; }" in block
    assert ".sectabs a[aria-current] { color: var(--text-1); background: none; border-bottom-color: var(--tab-on); }" in block
    assert ".sectabs-row a:first-child { padding-left: 0; }" in block   # first tab flush with the page column
    assert ".sectabs-page {" not in head                                 # visible below 768 px (phone pills stay)


def test_waitcount_has_a_fixed_box():
    rule = " ".join(re.findall(r"(?m)^\.waitcount \{([^}]*)\}", CSS))
    assert "height: 18px;" in rule and "min-width: 18px;" in rule and "margin-left: 6px;" in rule
    assert "font-variant-numeric: tabular-nums;" in rule
    assert ".topdock .waitcount" not in CSS and not re.search(r"\.sectabs a \{[^}]*\bgap:", CSS)   # one margin, no doubled gap


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
    assert tabs["movies"] == ["My films", "Watchlist", "Tonight", "To Rate", "Awards"]   # media-ux4: + To rate; 2026-10-08: + Awards
    assert tabs["tv"] == ["My shows", "Watchlist", "Tonight", "To Rate", "Awards"]
    assert not [h for s in media_nav.SECTIONS for _, h in s["tabs"] if h.startswith("/media/years")]


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
