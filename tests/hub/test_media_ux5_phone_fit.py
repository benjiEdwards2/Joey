"""media-ux5 items 2 + 4 (2026-10-09): on a phone nothing is wider than the screen and the bottom bar stays put.
Phone library grids are exactly three minmax(0, 1fr) columns, grid children may shrink, html + body clip sideways
overflow (clip, never hidden: sticky must keep working), and the fixed tab bar is a direct child of <body> with no
transformed / filtered ancestor. Browser measurements (320/375/390/430 px) are in the media-ux5 report."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.test_media_frame import env  # noqa: F401  (env is a fixture)
from tests.hub.helpers import ARR, JELLY

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


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
