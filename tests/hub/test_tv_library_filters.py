"""JY-270 (library filters, B. 2026-10-29: chips only): on the TV, Movies and TV shows carry one sideways chip row under
the sub-tabs - Search this library (its own search dialog, sent as ?q=), the web toolbar's filters and its sorts as
links, the lit chip saying "on" in words. The web page never draws it (the toolbar there is unchanged)."""
import re

import pytest

from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import TV_UA, guest_client, sign_in
from tests.hub.test_tv_mode import run_tv_pages
from tests.hub.tv_css import design_px


MOVIES = [{"title": t, "jf_id": f"{i + 1:04d}" * 8, "item_key": f"tmdb:{9000 + i}", "year": 2020 + i,
           "added_at": "2026-10-01T00:00:00.0000000Z", "community_rating": 7.0} for i, t in enumerate(["Arrival", "Dune"])]
SHOWS = [{"title": "Quiet Coast", "jf_id": "5eed" * 8, "item_key": "tmdb:8001", "year": 2023,
          "added_at": "2026-10-01T00:00:00.0000000Z", "community_rating": 8.4, "episodes": 8}]


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    jelly = {"server_id": "srv-1", "summary": "x", "library": {"movies": 2, "episodes": 8}, "movies": MOVIES, "shows": SHOWS}
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        yield c


def chips(html: str) -> str:
    m = re.search(r'<nav class="chips tv-libchips".*?</nav>', html, re.S)
    return m.group(0) if m else ""


@pytest.mark.parametrize("path", ["/media/movies", "/media/tv"])
def test_the_tv_draws_the_chip_row_and_the_web_does_not(gc, path):
    tv = gc.get(path, headers={"User-Agent": TV_UA}).text
    web = gc.get(path).text
    row = chips(tv)
    assert "Search this library" in row and 'aria-controls="tv-lib-dlg"' in row
    assert 'id="tv-lib-dlg"' in tv and "data-tv-libsearch" in tv
    assert row.count("· on") >= 1 and "Sort: " in row and "<select" not in row
    assert "tv-libchips" not in web and "tv-lib-dlg" not in web


def test_a_sort_chip_keeps_the_filter_and_the_search_shows_its_words(gc):
    html = gc.get("/media/movies?q=a&sort=title", headers={"User-Agent": TV_UA}).text
    row = chips(html)
    assert "Search: a" in row and "Clear search" in row
    assert re.search(r'class="chip on" href="[^"]*sort=title[^"]*" aria-current="true">Sort: [^<]+<span class="tv-chipword"> · on', row)
    assert 'name="sort" value="title"' in html   # the dialog's search keeps the sort


def test_the_chip_css_keeps_the_18px_floor_and_the_js_sends_the_library_search(gc):
    css = gc.get("/static/tv.css").text
    block = css[css.index("JY-270 (library filters"):]
    block = block[:block.index("svg.ic { width: 1.125rem; height: 1.125rem; }")]
    sizes = [float(x) for x in re.findall(r"font-size: ([\d.]+)px", design_px(block))]
    assert sizes and min(sizes) >= 18
    js = gc.get("/static/tv.js").text
    assert "data-tv-libsearch" in js and "'.carousel, .tv-seasonchips, .tv-libchips'" in js


def test_the_search_dialog_keeps_the_filter_and_sort_for_its_reload(gc):
    """Enter in the dialog sends its form (tv.js: action + FormData as ?q=...): the hidden fields carry f and sort."""
    html = gc.get("/media/movies?f=watched&sort=title&q=du", headers={"User-Agent": TV_UA}).text
    form = re.search(r'<form[^>]*data-tv-libsearch>.*?</form>', html, re.S).group(0)
    assert 'action="/media/movies"' in form and 'name="q" value="du"' in form
    assert 'name="f" value="watched"' in form and 'name="sort" value="title"' in form


def test_up_from_the_grid_lands_on_the_lit_chip_under_node(gc, tmp_path):
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/movies', function () {
  movies(2);
  var main = document.querySelector('main');
  var row = new El('nav', { cls: ['chips', 'tv-libchips'], top: 140, left: 100 });
  row.append(new El('button', { name: 'c-search', cls: ['chip'], top: 140, left: 100 }));
  row.append(new El('a', { name: 'c-all', cls: ['chip'], attrs: { href: '/media/movies' }, top: 140, left: 300 }));
  row.append(new El('a', { name: 'c-lit', cls: ['chip', 'on'], attrs: { href: '/media/movies?f=watched', 'aria-current': 'true' }, top: 140, left: 700 }));
  main.append(row);
});
out.first = now();
key('ArrowUp');
out.up = now();
""")
    assert out["first"] == "p1" and out["up"] == "c-lit"
