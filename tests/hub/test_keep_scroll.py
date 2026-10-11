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


def test_awards_tiles_and_stepper_keep_scroll(rate_env):
    html = awards_html(rate_env)
    tiles = re.search(r'<nav class="awtiles"[^>]*>', html).group(0)
    step = re.search(r'<div class="awstep"[^>]*>(.*?)</form>.*?</div>\n', html, re.S)
    assert KEEP in tiles and KEEP in re.search(r'<div class="awstep"[^>]*>', html).group(0)
    # the year form, Current year and Not seen chips, prev / next all sit inside the .awstep that carries it
    assert 'class="awyearform"' in step.group(0)
    awstep = html.split('<div class="awstep"', 1)[1].split("\n</div>", 1)[0]
    assert 'class="chip' in awstep and "Not seen" in awstep and "Current year" in awstep
    assert KEEP not in html.split('<div class="awstep"', 1)[1].split("\n</div>", 1)[1]   # nothing past the controls


def test_awards_year_select_submits_through_htmx_not_a_native_reload(rate_env):
    html = awards_html(rate_env)
    sel = re.search(r'<select class="select awyear"[^>]*>', html).group(0)
    assert 'onchange="this.form.requestSubmit()"' in sel   # fires the submit event htmx boosts; form.submit() would not
    assert "this.form.submit()" not in html


def test_awards_posters_and_section_tabs_still_go_to_the_top(rate_env):
    html = awards_html(rate_env)
    assert html.count("show:none") == 2                      # the tiles nav and the stepper row, nothing else
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
