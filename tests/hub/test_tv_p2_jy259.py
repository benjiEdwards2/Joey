"""JY-259 phase 2 (2026-10-28; B.'s pick "JY-259: A · 1A · 2A · 3A · 4A · 5A · 6A · 7A · 8A"): the Home hero follows
the focused tile (Q1), the top row fades (Q2), the Search stop (Q6), <main>-only page swaps with a crossfade (Q7) and
placeholder shapes. Spec: docs/specs/JY-259-tv-revamp.md, phase 2.

tv.js runs under node in the fake DOM of test_tv_mode.py, with a virtual clock (the 150 ms debounce), an Image stub
(the only network use allowed is the browser's /img fetch) and fetch / XMLHttpRequest / htmx.ajax stubs that record
any other call. The server side: every Home tile carries its hero data from the caches, friend by friend."""
import html as htmllib
import json
import re
import shutil
import subprocess
import time

import pytest

from hub import guest, media_item, shell
from tests.hub.fake_jellyfin import FRIEND_ID, OTHER_ID
from tests.hub.guest_pages import TV_UA, movie, sign_in
from tests.hub.test_tv_home_jy259 import (cache_show, fc, main, show_read, tv_page,  # noqa: F401 (fc is a fixture)
                                          watched_ep)
from tests.hub.test_tv_mode import FAKE_DOM
from tests.hub.tv_css import root_px

TV_JS = (shell.TEMPLATES_DIR.parent / "static" / "tv.js").read_text(encoding="utf-8")
TV_CSS = (shell.TEMPLATES_DIR.parent / "static" / "tv.css").read_text(encoding="utf-8")

# The TV Home in small, as base.html + area_shelves.html draw it in phase 2: the bar (brand = Home, four pills, the
# Search stop, the sign-out pill, the search dialog), then <main>: the two backdrop layers, the hero, two rows of tiles
# that carry data-hero. title() is a title page; discover() a Discover page with its own field.
HARNESS = FAKE_DOM + r"""
var clock = 0, tid = 0, queue = [], images = [], net = [], FADE = '0s';
setTimeout = function (f, ms) { tid++; queue.push({ id: tid, f: f, at: clock + (ms || 0) }); return tid; };
function clearTimeout(id) { queue = queue.filter(function (t) { return t.id !== id; }); }
function advance(ms) {
  var end = clock + ms;
  for (;;) {
    var due = queue.filter(function (t) { return t.at <= end; }).sort(function (a, b) { return a.at - b.at || a.id - b.id; })[0];
    if (!due) break;
    queue.splice(queue.indexOf(due), 1); clock = Math.max(clock, due.at); due.f();
  }
  clock = end;
}
flush = function () { advance(0); };
var pres = [], ls = {}, metaTag = 'v1';
function Image() { pres.push(this); }
Object.defineProperty(Image.prototype, 'src', { set: function (v) { this._src = v; images.push(v); },
                                                get: function () { return this._src; } });
function loaded(url) { pres.filter(function (p) { return p._src === url && p.onload; }).forEach(function (p) { p.onload(); }); }
Date.now = function () { return clock; };
window.localStorage = { getItem: function (k) { return k in ls ? ls[k] : null; }, setItem: function (k, v) { ls[k] = String(v); },
                        removeItem: function (k) { delete ls[k]; } };
window.sessionStorage.removeItem = function (k) { delete store[k]; };
function fetch() { net.push('fetch'); }
function XMLHttpRequest() { net.push('xhr'); }
var htmx = { ajax: function () { net.push('htmx.ajax'); } };
var gcs0 = getComputedStyle;
getComputedStyle = function (el) {
  var s = gcs0(el);
  s.getPropertyValue = function (n) { return n === '--tv-fade' ? FADE : ''; };
  return s;
};
document.startViewTransition = function () {};
var bar, brand, stop, dlg, sfield, sout, A, B, heroTitle, titleSets = [];
function header(open) {
  brand = new El('a', { name: 'brand', cls: ['brand', 'brand-home'], attrs: { href: '/a/media' }, top: 10, left: 50 });
  if (open === 'home') brand.attrs['aria-current'] = 'page';
  var nav = new El('nav', { cls: ['toplinks'], top: 10, left: 300 });
  [['movies', '/media/movies'], ['tv', '/media/tv'], ['diary', '/media/diary'], ['discover', '/media/discover']]
    .forEach(function (s, i) {
      var attrs = { href: s[1] };
      if (s[0] === open) attrs['aria-current'] = 'page';
      nav.append(new El('a', { name: 'pill-' + s[0], attrs: attrs, top: 10, left: 300 + i * 150 }));
    });
  stop = new El('button', { name: 'stop', attrs: { type: 'button', 'data-tv-search-open': '' }, top: 10, left: 1000 });
  var chip = new El('button', { name: 'userchip', cls: ['userchip'], top: 10, left: 1500 });
  sfield = new El('input', { name: 'sfield', attrs: { type: 'search', 'data-tv-search': '' }, top: 100, left: 860 });
  sfield.value = ''; sfield.readOnly = true;
  sout = new El('div', { attrs: { id: 'tv-search-out' }, top: 200, kids: [new El('div', { cls: ['reqgrid-wrap'], attrs: { 'data-q': '' }, top: 200 })] });
  dlg = new El('dialog', { name: 'dlg', attrs: { id: 'tv-search-dlg', hidden: '' }, top: 80, kids: [
    new El('form', { cls: ['toolbar', 'discover-search'], top: 100, kids: [sfield] }), sout] });
  dlg.open = false;
  dlg.showModal = function () { this.open = true; this.attrs.open = ''; delete this.attrs.hidden; };
  dlg.close = function () { this.open = false; delete this.attrs.open; this.attrs.hidden = ''; fire('close', { target: this }); };
  bar = new El('header', { cls: ['topbar'], top: 0, kids: [new El('div', { cls: ['topbar-in'], top: 0, kids: [brand, nav, stop, chip] }), dlg] });
  body.append(bar);
}
function hero(i) { return JSON.stringify({ bd: '/img/jfb:' + i + '?h=1280&t=T' + i, blur: false, title: 'Title ' + i,
                                           facts: '2024 · Film · 1h 4' + i + 'm', syn: 'Synopsis ' + i }); }
function home(main) {
  A = new El('img', { name: 'A', attrs: { src: '/img/jfb:1?h=1280&t=T1' } });
  B = new El('img', { name: 'B', cls: ['tv-bd-next'] });
  main.append(new El('div', { cls: ['tv-bd'], kids: [A, B] }));
  heroTitle = new El('p', { cls: ['tv-hero-title'] });
  var t = 'Title 1';
  Object.defineProperty(heroTitle, 'textContent', { get: function () { return t; },
                                                     set: function (v) { t = v; titleSets.push(v); } });
  main.append(new El('div', { cls: ['tv-hero'], top: 80, kids: [new El('p', { cls: ['tv-hero-eyebrow'] }), heroTitle,
    new El('p', { cls: ['tv-hero-facts'] }), new El('p', { cls: ['tv-hero-syn'] })] }));
  [['Continue watching', 'Pick up where you left off', 1], ['Recently added', 'Just added', 6]].forEach(function (r, ri) {
    var row = new El('div', { cls: ['carousel', 'tvt-row'], top: 400 + ri * 300 });
    for (var n = r[2]; n < r[2] + 5; n++)
      row.append(new El('a', { name: 't' + n, cls: ['card-poster', 'tvt'], top: 400 + ri * 300, left: 100 + (n - r[2]) * 200,
                               attrs: { href: '/media/item/' + n, 'data-hero': hero(n) } }));
    main.append(new El('section', { cls: ['sec'], attrs: { 'data-hero-eyebrow': r[1] }, top: 380 + ri * 300, kids: [row] }));
  });
}
function title(main) {
  main.append(new El('a', { name: 'play', attrs: { href: '/jf/play', 'data-jf-id': 'x' }, top: 300 }));
}
function discover(main) {
  var own = new El('input', { name: 'own', attrs: { type: 'search', 'data-tv-search': '' }, top: 110, left: 860 });
  own.value = ''; own.readOnly = true;
  main.append(new El('form', { cls: ['toolbar', 'discover-search'], top: 110, kids: [own] }));
  main.append(new El('div', { cls: ['reqgrid-wrap'], top: 200, kids: [
    new El('a', { name: 'd1', cls: ['card-poster'], attrs: { href: '/media/title/movie/1' }, top: 250 })] }));
}
var mainEl;
function shell(open, fill) {   /* a full load */
  body.children.forEach(function (k) { k.parentElement = null; }); body.children = [];
  document.activeElement = body;
  if (metaTag !== null) body.append(new El('meta', { attrs: { name: 'joey-viewer', content: metaTag } }));
  header(open);
  mainEl = new El('main', { cls: ['page'], top: 60 }); body.append(mainEl); fill(mainEl);
}
function swapMain(fill) {   /* what htmx does to <main> after the beforeSwap below: the bar is left alone */
  var m = new El('main', { cls: ['page'], top: 60 });
  body.children[body.children.indexOf(mainEl)] = m; m.parentElement = body; mainEl.parentElement = null; mainEl = m;
  if (!document.activeElement.isConnected) document.activeElement = body;
  fill(m);
}
function key(k) { fire('keydown', { key: k, preventDefault: function () {} }); }
function click(el) { fire('click', { target: el, preventDefault: function () {}, stopImmediatePropagation: function () {} }); }
function now() { return document.activeElement === body ? 'body' : document.activeElement.name; }
function cur() { return document.querySelectorAll('.topbar a[href]').filter(function (a) { return a.getAttribute('aria-current') !== null; })
                          .map(function (a) { return a.name; }); }
function boot() {
/*TV_JS*/
}
function load(path, open, fill) { listeners = {}; queue = []; window.scrollY = 0; window.location.pathname = path; shell(open, fill); boot(); flush(); }
var out = {};
/*SCENARIO*/
console.log(JSON.stringify(out));
"""


def run(tmp_path, scenario: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = tmp_path / "p2.js"
    script.write_text(HARNESS.replace("/*TV_JS*/", TV_JS).replace("/*SCENARIO*/", scenario), encoding="utf-8")
    r = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ---- Q1 A: the hero follows focus ----

def test_the_hero_swap_reads_the_page_only_and_fetches_nothing_but_img(tmp_path):
    out = run(tmp_path, r"""
load('/a/media', 'home', home);
out.first = now(); advance(150);
out.first_title = heroTitle.textContent;
key('ArrowRight'); advance(150);
var box = document.querySelector('.tv-hero');
out.title = heroTitle.textContent;
out.eyebrow = box.children[0].textContent; out.facts = box.children[2].textContent; out.syn = box.children[3].textContent;
out.b_off_before_load = B.getAttribute('src') === null;   /* nothing on a layer until decoded */
loaded('/img/jfb:2?h=1280&t=T2');
out.b_src = B.getAttribute('src');
out.b_off = B.classList.contains('is-off'); out.a_off = A.classList.contains('is-off');
key('ArrowDown'); advance(150); loaded('/img/jfb:7?h=1280&t=T7');
out.row2_eyebrow = box.children[0].textContent; out.row2_title = heroTitle.textContent;
out.a_src = A.getAttribute('src');   /* the layer that was off takes the next backdrop */
out.images = images; out.net = net;
""")
    assert out["first"] == "t1" and out["first_title"] == "Title 1"
    assert out["title"] == "Title 2" and out["eyebrow"] == "Pick up where you left off"
    assert out["facts"] == "2024 · Film · 1h 42m" and out["syn"] == "Synopsis 2"
    assert out["b_src"] == "/img/jfb:2?h=1280&t=T2" and out["b_off_before_load"]     # decoded first, then shown
    assert not out["b_off"] and out["a_off"]                                           # then the crossfade
    assert out["row2_eyebrow"] == "Just added" and out["row2_title"] == "Title 7"
    assert out["a_src"] == "/img/jfb:7?h=1280&t=T7"
    assert out["net"] == []                                                            # no fetch, xhr or htmx call
    assert out["images"] and all(u.startswith("/img/") for u in out["images"])        # only the /img warm-ups
    assert "/img/jfb:3?h=1280&t=T3" in out["images"]                                    # the right-hand neighbour
    assert "/img/jfb:6?h=1280&t=T6" in out["images"] and "/img/jfb:8?h=1280&t=T8" in out["images"]


def test_the_hero_waits_150ms_and_only_the_last_tile_of_a_fast_run_lands(tmp_path):
    out = run(tmp_path, r"""
load('/a/media', 'home', home);
advance(150); titleSets.length = 0;
key('ArrowRight'); advance(149);
out.at149 = heroTitle.textContent;
advance(1);
out.at150 = heroTitle.textContent;
titleSets.length = 0;
key('ArrowRight'); advance(60); key('ArrowRight'); advance(60); key('ArrowRight'); advance(149);
out.mid = heroTitle.textContent; out.sets_mid = titleSets.slice();
advance(1);
out.end = heroTitle.textContent; out.sets = titleSets.slice();
""")
    assert out["at149"] == "Title 1" and out["at150"] == "Title 2"
    assert out["mid"] == "Title 2" and out["sets_mid"] == []
    assert out["end"] == "Title 5" and out["sets"] == ["Title 5"]                     # one swap for three moves


# ---- Q2 A: the top row fades ----

def test_the_top_row_fades_while_focus_is_in_the_rows_and_returns_on_up(tmp_path):
    out = run(tmp_path, r"""
load('/a/media', 'home', home);
out.rows = bar.classList.contains('tv-dim');
key('ArrowUp'); key('ArrowUp');
out.at = now(); out.bar = bar.classList.contains('tv-dim');
key('ArrowDown');
out.back = bar.classList.contains('tv-dim');
""")
    assert out["rows"] is True
    assert out["at"] == "brand" and out["bar"] is False                                # Home's stop, full opacity
    assert out["back"] is True
    css = TV_CSS.replace("\n", " ")
    assert re.search(r"html\.tv \.topbar\.tv-dim \.topbar-in \{ opacity: \.4; \}", css)


# ---- Q6 A: the Search stop ----

def test_the_search_stop_opens_the_field_over_the_page_and_back_closes_it(tmp_path):
    out = run(tmp_path, r"""
load('/a/media', 'home', home);
key('ArrowRight'); out.from = now();
click(stop);
out.open = dlg.open; out.at = now(); out.editable = !sfield.readOnly; out.dim = bar.classList.contains('tv-dim');
sfield.value = 'dune'; sout.innerHTML = 'results';
out.closed = window.joeyTV.back();
out.open_after = dlg.open; out.after = now(); out.value = sfield.value; out.out = sout.innerHTML; out.locked = sfield.readOnly;
out.again = window.joeyTV.back();
load('/media/discover', 'discover', discover);
click(stop);
out.disc_open = dlg.open; out.disc_at = now();
""")
    assert out["open"] is True and out["at"] == "sfield" and out["editable"] is True   # one press: typing
    assert out["dim"] is False
    assert out["closed"] is True and out["open_after"] is False and out["after"] == "stop"
    assert out["value"] == "" and out["out"] == '<div class="reqgrid-wrap" data-q=""></div>' and out["locked"]
    assert out["again"] is False                                                       # nothing left to close
    assert out["disc_open"] is False and out["disc_at"] == "own"                       # Discover: its own field


# ---- Q7 A: <main>-only swaps; Back restores focus ----

def test_a_boosted_page_swaps_main_only_and_back_restores_focus_and_the_bar(tmp_path):
    out = run(tmp_path, r"""
load('/a/media', 'home', home);
var keepBar = bar, keepBrand = brand;
key('ArrowRight'); key('ArrowRight'); advance(150);
out.picked = now();
var page = '<html><head></head><body><header class="topbar"><div class="topbar-in"><a class="brand brand-home" href="/a/media">J</a>' +
  '<nav class="toplinks"><a href="/media/movies" aria-current="page">Movies <span class="waitcount">3</span></a><a href="/media/tv">TV</a></nav></div></header>' +
  '<main class="page"><a href="/jf/play">Play</a></main></body></html>';
var det = { boosted: true, shouldSwap: true, xhr: { responseText: page } };
key('Enter');
fire('htmx:beforeSwap', { detail: det });
out.target_is_main = det.target === mainEl; out.select = det.selectOverride; out.swap = det.swapOverride;
out.bar_cur = cur(); out.count = document.querySelector('.toplinks').children[0].innerHTML;
window.location.pathname = '/media/item/3'; swapMain(title);
fire('htmx:afterSettle', {}); flush();
out.title = now(); out.same_bar = document.querySelector('.topbar') === keepBar && brand === keepBrand;
/* Back: htmx puts the cached Home <main> back (its stale ring on t3 and on t1 included) */
window.location.pathname = '/a/media';
swapMain(home);
document.querySelector('main').querySelectorAll('.card-poster')[0].classList.add('tv-focus');
document.querySelector('main').querySelectorAll('.card-poster')[2].classList.add('tv-focus');
fire('htmx:historyRestore', { detail: {} }); flush(); advance(150);
out.back = now(); out.rings = document.querySelectorAll('.tv-focus').map(function (e) { return e.name; });
out.back_cur = cur(); out.back_hero = heroTitle.textContent;
/* a response that is not a shell page (sign-in): the whole body, as before */
var det2 = { boosted: true, shouldSwap: true, xhr: { responseText: '<html><body><form>sign in</form></body></html>' } };
fire('htmx:beforeSwap', { detail: det2 });
out.plain = det2.target === undefined && det2.selectOverride === undefined;
FADE = '200ms';
var det3 = { boosted: true, shouldSwap: true, xhr: { responseText: page } };
fire('htmx:beforeSwap', { detail: det3 });
out.fade_swap = det3.swapOverride;
""")
    assert out["picked"] == "t3"
    assert out["target_is_main"] and out["select"] == "main"
    assert out["swap"] == "outerHTML show:window:top"                                   # --tv-fade 0s: a cut
    assert out["fade_swap"] == "outerHTML show:window:top transition:true"              # above 0: the crossfade
    assert out["bar_cur"] == ["pill-movies"]                                            # the pill follows, no redraw
    assert out["count"] == 'Movies <span class="waitcount">3</span>'                    # review: counts from the response
    assert out["title"] == "play" and out["same_bar"]
    assert out["back"] == "t3" and out["rings"] == ["t3"]                               # JY-187 memory, one ring
    assert out["back_cur"] == ["brand"] and out["back_hero"] == "Title 3"
    assert out["plain"]


def test_tv_mode_keeps_main_snapshots_and_web_keeps_none(fc):   # noqa: F811
    tv = tv_page(fc)
    cfg = json.loads(re.search(r"<meta name=\"htmx-config\" content='([^']+)'>", tv).group(1))
    assert cfg == {"historyCacheSize": 10, "refreshOnHistoryMiss": True}
    assert '<main class="page" hx-history-elt>' in tv
    assert 'data-tv-search-open' in tv and 'id="tv-search-dlg"' in tv and 'hx-target="#tv-search-out"' in tv
    web = fc.get(guest.home_path()).text
    cfg = json.loads(re.search(r"<meta name=\"htmx-config\" content='([^']+)'>", web).group(1))
    assert cfg == {"historyCacheSize": 0, "refreshOnHistoryMiss": True}
    assert "hx-history-elt" not in web and "tv-search" not in web and "data-hero" not in web


def test_the_crossfade_is_one_css_variable_and_tiles_keep_a_placeholder_shape():
    css = re.sub(r"/\*.*?\*/", "", TV_CSS, flags=re.S)
    assert re.search(r"html\.tv \{ --tv-fade: 200ms; \}", css)
    assert re.search(r"\.tv-bd > img \{ transition: opacity var\(--tv-fade\) ease-out; \}", css)
    assert re.search(r"::view-transition-new\(tv-main\)[^{]*\{ animation-duration: var\(--tv-fade\); \}", css)
    assert "getPropertyValue('--tv-fade')" in TV_JS
    assert re.search(r"html\.tv \.card-pic > img \{ background-color: var\(--tv-surface-2\); \}", css)


# ---- the server side: hero data on every tile, from the caches, each friend's own ----

def _heroes(page: str) -> list[dict]:
    return [json.loads(htmllib.unescape(m)) for m in re.findall(r"data-hero='([^']*)'", page)]


def test_every_home_tile_carries_its_hero_and_the_first_matches_the_drawn_backdrop(fc):   # noqa: F811
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Film 01", "9001", at_min=30)]
    fc.fake.history[FRIEND_ID] = [watched_ep()]
    cache_show(FRIEND_ID, show_read())
    body = main(tv_page(fc))
    tiles = re.findall(r'<a class="card-poster tvt[^"]*"[^>]*>', body)
    heroes = _heroes(body)
    assert tiles and len(heroes) == len(tiles)
    drawn = htmllib.unescape(re.search(r'<div class="tv-bd" aria-hidden="true"><img src="([^"]+)"', body).group(1))
    assert heroes[0]["bd"] == drawn and heroes[0]["title"] == "Film 01"               # one browser-cache entry
    assert all(h["bd"] is None or h["bd"].startswith("/img/") for h in heroes)
    assert 'data-hero-eyebrow="Pick up where you left off"' in body and 'data-hero-eyebrow="Up next"' in body
    assert '<img class="tv-bd-next" alt="" decoding="async">' in body and 'class="tv-hero-syn"' in body


def test_each_friend_gets_hero_data_from_their_own_reads_only(fc):   # noqa: F811
    fid = "0001" * 8                                                    # Film 01, in both friends' library
    media_item._cache[(FRIEND_ID, fid)] = (time.time(), {"item": {"kind": "movie", "id": fid, "backdrops": 2,
                                                                   "overview": "Only FRIEND read this synopsis."}})
    fc.fake.resume[FRIEND_ID] = [movie("aaaa" * 8, "Friend Resume Film", "9001", at_min=30)]
    mine = main(tv_page(fc))
    assert "Only FRIEND read this synopsis." in mine and "Friend Resume Film" in mine
    sign_in(fc, fc.fake, OTHER_ID)
    other = main(tv_page(fc))
    assert "Only FRIEND read this synopsis." not in other and "Friend Resume Film" not in other
    assert all("Friend Resume Film" != h["title"] for h in _heroes(other))


def test_a_hostile_title_or_synopsis_cannot_leave_the_data_attribute():
    from tests.hub.test_tv_home_jy259 import _kit
    xss = "x' onfocus='alert(1)' <img src=x>"
    out = str(_kit().poster({"title": "T", "href": "/x", "poster": "jf:a",
                             "hero": {"bd": None, "blur": False, "title": xss, "facts": xss, "syn": xss}}))
    attr = re.search(r"data-hero='([^']*)'", out).group(1)
    assert json.loads(htmllib.unescape(attr))["syn"] == xss and "onfocus='" not in out and "<img src=x>" not in out


# ---- the 18 px floor for the new text, at every panel ----

@pytest.mark.parametrize("w,h", [(960, 540), (1280, 720), (1920, 1080), (3840, 2160)])
def test_the_new_text_holds_18px_at_every_panel(w, h):
    css = re.sub(r"/\*.*?\*/", "", TV_CSS, flags=re.S)
    for sel in (r"html\.tv \.tv-hero-syn ", r"html\.tv \.tv-searchdlg \.reqchip "):
        rule = re.search(sel + r"[^{]*\{([^}]*)\}", css).group(1)
        size = float(re.search(r"font-size: ([\d.]+)rem", rule).group(1))
        assert size * root_px(css, w, h) >= 18, (sel, w, h)


# ---- review fixes (2026-10-28) ----

def test_the_newest_focus_wins_the_backdrop_and_a_fading_layer_is_never_reloaded(tmp_path):
    """Flicker: an older backdrop decoded late never lands, and a swap inside the last fade waits for it to end."""
    out = run(tmp_path, r"""
FADE = '200ms';
load('/a/media', 'home', home);
advance(150);
key('ArrowRight'); advance(150);                 /* t2 asked */
key('ArrowRight'); advance(150);                 /* t3 asked: the newest */
loaded('/img/jfb:2?h=1280&t=T2');
out.after_old = [A.getAttribute('src'), B.getAttribute('src')];
loaded('/img/jfb:3?h=1280&t=T3');
out.after_new = [B.getAttribute('src'), B.classList.contains('is-off'), A.classList.contains('is-off')];
key('ArrowRight'); advance(150); loaded('/img/jfb:4?h=1280&t=T4');   /* 150 ms into a 200 ms fade */
out.mid_fade = A.getAttribute('src');
advance(49); out.at199 = A.getAttribute('src');
advance(1); out.at200 = [A.getAttribute('src'), A.classList.contains('is-off'), B.classList.contains('is-off')];
""")
    assert out["after_old"] == ["/img/jfb:1?h=1280&t=T1", None]                          # the stale one never lands
    assert out["after_new"] == ["/img/jfb:3?h=1280&t=T3", False, True]
    assert out["mid_fade"] == "/img/jfb:1?h=1280&t=T1" and out["at199"] == "/img/jfb:1?h=1280&t=T1"
    assert out["at200"] == ["/img/jfb:4?h=1280&t=T4", False, True]


def test_the_history_cache_is_dropped_for_a_new_viewer_on_sign_in_and_on_sign_out(tmp_path):
    """Privacy: on a shared TV nobody can Back into the previous viewer's cached pages."""
    out = run(tmp_path, r"""
ls['htmx-history-cache'] = '[{"url":"/a/media"}]'; ls['joeyTV.viewer'] = 'v1';
load('/a/media', 'home', home);
out.same = 'htmx-history-cache' in ls;
metaTag = 'v2'; load('/a/media', 'home', home);
out.other = 'htmx-history-cache' in ls; out.stamp = ls['joeyTV.viewer'];
ls['htmx-history-cache'] = 'x'; store['joeyTV.back'] = '{}';
metaTag = ''; load('/signin', 'home', home);
out.signin = 'htmx-history-cache' in ls; out.signin_stamp = 'joeyTV.viewer' in ls; out.mem = 'joeyTV.back' in store;
metaTag = 'v2'; load('/a/media', 'home', home); ls['htmx-history-cache'] = 'y';
fire('submit', { target: new El('form', { attrs: { action: '/signout', method: 'post' } }) });
out.signout = 'htmx-history-cache' in ls;
""")
    assert out["same"] is True                                                            # same viewer: kept
    assert out["other"] is False and out["stamp"] == "v2"                                 # another viewer: dropped
    assert out["signin"] is False and out["signin_stamp"] is False and out["mem"] is False
    assert out["signout"] is False


def test_the_tv_page_names_its_viewer_by_a_one_way_tag_only(fc):   # noqa: F811
    tag = re.compile(r'<meta name="joey-viewer" content="([0-9a-f]*)">')
    page = tv_page(fc)
    mine = tag.search(page).group(1)
    assert len(mine) == 16 and FRIEND_ID not in page.split("</head>", 1)[0]
    assert not tag.search(fc.get(guest.home_path()).text)                                 # web: none
    sign_in(fc, fc.fake, OTHER_ID)
    other = tag.search(tv_page(fc)).group(1)
    assert len(other) == 16 and other != mine
    signin = fc.get("/signin", headers={"User-Agent": TV_UA}).text
    assert 'name="joey-viewer"' not in signin and "/static/tv.js" in signin              # tv.js there clears the cache
