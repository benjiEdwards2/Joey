"""F1 keep scroll (2026-10-12): controls that re-render the SAME page (awards ceremony / year / chips, the Movies and TV
toolbar) swap the boosted body with `show:none`, so the reader stays where they are; real navigation (section tabs,
phone bar, posters) keeps htmx's default boosted `show:top`."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.hub.test_awards_pages import ALPHA, jelly as awards_jelly, seeded  # noqa: F401
from tests.hub.test_media_frame import env  # noqa: F401
from tests.hub.test_media_library_pages import ARRV, jelly as lib_jelly
from tests.hub.test_media_rate import env as rate_env  # noqa: F401

KEEP = 'hx-swap="innerHTML show:none"'
ROOT = Path(__file__).resolve().parents[2]


def awards_html(rate_env):
    build, _ = rate_env
    seeded()
    with build(awards_jelly(ALPHA)) as client:
        return client.get("/media/movies/awards?body=oscars&year=2024").text


def test_awards_controls_keep_scroll():
    """Awards ballot (2026-10-14): ONE swap block, #awmain, carries `show:none` (picker, year, view, filter, sort links all
    swap it and keep the reader's place); rows, cards and the people strip leave it as ordinary navigation (to the top)."""
    from tests.hub.test_awards_ballot_templates import page
    p = page()
    assert re.search(r'<div id="awmain"[^>]*hx-swap="outerHTML show:none"', p)
    assert p.count("show:none") == 1                                         # only the block, nothing inside re-declares it
    assert p.count('hx-swap="innerHTML show:window:top"') >= 5               # 4 rows + the people strip leave #awmain
    assert "onchange=" not in p                                              # no inline handler
    # JY-270 years (B. 2026-10-30): one native year <select> beside the button, followed by joey.js (data-nav)
    assert p.count("<select") == 1 and '<select class="awyrsel" aria-label="Year" data-nav>' in p


def test_awards_posters_and_section_tabs_still_go_to_the_top(rate_env):
    html = awards_html(rate_env)
    assert html.count("show:none") == 1                      # the #awmain block, nothing else
    for tabs in re.findall(r'<nav class="sectabs[^"]*"[^>]*>', html):
        assert "hx-swap" not in tabs
    assert 'hx-swap="innerHTML show:window:top"' in html     # the phone bar is unchanged


def test_library_toolbar_keeps_scroll_on_movies_and_tv(env):
    main = env(jellyfin=lib_jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        for path in ("/media/movies", "/media/tv"):
            html = c.get(path).text
            form = re.search(r'<form class="toolbar"[^>]*>(.*?)</form>', html, re.S)
            assert KEEP in re.search(r'<form class="toolbar"[^>]*>', html).group(0), path
            assert '<nav class="seg" aria-label="Layout">' in form.group(1)   # Grid / List links inherit it
            assert html.count("show:none") == 1, path
            for tabs in re.findall(r'<nav class="sectabs[^"]*"[^>]*>', html):
                assert "hx-swap" not in tabs


def test_vendored_htmx_parses_show_none_and_overrides_the_boost_default():
    js = (ROOT / "hub" / "static" / "htmx.min.js").read_text(encoding="utf-8")
    assert 'version:"2.0.4"' in js
    # show:<x> is parsed after the boosted default (show = "top"), and only top / bottom ever scroll
    assert js.index('r.show="top"') < js.index("r.show=f")
    assert 't.show==="top"' in js and 't.show==="bottom"' in js
