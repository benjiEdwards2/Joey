"""JY-259 phase 3 (2026-10-28; B.: "Keen to run jy 259 and teh rest after that building better with the UI improvements."):
the TV title pages as a backdrop hero with one button row, a show's episodes on the first screen with the seasons as
chips, cast circles and "More on Joey" kit posters (skeletons while they load), the grid's score glow off and the
sub-tab fold (Q8 A), Discover's state on a band under the art (Q5 A), eager first rows. Spec:
docs/specs/JY-259-tv-revamp.md §8. TV mode only: the web and phone pages are unchanged."""
import re
import socket

import pytest

from hub import guest, media_discover as md, media_guest_home, media_item, shell
from tests.hub.fake_jellyfin import FRIEND_ID, OTHER_ID
from tests.hub.film_page import whole
from tests.hub.guest_pages import TV_UA, guest_client, movie, sign_in
from tests.hub.test_guest_requests import start
from tests.hub.test_tv_mode import run_tv_pages
from tests.hub.test_tv_series_episodes import E1, E2, E3, S1, SHOW, tvc  # noqa: F401 - the show fixture
from tests.hub.test_tv_shelves_tmdb import shelves
from tests.hub.tv_css import design_px

TV = {"User-Agent": TV_UA}


def _sheet() -> str:
    return design_px(re.sub(r"/\*.*?\*/", "", (shell.TEMPLATES_DIR.parent / "static" / "tv.css").read_text(encoding="utf-8"),
                            flags=re.S))


def _kit():
    return shell.templates.env.get_template("_tv_tile.html").module


def header(html: str) -> str:
    return html.split('<header class="pagehead hero-detail', 1)[1].split("</header>", 1)[0]


def after_header(html: str) -> str:
    return html.split("</header>", 2)[-1]


def eps(html: str) -> str:
    m = re.search(r'<section class="sec tvshelf tv-eps"[^>]*>(.*?)</section>', html, flags=re.S)
    assert m, "no episodes row"
    return m.group(1)


@pytest.fixture()
def film_friend(monkeypatch, tmp_path):
    """A friend on the media front with Seerr: film 603 is on the server, with a cast and two shelves."""
    client, fake, seerr, uid = start(monkeypatch, tmp_path)
    shelves(seerr)
    seerr.titles[("movie", 603)]["credits"] = {"cast": [
        {"id": 11, "name": "Ann Actor", "character": "Detective", "profilePath": "/a11.jpg"},
        {"id": 12, "name": "Bo Player", "character": "Pilot", "profilePath": None},
        {"id": None, "name": "Cy Nameless", "character": "Guard", "profilePath": "/a13.jpg"}]}
    with client as c:
        c.fake, c.seerr = fake, seerr
        sign_in(c, fake, uid)
        yield c


def tv_whole(c, url):
    c.headers.update(TV)
    try:
        return whole(c, url)
    finally:
        c.headers.pop("User-Agent", None)


# ---- 1: the backdrop hero, per kind ----

def test_a_film_title_page_is_a_backdrop_hero(film_friend):
    film = tv_whole(film_friend, "/media/title/movie/603")
    h = header(film)
    assert 'class="hero-detail-bd"' in h and "hero-detail-poster" in h and h.count('class="hero-detail-btns"') == 1
    assert "tv-eps" not in film


def test_title_pages_are_a_backdrop_hero_per_kind(tvc):
    """a show, a season and an episode (the film: the test above; two fake servers cannot share one test)"""
    show = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    assert "hero-detail-poster" in header(show) and header(show).count('class="hero-detail-btns"') == 1
    rest = after_header(show)
    assert rest.index('class="sec tvshelf tv-eps"') < rest.index('<div class="filmbody">')   # episodes first, under the hero
    season = tvc.get(f"/media/item/{S1}", headers=TV).text
    assert 'aria-current="page"' in eps(season).split("</nav>", 1)[0]                          # its chip is lit
    episode = tvc.get(f"/media/item/{E2}", headers=TV).text
    assert 'class="tv-epstill"' in header(episode) and ">This one<" in eps(episode)


def test_the_web_and_phone_title_pages_are_unchanged(tvc):
    web = tvc.get(f"/media/item/{SHOW}").text
    assert "tv-eps" not in web and "tv-seasonchips" not in web and "tvt" not in web and "tvt-skel" not in web


# ---- 2: one button row that never wraps ----

def test_the_title_button_row_never_wraps():
    css = _sheet()
    assert re.search(r"html\.tv \.hero-detail-btns \{[^}]*flex-wrap: nowrap", css)
    assert re.search(r"html\.tv \.hero-detail-btns > \* \{[^}]*flex: none", css)
    first = re.search(r"html\.tv \.hero-detail-btns > a\.btn-white \{([^}]*)\}", css).group(1)
    for rule in ("flex: 0 1 auto", "min-width: 0", "overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap"):
        assert rule in first, rule
    assert re.search(r"html\.tv \.hero-detail-text \{[^}]*min-width: 0", css)


# ---- 3: a show's episodes on the first screen, the seasons as chips, the D-pad ----

def test_a_show_draws_episodes_then_season_chips(tvc):
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    row = eps(html)
    head, tiles = row.split('<div class="carousel', 1)
    assert '<h2 class="seclabel">Episodes</h2>' in head
    chips = re.findall(r'<a class="chip( on)?" href="([^"]+)"[^>]*>([^<]+)</a>', head)
    assert [(c[0], c[1], c[2]) for c in chips][0] == (" on", f"/media/item/{S1}", "Season 1") and len(chips) == 2
    assert "0 of 3 watched" in head                                                 # the lit season's own count
    cards = re.findall(r'<a class="card-poster tvt tvt-land"[^>]*>.*?</a>', tiles, flags=re.S)
    assert len(cards) == 3 and f'src="/img/jf:{E1}?h=400' in cards[0] and 'loading="lazy"' not in cards[0]
    assert '<section class="sec tvshelf tv-seasons"' not in html                    # no poster shelf of seasons


def test_down_from_the_buttons_skips_the_chips_to_the_first_episode_under_node(tvc, tmp_path):
    out = run_tv_pages(tvc, tmp_path, r"""
function show() {
  var main = shell('tv');
  main.append(new El('header', { cls: ['pagehead', 'hero-detail'], top: 80, kids: [new El('div', { cls: ['hero-detail-btns'], kids: [
    new El('a', { name: 'play', attrs: { href: '/jf/play', 'data-jf-id': 'x' }, top: 300, left: 250 }),
    new El('a', { name: 'trailer', attrs: { href: '/trailer' }, top: 300, left: 450 })] })] }));
  /* as drawn: the poster left of the buttons, the chips after the "Episodes" label, E1 under the label */
  var sec = new El('section', { cls: ['sec', 'tvshelf', 'tv-eps'], top: 450 });
  sec.append(new El('nav', { cls: ['tv-seasonchips'], top: 470, kids: [
    new El('a', { name: 'chip1', cls: ['chip', 'on'], attrs: { href: '/s1' }, top: 470, left: 200 }),
    new El('a', { name: 'chip2', cls: ['chip'], attrs: { href: '/s2' }, top: 470, left: 330 })] }));
  var row = new El('div', { cls: ['carousel', 'tvt-row'], top: 560 });
  for (var i = 1; i <= 4; i++) row.append(new El('a', { name: 'e' + i, cls: ['card-poster', 'tvt', 'tvt-land'],
    attrs: { href: '/e' + i }, top: 560, left: 100 + (i - 1) * 200 }));
  sec.append(row);
  main.append(sec);
}
load('/media/item/show', show);
out.first = now();
key('ArrowDown'); out.down = now();
key('ArrowUp'); out.up = now();
key('ArrowRight'); out.right = now();
key('ArrowUp'); out.up2 = now();
""")
    assert out == {"first": "play", "down": "e1", "up": "chip1", "right": "chip2", "up2": "play"}


def test_each_friend_sees_only_their_own_episodes_and_chips(tvc):
    mine = eps(tvc.get(f"/media/item/{SHOW}", headers=TV).text)
    assert "0 of 3 watched" in mine and ">Watched<" not in mine                    # the household watched E1 + E2
    sign_in(tvc, tvc.fake, OTHER_ID)                                                # watched E1
    theirs = eps(tvc.get(f"/media/item/{SHOW}", headers=TV).text)
    assert "1 of 3 watched" in theirs and ">Watched<" in theirs


def test_no_socket_opens_on_a_warm_tv_title_page(tvc, monkeypatch):
    tvc.get(f"/media/item/{SHOW}", headers=TV)

    def boom(*a, **k):
        raise AssertionError("a live read on render")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    monkeypatch.setattr(md, "_fetch", boom)
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    assert "tv-eps" in html


# ---- 4: cast circles, More on Joey, skeletons ----

def test_cast_is_circles_and_more_on_joey_is_kit_posters(film_friend):
    b = tv_whole(film_friend, "/media/title/movie/603")
    cast = b.split('<section class="sec tv-cast">', 1)[1].split("</section>", 1)[0]
    assert '<h2 class="seclabel">Cast</h2>' in cast
    assert re.search(r'<a class="card-poster tvt tvt-person" href="/media/person/11">', cast)
    assert "/img/tmdb:/a11.jpg?h=240" in cast and ">Detective<" in cast and "Bo Player" in cast
    # review: an actor with no TMDB id is drawn (picture, name, role) but is no link and no D-pad stop
    nameless = re.search(r'<div class="card-poster tvt tvt-person">(.*?)</div>', cast, flags=re.S)
    assert nameless and "Cy Nameless" in nameless.group(1) and ">Guard<" in nameless.group(1) and "href" not in nameless.group(0)
    more = b.split('<h2 class="seclabel">More on Joey</h2>', 1)[1].split("</section>", 1)[0]
    assert more.count('class="card-poster tvt tvt-poster"') == 2
    assert b.index('class="sec tv-cast"') < b.index("More on Joey")


def test_slow_shelves_draw_a_skeleton_row(film_friend):
    film_friend.headers.update(TV)
    try:
        cold = film_friend.get("/media/title/movie/603").text
    finally:
        film_friend.headers.pop("User-Agent", None)
    assert 'id="fp-shelves"' in cold
    skel = re.findall(r'<div class="carousel tvt-row tvt-skel" aria-hidden="true">(.*?)</div></section>', cold, flags=re.S)
    assert skel and all(s.count('class="tvt tvt-') == 3 and "<a " not in s and "<img" not in s for s in skel)
    assert "tvt-skel" not in tv_whole(film_friend, "/media/title/movie/603")       # the part replaced it
    assert "tvt-skel" not in film_friend.get("/media/title/movie/603").text           # never off the TV


def test_the_skeleton_macro_is_a_shape_with_no_stop():
    s = str(_kit().skeleton("More on Joey", "poster"))
    assert '<h2 class="seclabel">More on Joey</h2>' in s and s.count('class="tvt tvt-poster"') == 3
    assert "href" not in s and "<img" not in s and 'aria-hidden="true"' in s
    css = _sheet()
    assert re.search(r"html\.tv \.tvt-skel \.card-pic \{[^}]*aspect-ratio: 2 / 3", css)
    assert re.search(r"html\.tv \.tvt-skel \.tvt-land \.card-pic \{[^}]*aspect-ratio: 16 / 9", css)


# ---- 5: grids ----

def test_the_grid_has_no_score_glow_on_the_tv():
    css = _sheet()
    assert re.search(r"html\.tv \.poster-grid \.gold-glow, html\.tv \.poster-grid \.gold-glow-sm \{ animation: none; box-shadow: none; \}", css)
    assert re.search(r"repeat\(9, minmax\(0, 1fr\)\); gap: 18px 16px", css)       # phase 1's sizes kept


@pytest.fixture()
def lib(monkeypatch, tmp_path):
    films = [{"title": f"Film {i}", "jf_id": f"{i:04d}" * 8, "item_key": f"tmdb:{9000 + i}", "poster": "jf:" + f"{i:04d}" * 8,
              "year": 2024, "added_at": "2026-01-01T00:00:00.0000000Z"} for i in range(1, 4)]
    snap = {"jellyfin": {"server_id": "srv-1", "summary": "x", "library": {"movies": 3, "episodes": 0}, "latest": [],
                         "movies": films, "shows": []}}
    client, fake = guest_client(monkeypatch, tmp_path, snap)
    media_guest_home.clear_cache()
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def subtabs(html: str) -> str:
    return html.split('<nav class="sectabs sub"', 1)[1].split("</nav>", 1)[0]


def test_the_tv_sub_tabs_fold_tonight_to_rate_and_awards_under_more(lib):
    nav = subtabs(lib.get("/media/movies", headers=TV).text)
    top, more = nav.split('<details class="tv-tabmore"', 1)
    assert re.findall(r'<a href="([^"]+)"', top) == ["/media/movies", "/media/movies/watchlist"]
    assert "<summary>More</summary>" in more and " open" not in more.split(">", 1)[0]
    assert re.findall(r'<a href="([^"]+)"', more) == ["/media/movies/tonight", "/media/movies/to-rate", "/media/movies/awards"]
    tonight = subtabs(lib.get("/media/movies/tonight", headers=TV).text)
    folded = tonight.split('<details class="tv-tabmore"', 1)[1]
    assert folded.startswith(" open>") and re.search(r'href="/media/movies/tonight" aria-current="page"', folded)
    web = subtabs(lib.get("/media/movies").text)
    assert "tv-tabmore" not in web and len(re.findall(r"<a href=", web)) == 5        # the web keeps five tabs


# ---- 6: Discover ----

def test_discover_states_are_foot_bands_not_chips_over_the_art(monkeypatch, tmp_path):
    client, fake, seerr, uid = start(monkeypatch, tmp_path)
    with client as c:
        sign_in(c, fake, uid)
        tv = c.get("/media/discover", headers=TV).text
        web = c.get("/media/discover").text
    assert re.search(r'id="chip-movie-603" class="reqchip reqchip-lib">On Joey<', tv)
    assert re.search(r'id="chip-movie-701" class="reqchip reqchip-request">Request<', tv)
    assert re.search(r'id="chip-movie-603" class="reqchip reqchip-lib">In library<', web)   # the web keeps its words
    css = _sheet()
    for scope in (r"\.reqgrid", r"\.tv-searchdlg"):
        rule = re.search(r"html\.tv " + scope + r" \.reqchip \{([^}]*)\}", css).group(1)
        assert "position: static" in rule and "display: block" in rule, scope     # a band under the art, not over it
    band = re.search(r"html\.tv \.tvt-band \{([^}]*)\}", css).group(1)
    assert "position: static" in band
    # the words read whole at the 18 px floor: Discover is 8 across (a 9-across cell, 82 px, cut "Requested")
    last = re.findall(r"html\.tv \.poster-grid\.reqgrid \{ grid-template-columns: repeat\((\d+), minmax\(0, 1fr\)\)", css)[-1]
    assert last == "8" and css.rindex("repeat(8, minmax(0, 1fr))") > css.rindex("repeat(9, minmax(0, 1fr))")


# ---- 7: loading ----

def test_the_first_two_rows_load_eagerly():
    kit = _kit()
    item = {"title": "A", "poster": "jf:aa", "href": "/a"}
    eager = str(kit.row({"title": "R", "land": False, "items": [item]}, True))
    lazy = str(kit.row({"title": "R", "land": False, "items": [item]}))
    assert 'loading="lazy"' not in eager and 'loading="lazy"' in lazy
    src = (shell.TEMPLATES_DIR / "area_shelves.html").read_text(encoding="utf-8")
    assert "tvt.row(s, loop.index <= 2)" in src


def test_tv_home_first_two_rows_eager_and_the_rest_lazy(monkeypatch, tmp_path):
    from tests.hub.test_tv_home_jy259 import cache_show, jelly, main, show_read, watched_ep
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly(12)})
    media_guest_home.clear_cache()
    media_item.clear_cache()
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]
        fake.history[FRIEND_ID] = [watched_ep()]
        cache_show(FRIEND_ID, show_read())
        body = main(c.get(guest.home_path(), headers=TV).text)
    rows = body.split('<section class="sec"')[1:]
    assert len(rows) >= 3
    assert 'loading="lazy"' not in rows[0] and 'loading="lazy"' not in rows[1] and 'loading="lazy"' in rows[2]
    media_item.clear_cache()


# ---- review fixes (2026-10-28, PR #267) ----

def test_the_season_chips_sit_in_the_head_line_above_the_tile_row():
    """Review B (blocking): the chips were clipped (a negative margin on a scroll box) and drawn under the tile row. The
    head line stacks above the row; since the verifier fix the chips are one scroll line with the ring's room inside it
    (next test), never a wrap (the shots check every chip with elementFromPoint at all four sizes)."""
    css = _sheet()
    chips = re.search(r"html\.tv \.tv-seasonchips \{([^}]*)\}", css).group(1)
    assert "margin: -" not in chips and "flex-wrap: nowrap" in chips
    hd = re.search(r"html\.tv \.tv-eps \.tvshelf-hd \{([^}]*)\}", css).group(1)
    assert "position: relative" in hd and "z-index: 6" in hd and "min-height: 36px" in hd   # a chip's 2.25rem


def test_a_title_with_no_backdrop_is_still_the_hero(tvc, monkeypatch):
    from hub import media_backdrop
    monkeypatch.setattr(media_backdrop, "title_page", lambda *a, **k: None)          # no Jellyfin, stored or TMDB backdrop
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    h = header(html)
    assert "hero-detail-bd" not in h and "hero-detail-poster" in h and h.count('class="hero-detail-btns"') == 1
    assert after_header(html).index('class="sec tvshelf tv-eps"') < after_header(html).index('<div class="filmbody">')
    css = _sheet()
    assert "html.tv .pagehead.hero-detail:not(:has(.hero-detail-bd)) { background: radial-gradient(" in css   # a quiet glow


def test_a_show_with_no_episode_list_draws_the_chips_and_no_tile_row(tvc, monkeypatch):
    from hub import media_film
    real = media_film.tv_shelves
    monkeypatch.setattr(media_film, "tv_shelves", lambda *a, **k: {**real(*a, **k), "eps": None})
    row = eps(tvc.get(f"/media/item/{SHOW}", headers=TV).text)
    assert '<h2 class="seclabel">Episodes</h2>' in row and row.count('class="chip') == 2
    assert "carousel" not in row and "tvt-land" not in row and "tv-seasonsub" not in row   # no season shown, no count


def test_down_from_play_reaches_e1_even_when_it_is_scrolled_out_of_view_under_node(tvc, tmp_path):
    """Review: E1 scrolled off the left of its row (a Back into a scrolled row): Down from Play still lands on E1, and
    tv.js brings it into view (keepRowInView), rather than on the nearest visible tile."""
    out = run_tv_pages(tvc, tmp_path, r"""
function show() {
  var main = shell('tv');
  main.append(new El('header', { cls: ['pagehead', 'hero-detail'], top: 80, kids: [new El('div', { cls: ['hero-detail-btns'], kids: [
    new El('a', { name: 'play', attrs: { href: '/jf/play', 'data-jf-id': 'x' }, top: 300, left: 250 })] })] }));
  var sec = new El('section', { cls: ['sec', 'tvshelf', 'tv-eps'], top: 450 });
  sec.append(new El('nav', { cls: ['tv-seasonchips'], top: 470, kids: [
    new El('a', { name: 'chip1', cls: ['chip', 'on'], attrs: { href: '/s1' }, top: 470, left: 200 })] }));
  var row = new El('div', { cls: ['carousel', 'tvt-row'], top: 560 });
  for (var i = 1; i <= 4; i++) row.append(new El('a', { name: 'e' + i, cls: ['card-poster', 'tvt', 'tvt-land'],
    attrs: { href: '/e' + i }, top: 560, left: -500 + (i - 1) * 200 }));   /* e1, e2, e3 left of the screen */
  sec.append(row);
  main.append(sec);
}
load('/media/item/show', show);
out.first = now();
key('ArrowDown'); out.down = now();
""")
    assert out == {"first": "play", "down": "e1"}


# ---- verifier fix (2026-10-28, PR #267): many seasons stay on ONE line, a scroll row ----

MANY = r"""
var nav;
function many(lit) {   /* 16 season chips on one line, 130 px apart: chips 7-16 sit past the 960 px screen in the row */
  var main = shell('tv');
  main.append(new El('header', { cls: ['pagehead', 'hero-detail'], top: 80, kids: [new El('div', { cls: ['hero-detail-btns'], kids: [
    new El('a', { name: 'play', attrs: { href: '/jf/play', 'data-jf-id': 'x' }, top: 300, left: 250 })] })] }));
  var sec = new El('section', { cls: ['sec', 'tvshelf', 'tv-eps'], top: 450 });
  nav = new El('nav', { cls: ['tv-seasonchips'], top: 470, left: 200 });
  nav.scrollLeft = 0;
  for (var n = 1; n <= 16; n++) nav.append(new El('a', { name: 'chip' + n, cls: n === lit ? ['chip', 'on'] : ['chip'],
    attrs: n === lit ? { href: '/s' + n, 'aria-current': 'page' } : { href: '/s' + n }, top: 470, left: 200 + (n - 1) * 130 }));
  sec.append(nav);
  var row = new El('div', { cls: ['carousel', 'tvt-row'], top: 560 });
  row.scrollLeft = 0;
  for (var i = 1; i <= 4; i++) row.append(new El('a', { name: 'e' + i, cls: ['card-poster', 'tvt', 'tvt-land'],
    attrs: { href: '/e' + i }, top: 560, left: 100 + (i - 1) * 200 }));
  sec.append(row);
  main.append(sec);
}
"""


def test_the_season_chips_are_one_scroll_line_with_room_for_the_ring():
    css = _sheet()
    chips = re.search(r"html\.tv \.tv-seasonchips \{([^}]*)\}", css).group(1)
    assert "flex-wrap: nowrap" in chips and "overflow-x: auto" in chips and "margin" not in chips
    pad = re.search(r"padding: ([\d.]+)px ([\d.]+)px", chips).groups()
    ring = sum(map(float, re.search(r"\.card-poster\.tv-focus \.card-pic \{[^}]*outline: ([\d.]+)px solid[^}]*"
                                    r"outline-offset: ([\d.]+)px", css).groups()))
    assert float(pad[0]) >= ring and float(pad[1]) >= ring                       # the focus ring is never clipped


def test_left_and_right_walk_the_chip_row_and_scroll_it_under_node(tvc, tmp_path):
    out = run_tv_pages(tvc, tmp_path, MANY + r"""
load('/media/item/s1', function () { many(1); });
out.load_scroll = nav.scrollLeft;
key('ArrowDown'); key('ArrowUp'); out.up = now();
var walk = [];
for (var k = 0; k < 8; k++) { key('ArrowRight'); walk.push(now()); }
out.walk = walk; out.scrolled = nav.scrollLeft > 0;
key('ArrowLeft'); out.left = now();
""")
    assert out["up"] == "chip1" and out["load_scroll"] <= 0
    assert out["walk"] == [f"chip{n}" for n in range(2, 10)] and out["scrolled"] and out["left"] == "chip8"


def test_a_late_season_chip_is_scrolled_into_view_on_load_and_up_from_e1_lands_on_it_under_node(tvc, tmp_path):
    out = run_tv_pages(tvc, tmp_path, MANY + r"""
load('/media/item/s14', function () { many(14); });
out.load_scroll = nav.scrollLeft;
key('ArrowDown'); out.down = now();
key('ArrowUp'); out.up = now();
key('ArrowDown'); out.back_down = now();
""")
    assert out["load_scroll"] > 1000                                              # chip 14 (x 1890) brought into the row
    assert out["down"] == "e1" and out["up"] == "chip14" and out["back_down"].startswith("e")
