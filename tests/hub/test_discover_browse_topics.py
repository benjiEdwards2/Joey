"""JY-303 phase 2: Discover's Browse by genre (a Films row and a TV row of genre pills -> the See all grid with the kind
+ genre, sorted Popular), the grid's "<Genre> films" heading, and Related topics (TMDB keywords over the grid's first
page, a deferred part with a 12 s deadline; a chip filters the grid by `keyword=`). Fake Seerr only, no network: the
details' `keywords: [{id, name}]`, `/api/v1/keyword/{id}` and discover's `keywords=` follow Seerr's API; not probed
live."""
from __future__ import annotations

import re
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from hub import media_discover as md
from tests.hub.fake_seerr import Resp as SResp, res as sres
from tests.hub.test_discover_see_all import Paged, paged, text  # noqa: F401 - the paged fake Seerr
from tests.hub.test_guest_requests import friend  # noqa: F401 - the signed-in friend on the media front
from tests.hub.test_media_discover import HX, assert_no_secrets, env  # noqa: F401
from tests.hub.test_tv_discover_upcoming_jy270 import TV, tvf  # noqa: F401 - the friend + providers (TV)
from tests.hub.test_tv_mode import run_tv_pages
from tests.hub.tv_css import design_px

GENRES = {"movie": [{"id": 28, "name": "Action"}, {"id": 35, "name": "Comedy"}], "tv": [{"id": 18, "name": "Drama"}]}


def kw(*pairs) -> list[dict]:
    return [{"id": i, "name": n} for i, n in pairs]


def details(p: Paged, kind: str, tmdb: int, keywords) -> None:
    p.extra[f"/api/v1/{kind}/{tmdb}"] = {"id": tmdb, "keywords": keywords}


# ---- Browse by genre ----

def test_browse_section_renders_both_rows_from_the_genre_lists(paged):
    page = text(paged.get("/media/discover"))
    assert '<section class="sec browse" aria-label="Browse by genre">' in page
    films, tv = page.index('data-browse="movie"'), page.index('data-browse="tv"')
    assert page.rindex("See all") < films < tv                                  # under the last shelf
    assert '<a class="chip" href="/media/discover/all?kind=movie&sort=popular&genre=28">Action</a>' in page
    assert '<a class="chip" href="/media/discover/all?kind=movie&sort=popular&genre=35">Comedy</a>' in page
    assert '<a class="chip" href="/media/discover/all?kind=tv&sort=popular&genre=18">Drama</a>' in page
    assert sum(1 for g in paged.paged.gets if g.startswith("/api/v1/genres/")) == 2
    paged.get("/media/discover")
    assert sum(1 for g in paged.paged.gets if g.startswith("/api/v1/genres/")) == 2   # cached (24 h)


def test_browse_drops_a_kind_without_a_list_and_hides_when_both_are_empty(paged):
    paged.paged.genres["tv"] = []
    page = text(paged.get("/media/discover"))
    assert 'data-browse="movie"' in page and 'data-browse="tv"' not in page
    md.clear_cache()
    md.clear_meta(disk=True)
    paged.paged.genres = {"movie": [], "tv": []}
    assert "Browse by genre" not in paged.get("/media/discover").text


def test_browse_hidden_when_seerr_is_down(paged):
    paged.paged.fail = True
    r = paged.get("/media/discover")
    assert r.status_code == 200 and "Browse by genre" not in r.text and "Discover unavailable" in r.text


def test_never_on_search_results(paged):
    paged.paged.extra["/api/v1/search?query=abc"] = {"results": []}
    assert "Browse by genre" not in paged.get("/media/discover?q=abc").text


# ---- the genre page (the phase 1 grid) ----

def test_genre_grid_heading_reads_genre_films_or_tv(paged):
    page = text(paged.get("/media/discover/all?kind=movie&sort=popular&genre=28"))
    assert "<title>Action films · Joey</title>" in page and ">Action films</h1>" in page
    assert '<option value="28" selected>Action</option>' in page                # the filter bar keeps working
    page = text(paged.get("/media/discover/all?kind=tv&sort=popular&genre=18"))
    assert ">Drama TV</h1>" in page
    page = text(paged.get("/media/discover/all?kind=tv&sort=rated&genre=18"))
    assert ">Drama TV · Top rated</h1>" in page
    assert ">Popular films</h1>" in text(paged.get("/media/discover/all?shelf=movies"))   # unchanged otherwise


# ---- keyword filter ----

def test_keyword_filters_the_seerr_read_and_shows_the_active_chip(paged):
    paged.paged.extra["/api/v1/keyword/9715"] = {"id": 9715, "name": "superhero"}
    page = text(paged.get("/media/discover/all?kind=movie&sort=popular&keyword=9715"))
    [read] = [g for g in paged.paged.gets if g.startswith("/api/v1/discover/")]
    q = {k: v[0] for k, v in parse_qs(urlsplit(read).query).items()}
    assert urlsplit(read).path == "/api/v1/discover/movies" and q["keywords"] == "9715"
    assert ">Popular films · superhero</h1>" in page
    assert '<span class="chip on" aria-current="true">superhero</span>' in page
    assert ('<a class="chip topic-clear" href="/media/discover/all?kind=movie&sort=popular" '
            'aria-label="Clear topic superhero">×</a>') in page
    assert '<input type="hidden" name="keyword" value="9715">' in page          # a filter change keeps the topic
    more = re.search(r'class="btn btn-secondary seemore" href="([^"]+)"', page).group(1)
    assert more == "/media/discover/all?kind=movie&sort=popular&keyword=9715&page=2"
    assert 'hx-get="/media/discover/all?kind=movie&sort=popular&keyword=9715&part=topics"' in page


def test_keyword_on_trending_reads_both_kinds_by_popularity(paged):
    page = text(paged.get("/media/discover/all?shelf=trending&keyword=12"))
    reads = sorted(urlsplit(g).path for g in paged.paged.gets if g.startswith("/api/v1/discover/"))
    assert reads == ["/api/v1/discover/movies", "/api/v1/discover/tv"]
    assert ">Popular films & TV · Topic</h1>" in page                   # a name Seerr can't give


def test_bad_keyword_falls_back(paged):
    r = paged.get("/media/discover/all?kind=movie&keyword=abc")
    assert r.status_code == 200 and "keywords=" not in "".join(paged.paged.gets) and "topic-clear" not in r.text


# ---- Related topics (the deferred part) ----

def topics(c, url):
    return c.get(url + "&part=topics", headers=HX)


def test_related_topics_count_over_the_page_most_first_capped(paged):
    p = paged.paged
    details(p, "movie", 1100, kw((1, "heist"), (2, "london"), (3, "betrayal")))
    details(p, "movie", 1101, kw((2, "london"), (3, "betrayal"), (3, "betrayal")))   # a duplicate counts once
    details(p, "movie", 1102, kw((3, "betrayal")) + kw(*[(100 + i, f"k{i}") for i in range(10)]))
    r = topics(paged, "/media/discover/all?kind=movie&sort=popular")
    page = text(r)
    assert r.status_code == 200 and "<html" not in page
    chips = re.findall(r'<a class="chip" href="([^"]+)">([^<]+)</a>', page)
    assert [n for _, n in chips] == ["betrayal", "london", "heist", "k0", "k1", "k2", "k3", "k4"]   # 3,2,1 titles
    assert chips[0][0] == "/media/discover/all?kind=movie&sort=popular&keyword=3"
    assert '<section id="see-topics" class="sec seetopics">' in page and ">Related topics</h2>" in page
    reads = [g for g in p.gets if re.match(r"/api/v1/movie/\d+$", g)]
    assert len(reads) == 20 and len(set(reads)) == 20                              # one read per title on page 1
    topics(paged, "/media/discover/all?kind=movie&sort=popular")
    assert len([g for g in p.gets if re.match(r"/api/v1/movie/\d+$", g)]) == 20    # cached (24 h)


def test_related_topics_leave_out_the_active_keyword_and_keep_its_chip(paged):
    p = paged.paged
    p.extra["/api/v1/keyword/3"] = {"id": 3, "name": "betrayal"}
    details(p, "movie", 1100, kw((3, "betrayal"), (2, "london")))
    page = text(topics(paged, "/media/discover/all?kind=movie&sort=rated&genre=28&keyword=3"))
    assert '<span class="chip on" aria-current="true">betrayal</span>' in page
    # the clear keeps the genre
    assert 'href="/media/discover/all?kind=movie&sort=rated&genre=28" aria-label="Clear topic betrayal"' in page
    chips = re.findall(r'<a class="chip" href="([^"]+)">([^<]+)</a>', page)
    assert chips == [("/media/discover/all?kind=movie&sort=rated&keyword=2", "london")]   # the topic is the page
    assert "hx-get" not in page                                                    # the part never loads itself again


def test_related_topics_empty_or_down_is_an_empty_200(paged):
    r = topics(paged, "/media/discover/all?kind=movie&sort=popular")           # no title carries keywords
    assert r.status_code == 200 and r.text == ""
    paged.paged.fail = True
    md.clear_cache()
    r = topics(paged, "/media/discover/all?kind=tv&sort=popular")
    assert r.status_code == 200 and r.text == ""


def test_seerr_down_page_has_no_topics_loader(paged):
    paged.paged.fail = True
    page = paged.get("/media/discover/all?shelf=movies").text
    assert "Discover unavailable" in page and "part=topics" not in page and "see-topics" not in page
    assert_no_secrets(page)


def test_related_topics_stop_at_the_deadline(paged, monkeypatch):
    p = paged.paged
    details(p, "movie", 1100, kw((7, "fast")))
    gate = threading.Event()
    real = p.get

    def get(url, headers=None, timeout=None, **kw_):
        if re.search(r"/api/v1/movie/(?!1100$)\d+$", url):
            gate.wait(5)   # every other title hangs
        return real(url, headers=headers, timeout=timeout, **kw_)
    monkeypatch.setattr(md.requests, "get", get)
    try:
        got = md.related_topics(md.see_filters(kind="movie", sort="popular"), deadline=0.5)
    finally:
        gate.set()
    assert [t["name"] for t in got] == ["fast"]


def test_a_failing_part_answers_empty(paged, monkeypatch):
    monkeypatch.setattr(md, "related_topics", lambda f: 1 / 0)
    r = topics(paged, "/media/discover/all?kind=movie&sort=popular")
    assert r.status_code == 200 and r.text == ""


# ---- friends (media front, web and TV) ----

@pytest.fixture()
def fg(tvf):  # noqa: F811
    """The friend (+ providers), with Seerr's genre lists, a keyword and a title's keywords."""
    s = tvf.seerr
    s.shelves["/api/v1/discover/trending"] = [sres(701, "Friend Film"), sres(702, "Friend Show", "tv")]
    real = s.get

    def get(url, headers=None, timeout=None, **kw_):
        u = str(url)
        for kind in ("movie", "tv"):
            if u.endswith(f"/api/v1/genres/{kind}"):
                return SResp(GENRES[kind])
        if u.endswith("/api/v1/keyword/40"):
            return SResp({"id": 40, "name": "time travel"})
        if "/api/v1/discover/movies?" in u and "keywords=40" in u:
            return SResp({"page": 1, "totalPages": 1, "results": [sres(703, "Topic Film")]})
        if u.endswith("/api/v1/movie/703"):
            return SResp({"id": 703, "keywords": kw((40, "time travel"), (41, "paradox"))})
        return real(url, headers=headers, timeout=timeout, **kw_)
    s.get = get
    return tvf


def test_friends_get_browse_on_their_discover_web_and_tv(fg):
    for headers in ({}, TV):
        page = text(fg.get("/media/discover", headers=headers))
        assert 'data-browse="movie"' in page and 'data-browse="tv"' in page
        assert '<a class="chip" href="/media/discover/all?kind=tv&sort=popular&genre=18">Drama</a>' in page
    tv = text(fg.get("/media/discover", headers=TV))
    assert tv.index('data-shelf="tv-soon"') < tv.index('data-browse="movie"')   # after the last shelf
    assert "Browse by genre" not in fg.get("/media/discover/search?q=Fri", headers=HX).text


def test_friends_keyword_grid_has_request_chips_and_topics(fg):
    page = text(fg.get("/media/discover/all?kind=movie&sort=popular&keyword=40"))
    assert ">Popular films · time travel</h1>" in page and "Topic Film" in page
    assert 'hx-get="/media/title/movie/703/request?panel=1"' in page and "reqchip reqchip-request" in page
    assert "wlbtn" not in page
    part = text(fg.get("/media/discover/all?kind=movie&sort=popular&keyword=40&part=topics", headers=HX))
    assert re.findall(r'<a class="chip" href="[^"]+">([^<]+)</a>', part) == ["paradox"]
    assert '<span class="chip on" aria-current="true">time travel</span>' in part


# ---- TV ----

def test_tv_css_styles_the_browse_and_topic_rows(friend):  # noqa: F811
    css = design_px(friend.get("/static/tv.css").text)
    assert ("html.tv .browse-label { margin: 12px 0 0; font-size: 18px; line-height: 22px; font-weight: 600; "
            "color: var(--tv-t2); }") in css
    assert ("html.tv .browse-row, html.tv .topic-row { display: flex; flex-wrap: nowrap; gap: 8px; margin: 4px 0 0; "
            "padding: 7px 8px; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; }") in css
    assert ("html.tv .browse-row .chip, html.tv .topic-row .chip { flex: none; height: 36px; padding: 0 16px; "
            "border-radius: var(--tv-r); border: 1px solid var(--tv-line); background: var(--tv-surface); "
            "font-size: 18px; color: var(--tv-t3); }") in css
    assert ("html.tv .browse-row .chip.tv-focus, html.tv .browse-row .chip:focus-visible, html.tv .topic-row "
            ".chip.tv-focus, html.tv .topic-row .chip:focus-visible { color: var(--tv-t1); }") in css
    assert ("html.tv .topic-row .chip.on { background: #f4f4f5; color: #09090b; border-color: transparent; "
            "font-weight: 600; }") in css
    assert "html.tv .seetopics { margin: 12px 0 0; }" in css


def test_down_from_the_last_shelf_walks_the_browse_rows_under_node(friend, tmp_path):  # noqa: F811
    out = run_tv_pages(friend, tmp_path, r"""
var films;
function discover() {
  var main = shell('discover');
  var row = new El('div', { cls: ['carousel', 'tvt-row'], top: 200 });
  for (var n = 1; n <= 4; n++) row.append(new El('a', { name: 'p' + n, cls: ['card-poster'],
    attrs: { href: '/media/title/movie/' + n }, top: 200, left: 100 + (n - 1) * 200 }));
  main.append(row);
  var sec = new El('section', { cls: ['sec', 'browse'], top: 600 });
  films = new El('nav', { cls: ['chips', 'browse-row'], top: 650, left: 100 });
  films.scrollLeft = 0;
  for (var g = 1; g <= 14; g++) films.append(new El('a', { name: 'f' + g, cls: ['chip'],
    attrs: { href: '/media/discover/all?kind=movie&genre=' + g }, top: 650, left: 100 + (g - 1) * 150 }));
  var tv = new El('nav', { cls: ['chips', 'browse-row'], top: 750, left: 100 });
  for (var t = 1; t <= 3; t++) tv.append(new El('a', { name: 't' + t, cls: ['chip'],
    attrs: { href: '/media/discover/all?kind=tv&genre=' + t }, top: 750, left: 100 + (t - 1) * 150 }));
  sec.append(films); sec.append(tv);
  main.append(sec);
}
load('/media/discover', discover);
out.first = now();
key('ArrowDown'); out.down = now();
var walk = [];
for (var k = 0; k < 12; k++) { key('ArrowRight'); walk.push(now()); }
out.walk = walk; out.scrolled = films.scrollLeft > 0;
key('ArrowDown'); out.tvrow = now();
key('ArrowUp'); out.up = now();
""")
    assert out["first"] == "p1" and out["down"] == "f1"
    assert out["walk"] == [f"f{n}" for n in range(2, 14)] and out["scrolled"]
    assert out["tvrow"].startswith("t") and out["up"].startswith("f")
