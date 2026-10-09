"""media-ux5 item 1 (2026-10-09): on desktop the Media section row docks into the top bar once it scrolls under it.
The docked copy is rendered server-side inside the top bar on Media pages only (same sections, counts and active
section as the page's own row), the row carries the sentinel, base.html carries the observer, CSS does the swap."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.conftest import shell_script
from tests.hub.test_media_frame import env, ROUTES, LABELS  # noqa: F401  (env is a fixture)
from tests.hub.test_media_shelves import JELLY, ARR

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
    assert counts(d) == counts(row) and counts(d)                  # Movies / TV "to place" badges


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
