"""JY-303 phase 1 (B. 2026-11-06 picker: PUSH, rec B phased): every Discover shelf's "See all" opens one grid page with
filters (Films / TV, Genre, Year, Sort, Service, Hide what is on Joey) and Load more (Seerr `?page=N`). Fake Seerr only,
no network: the paged / genre reads are modelled on Seerr's shapes (`{"page", "totalPages", "results"}`, genres
`[{id, name}]`); the spec lists which reads are not yet probed live."""
from __future__ import annotations

import html as htmllib
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from hub import media_discover as md
from tests.hub.fake_seerr import Resp as SResp, res as sres
from tests.hub.test_guest_requests import friend  # noqa: F401 - the signed-in friend on the media front
from tests.hub.test_media_discover import FAKE_KEY, FAKE_URL, HX, Resp, assert_no_secrets, env, res  # noqa: F401
from tests.hub.test_tv_discover_upcoming_jy270 import TV, tvf  # noqa: F401 - the friend + providers (TV)
from tests.hub.test_tv_mode import FAKE_DOM, run_tv_pages  # noqa: F401
from tests.hub.tv_css import design_px

SHELF_IDS = ("trending", "movies", "tv", "movies-soon", "tv-soon")
TODAY = date(2026, 11, 6)


def page_rows(prefix: int, n: int = 20, status=None) -> list[dict]:
    return [res(prefix + i, f"Title {prefix + i}", status=status, media="movie") for i in range(n)]


class Paged:
    """A Seerr that answers every discover / genre read by path + query, with page / totalPages."""

    def __init__(self, total: int = 3):
        self.gets: list[str] = []
        self.total, self.fail = total, False
        self.genres = {"movie": [{"id": 28, "name": "Action"}, {"id": 35, "name": "Comedy"}],
                       "tv": [{"id": 18, "name": "Drama"}]}
        self.extra: dict[str, dict] = {}

    def get(self, url, headers=None, timeout=None, **kw):
        assert url.startswith(FAKE_URL) and headers == {"X-Api-Key": FAKE_KEY} and timeout
        path = url[len(FAKE_URL):]
        self.gets.append(path)
        if self.fail:
            raise requests.ConnectionError(url)
        if path in self.extra:
            return Resp(self.extra[path])
        parts = urlsplit(path)
        q = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        if parts.path.startswith("/api/v1/genres/"):
            assert timeout == 3   # Discover never blocks (E1)
            return Resp(self.genres[parts.path.rsplit("/", 1)[1]])
        if parts.path.startswith("/api/v1/watchproviders/"):
            return Resp([])
        if parts.path.startswith("/api/v1/discover/"):
            assert timeout == 3
            page = int(q.get("page", 1))
            kind = "tv" if "/tv" in parts.path else "movie"
            base = (2000 if kind == "tv" else 1000) + page * 100
            rows = [res(base + i, f"{kind} p{page} n{i}", media=kind, status=5 if i == 0 else None) for i in range(20)]
            return Resp({"page": page, "totalPages": self.total, "totalResults": self.total * 20, "results": rows})
        return Resp({}, 404)


@pytest.fixture()
def paged(env, monkeypatch):  # noqa: F811
    c, _ = env()
    p = Paged()
    monkeypatch.setattr(md.requests, "get", p.get)
    with c:
        c.paged = p
        yield c


def text(r) -> str:
    return htmllib.unescape(r.text)


# ---- the links ----

def test_every_discover_shelf_has_a_see_all_link(paged):
    page = text(paged.get("/media/discover"))
    for sid in SHELF_IDS:
        assert f'<a class="seeall" href="/media/discover/all?shelf={sid}">See all</a>' in page


def test_service_shelves_link_to_the_grid_with_the_service(tvf):  # noqa: F811
    page = text(tvf.get("/media/discover/service/100", headers=TV))
    links = re.findall(r'class="seeall" href="([^"]+)"', page)
    assert links == ["/media/discover/all?kind=movie&sort=popular&service=100",
                     "/media/discover/all?kind=tv&sort=popular&service=100",
                     "/media/discover/all?kind=&sort=newest&service=100",
                     "/media/discover/all?kind=&sort=rated&service=100"]


# ---- the grid ----

def test_page_one_is_the_shelf_itself_with_the_preset_filters(paged):
    r = paged.get("/media/discover/all?shelf=movies")
    page = text(r)
    assert r.status_code == 200 and "Popular films · Joey" in page
    assert paged.paged.gets.count("/api/v1/discover/movies") == 1          # the shelf's own path, no ?page=1
    assert page.count('class="card-cell"') == 20 and "movie p1 n0" in page
    assert '<option value="movie" selected>Films</option>' in page
    assert '<option value="popular" selected>Popular</option>' in page
    assert '<option value="28">Action</option>' in page                      # Genre, once a kind is picked
    assert 'class="wlbtn compact"' in page                                   # B.'s cards keep the watchlist +
    more = re.search(r'<a class="btn btn-secondary seemore" href="([^"]+)" hx-get="([^"]+)"', page)
    assert more.group(1) == "/media/discover/all?kind=movie&sort=popular&page=2"
    assert more.group(2) == "/media/discover/all?kind=movie&sort=popular&page=2&more=1"


def test_load_more_returns_the_next_page_and_the_next_button_only(paged):
    r = paged.get("/media/discover/all?kind=movie&sort=popular&page=2&more=1", headers=HX)
    page = text(r)
    assert r.status_code == 200 and "<html" not in page and "<select" not in page
    assert "movie p2 n0" in page and "movie p1 n0" not in page
    assert "/api/v1/discover/movies?page=2" in paged.paged.gets
    assert page.count("data-more-first") == 1 and page.index("data-more-first") < page.index("movie p2 n0")
    assert '<div id="see-more" class="seemore-wrap" hx-swap-oob="true">' in page
    assert 'href="/media/discover/all?kind=movie&sort=popular&page=3"' in page
    last = text(paged.get("/media/discover/all?kind=movie&sort=popular&page=3&more=1", headers=HX))
    assert "movie p3 n0" in last and "seemore" not in last.replace("seemore-wrap", "")   # the last page: no button


def test_a_full_load_of_page_n_shows_pages_1_to_n_capped(paged):
    page = text(paged.get("/media/discover/all?kind=movie&sort=popular&page=3"))
    assert page.count('class="card-cell"') == 60 and "movie p3 n19" in page and "seemore" not in page.replace(
        "seemore-wrap", "")
    paged.paged.total = 40
    md.clear_cache()
    paged.paged.gets.clear()
    page = text(paged.get("/media/discover/all?kind=tv&sort=popular&page=15"))
    reads = [g for g in paged.paged.gets if g.startswith("/api/v1/discover/tv")]
    assert len(reads) == md.FULL_PAGES and "/api/v1/discover/tv?page=10" in reads and "page=11" not in "".join(reads)
    assert 'href="/media/discover/all?kind=tv&sort=popular&page=11"' in page


def test_filters_build_the_discover_read(paged):
    page = text(paged.get("/media/discover/all?kind=tv&genre=18&year=2024&sort=rated&service=8"))
    [read] = [g for g in paged.paged.gets if g.startswith("/api/v1/discover/")]
    q = parse_qs(urlsplit(read).query)
    assert urlsplit(read).path == "/api/v1/discover/tv"
    assert {k: v[0] for k, v in q.items()} == {
        "page": "1", "sortBy": "vote_average.desc", "voteCountGte": "200", "firstAirDateGte": "2024-01-01",
        "firstAirDateLte": "2024-12-31", "genre": "18", "watchRegion": "AU", "watchProviders": "8"}
    assert "Drama TV · Top rated · 2024 · Streaming service" in page   # JY-303 p2: a genre heads the title
    assert '<option value="18" selected>Drama</option>' in page and '<option value="2024" selected>2024</option>' in page


def test_films_and_tv_with_a_filter_reads_both_and_alternates(paged):
    page = text(paged.get("/media/discover/all?kind=&sort=popular&year=2023"))
    reads = sorted(g for g in paged.paged.gets if g.startswith("/api/v1/discover/"))
    assert [urlsplit(g).path for g in reads] == ["/api/v1/discover/movies", "/api/v1/discover/tv"]
    assert "primaryReleaseDateGte=2023-01-01" in reads[0] and "firstAirDateLte=2023-12-31" in reads[1]
    assert page.index("movie p1 n0") < page.index("tv p1 n0") < page.index("movie p1 n1<")
    assert page.count('class="card-cell"') == 40
    assert 'name="genre"' not in page                                        # Genre needs Films or TV


def test_hide_what_is_on_joey_drops_available_titles(paged):
    shown = text(paged.get("/media/discover/all?shelf=movies"))
    hidden = text(paged.get("/media/discover/all?kind=movie&sort=popular&hide=1"))
    assert "movie p1 n0" in shown and "movie p1 n0" not in hidden            # n0 is Available (status 5)
    assert hidden.count('class="card-cell"') == 19 and 'name="hide" value="1" checked' in hidden


def test_bad_values_fall_back_never_a_500(paged):
    r = paged.get("/media/discover/all?kind=zzz&sort=zzz&year=abc&page=-3&genre=x&service=y&shelf=nope")
    assert r.status_code == 200 and "Popular films &amp; TV" in r.text
    r = paged.get("/media/discover/all?kind=movie&genre=999&year=1800")      # a genre the list does not carry
    assert r.status_code == 200 and "genre=999" not in "".join(paged.paged.gets) and "year" not in "".join(
        g for g in paged.paged.gets if "Gte" in g)


def test_seerr_down_says_unavailable_without_load_more(paged):
    paged.paged.fail = True
    r = paged.get("/media/discover/all?shelf=tv")
    assert r.status_code == 200 and "Discover unavailable" in r.text and "seemore\"" not in r.text
    n = len(paged.paged.gets)
    assert paged.get("/media/discover/all?shelf=tv").status_code == 200
    assert not any(g.startswith("/api/v1/discover/") for g in paged.paged.gets[n:])   # remembered FAIL_TTL
    assert_no_secrets(r.text)


def test_trending_preset_reads_trending_and_pages_it(paged):
    page = text(paged.get("/media/discover/all?shelf=trending"))
    assert "/api/v1/discover/trending" in paged.paged.gets and "Trending · Joey" in page
    assert 'href="/media/discover/all?kind=&sort=trending&page=2"' in page
    paged.get("/media/discover/all?kind=&sort=trending&page=2&more=1", headers=HX)
    assert "/api/v1/discover/trending?page=2" in paged.paged.gets


# ---- the pure parts ----

def test_see_filters_presets_and_fallbacks():
    f = md.see_filters("movies-soon", today=TODAY)
    assert (f["kind"], f["sort"], f["genre"], f["year"], f["service"], f["hide"]) == ("movie", "soon", None, None,
                                                                                       None, False)
    assert md.see_filters("trending", kind="tv", today=TODAY)["sort"] == "popular"   # trending takes no filter
    assert md.see_filters("tv", kind="", genre="18", today=TODAY)["genre"] is None    # genre needs a kind
    assert md.see_filters(year="2030", today=TODAY)["year"] is None
    assert md.see_filters(year="2029", today=TODAY)["year"] == 2029


def test_see_paths_dates_and_presets():
    soon = md.see_filters("movies-soon", today=TODAY)
    assert md.see_paths(soon, 1, TODAY) == [("/api/v1/discover/movies/upcoming", "movie")]
    assert md.see_paths(soon, 4, TODAY) == [("/api/v1/discover/movies/upcoming?page=4", "movie")]
    [(p, _)] = md.see_paths({**soon, "year": 2026}, 1, TODAY)
    assert "primaryReleaseDateGte=2026-11-06" in p and "primaryReleaseDateLte=2026-12-31" in p
    [(p, _)] = md.see_paths(md.see_filters(kind="tv", sort="newest", today=TODAY), 2, TODAY)
    assert p == "/api/v1/discover/tv?page=2&sortBy=first_air_date.desc&firstAirDateLte=2026-11-06"


# ---- friends (media front, web and TV) ----

def test_friends_get_the_request_grid(friend):  # noqa: F811
    friend.seerr.shelves["/api/v1/discover/trending"] = [sres(701, "Friend Film"), sres(702, "Friend Show", "tv")]
    r = friend.get("/media/discover/all?shelf=trending")
    page = text(r)
    assert r.status_code == 200 and 'class="poster-grid seegrid reqgrid"' in page
    assert 'hx-get="/media/title/movie/701/request?panel=1"' in page and "reqchip reqchip-request" in page
    assert '<dialog id="req-dialog"' in page and "/media/watchlist" not in page and "wlbtn" not in page
    assert "seemore\"" not in page                                           # the fake answers totalPages 1


def test_friends_discover_grid_and_tv_shelves_link_to_see_all(tvf):  # noqa: F811
    tvf.seerr.shelves["/api/v1/discover/trending"] = [sres(701, "Friend Film")]
    web = text(tvf.get("/media/discover"))
    assert '<a class="seeall" href="/media/discover/all?shelf=trending">See all</a>' in web
    tv = text(tvf.get("/media/discover", headers=TV))
    for sid in ("trending", "movies-soon", "tv-soon"):
        assert f'href="/media/discover/all?shelf={sid}">See all</a>' in tv
    assert '<dialog id="req-dialog"' in tv                                   # the kit moved, still on the page
    assert "seeall" not in text(tvf.get("/media/discover/search?q=Fri", headers=HX))   # never on results


# ---- TV ----

def test_tv_css_shows_see_all_and_styles_load_more(friend):  # noqa: F811
    css = design_px(friend.get("/static/tv.css").text)
    assert "html.tv .sechead a { display: none; }" in css                   # the other heading links stay hidden
    assert ("html.tv .sechead a.seeall { display: inline-flex; align-items: center; height: 32px; padding: 0 14px; "
            "border-radius: var(--tv-r-pill); font-size: 18px; color: var(--tv-t3); }") in css
    assert "html.tv .sechead a.seeall.tv-focus, html.tv .sechead a.seeall:focus-visible { color: var(--tv-t1); }" in css
    assert ("html.tv .seemore { height: 44px; padding: 0 24px; font-size: 18px; border-radius: var(--tv-r-pill); }"
            in css)
    assert "html.tv .seefilters .select, html.tv .seehide { height: 40px; font-size: 18px;" in css


def test_load_more_focuses_the_first_new_poster_under_node(friend, tmp_path):  # noqa: F811
    out = run_tv_pages(friend, tmp_path, r"""
var more, grid, wrap;   /* the fake DOM has no #id selector: kept by reference */
function seeall() {
  var main = shell('discover');
  grid = new El('div', { cls: ['poster-grid', 'seegrid', 'reqgrid'], attrs: { id: 'see-grid' }, top: 180 });
  for (var n = 1; n <= 8; n++) grid.append(new El('a', { name: 'g' + n, cls: ['card-poster'],
    attrs: { href: '/media/title/movie/' + n }, top: 200 + Math.floor((n - 1) / 4) * 400, left: 100 + ((n - 1) % 4) * 200 }));
  main.append(grid);
  more = new El('a', { name: 'more', cls: ['btn', 'seemore'], attrs: { href: '/media/discover/all?page=2' }, top: 1100, left: 300 });
  wrap = new El('div', { attrs: { id: 'see-more' }, top: 1100, kids: [more] });
  main.append(wrap);
}
load('/media/discover/all', seeall);
['ArrowDown', 'ArrowDown'].forEach(key);
out.on = now();
/* htmx: the next posters land at the grid's end, the button is swapped out (oob) */
wrap.children.splice(0, 1); more.parentElement = null;
for (var n = 9; n <= 12; n++) {
  var attrs = { href: '/media/title/movie/' + n };
  if (n === 9) attrs['data-more-first'] = '';
  grid.append(new El('a', { name: 'g' + n, cls: ['card-poster'], attrs: attrs, top: 1000, left: 100 + (n - 9) * 200 }));
}
window.location.search = '?page=2';
fire('htmx:afterSettle', {}); flush();
out.after = now();
out.left = document.querySelector('[data-more-first]') ? 'kept' : 'gone';
""")
    assert out["on"] == "more" and out["after"] == "g9" and out["left"] == "gone"


def test_the_provider_and_genre_lists_are_read_side_by_side(paged, monkeypatch):
    """Review fix (PR #333): a hung Seerr costs one 3 s wait before the pages, not three. The two provider lists and the
    genre list must all be in flight together: each read waits at a 3-party barrier, which breaks (2 s) if they are
    issued one after another."""
    import threading
    barrier, broken = threading.Barrier(3, timeout=2), []
    real = paged.paged.get

    def get(url, headers=None, timeout=None, **kw):
        if "/api/v1/watchproviders/" in url or "/api/v1/genres/" in url:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                broken.append(url)
        return real(url, headers=headers, timeout=timeout, **kw)
    monkeypatch.setattr(md.requests, "get", get)
    r = paged.get("/media/discover/all?kind=movie&sort=popular")
    assert r.status_code == 200 and broken == []
    assert sum(1 for g in paged.paged.gets if g.startswith(("/api/v1/watchproviders/", "/api/v1/genres/"))) == 3
