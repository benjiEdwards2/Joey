"""Joey TV WP-B3 step 6 (2026-10-21; Q34, Q41, D-P8, DECISIONS D): TV mode.

`tv_mode(request)` is true ONLY on the media front, when the user agent carries the shell's token `JoeyTV/` (D-P8:
` JoeyTV/<semver> (<versionCode>)`) or the `tv=1` cookie is present; `?tv=1` sets that cookie (1 year, SameSite=Lax)
and `?tv=0` clears it - handled in GuestGate, so it works on every media-front page, the 404 page and /signin. In TV
mode `<html>` carries class `tv` and the page links /static/tv.css + /static/tv.js (vendored, no external asset). The
private front ignores all of it. tv.js exposes `window.joeyTV.back()` (the shell's BackPolicy asks it first, WP-B7)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hub import guest
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.fake_seerr import FakeSeerr, res
from tests.hub.guest_pages import TV_UA, guest_client, sign_in


@pytest.fixture()
def gc(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path)
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def is_tv(html: str) -> bool:
    head = html.split("</head>", 1)[0]
    on = bool(re.search(r'<html lang="en" class="tv"', html))
    assets = bool(re.search(r'href="/static/tv\.css\?v=\w+"', head)) and bool(re.search(r'src="/static/tv\.js\?v=\w+"', head))
    assert on == assets, "class tv and the TV assets go together"
    return on


def tv_cookie(r) -> list[str]:
    return [h for h in r.headers.get_list("set-cookie") if h.startswith("tv=")]


@pytest.mark.parametrize("path", ["/a/media", "/media/movies", "/no-such-page", "/signin"])
def test_ua_and_cookie_triggers(gc, path):
    assert not is_tv(gc.get(path).text)
    assert is_tv(gc.get(path, headers={"User-Agent": TV_UA}).text), path
    gc.cookies.set("tv", "1")
    assert is_tv(gc.get(path).text), path


def test_query_sets_and_clears_the_cookie(gc):
    r = gc.get("/media/movies?tv=1")
    assert is_tv(r.text)
    (line,) = tv_cookie(r)
    assert line.startswith("tv=1;") and "Max-Age=31536000" in line and "Path=/" in line and "SameSite=Lax" in line
    assert is_tv(gc.get("/media/tv").text)                      # persists
    r = gc.get("/media/tv?tv=0")
    assert not is_tv(r.text)
    (line,) = tv_cookie(r)
    assert line.startswith("tv=;") and "Max-Age=0" in line
    assert not is_tv(gc.get("/media/movies").text)              # cleared


def test_the_query_works_before_sign_in(monkeypatch, tmp_path):
    client, _ = guest_client(monkeypatch, tmp_path)
    with client as c:
        r = c.get("/signin?tv=1")
        assert is_tv(r.text) and tv_cookie(r)
        redirect = c.get("/media/movies?tv=1", follow_redirects=False)
        assert redirect.status_code == 303 and tv_cookie(redirect)


def test_the_private_front_ignores_tv_mode(monkeypatch, tmp_path):
    client, _ = guest_client(monkeypatch, tmp_path)
    monkeypatch.setenv("JOEY_FRONT", "private")
    with client as c:
        c.cookies.set("tv", "1")
        r = c.get("/media/movies?tv=1", headers={"User-Agent": TV_UA})
    assert not is_tv(r.text) and not tv_cookie(r)


def test_the_tv_assets_are_served_and_self_contained(gc):
    js = gc.get("/static/tv.js")
    css = gc.get("/static/tv.css")
    assert js.status_code == 200 and css.status_code == 200
    assert "window.joeyTV" in js.text and "back" in js.text
    for body in (js.text, css.text):
        assert not re.search(r"https?://", body.replace("http://www.w3.org/", "")), "no external asset"
        assert "@import" not in body


def test_tv_token_is_the_frozen_substring():
    assert guest.TV_UA_TOKEN == "JoeyTV/" and guest.TV_UA_TOKEN in TV_UA


# ---- the look (WP-B3 follow-on): tv.css is the WP-M mockup; none of it leaks into the shared sheet ----

def test_tv_css_has_no_hover_rule_and_keeps_the_floor(gc):
    css = re.sub(r"/\*.*?\*/", "", gc.get("/static/tv.css").text, flags=re.S)       # rules, not comments
    assert ":hover" not in css, "WP-M spec: no hover states anywhere in the TV UI"
    assert "(hover" not in css
    sizes = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", css)]
    assert sizes and min(sizes) >= 16, "WP-M spec: nothing under 16 px"
    assert re.search(r"\.brand b \{[^}]*font-size: 22px; font-weight: 700", css)        # brand text, 22 px bold
    assert "--tv-bar-fill: #f97316" in css                                              # the mockup's progress colour


def test_the_shared_sheet_carries_no_tv_rule(gc):
    shared = gc.get("/static/control-surface.css").text
    assert "html.tv" not in shared and ".tv-focus" not in shared
    assert gc.get("/static/control-surface.css", headers={"User-Agent": TV_UA}).text == shared   # TV mode adds a sheet, never edits one


def test_tv_overview_drops_the_head_band_and_paints_the_port(gc):
    plain = gc.get("/a/media").text
    tv = gc.get("/a/media", headers={"User-Agent": TV_UA}).text
    assert '<header class="pagehead">' in plain and '<header class="pagehead">' not in tv
    for html in (plain, tv):
        assert "<em>:8443</em>" in html and 'aria-label="Server address https://' in html and html.count("setup-addr") == 1


def test_tv_title_page_has_synopsis_and_rating_chips_only_in_tv_mode(gc):
    item = "f11f" * 8
    gc.fake.items[item] = {"Id": item, "Type": "Movie", "Name": "Chip Film", "ProductionYear": 2001,
                           "Overview": "A synopsis line.", "ProviderIds": {"Tmdb": "777"}, "RunTimeTicks": 100 * 600_000_000}
    plain = gc.get(f"/media/item/{item}").text
    tv = gc.get(f"/media/item/{item}", headers={"User-Agent": TV_UA}).text
    assert "tv-syn" not in plain and "tv-rate" not in plain and "Chip Film (2001)" in plain
    assert tv.count('name="score"') == 10 and "Your rating" in tv
    assert 'id="rate"' not in tv                                                         # no second picker below the fold
    assert 'class="tv-syn">A synopsis line.' in tv and "Chip Film (2001)" not in tv


def test_tv_discover_is_the_eight_column_grid_with_chips_and_the_panel(monkeypatch, tmp_path):
    """WP-B4 follow-on: Discover in TV mode = WP-M screen 10. The grid takes tv.css's six-column helper, every poster has
    its chip, the panel is the dialog; the rules are tv.css's own (html.tv scope, no :hover) - the page carries none."""
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyseerr": {"summary": "x", "requests": []}})
    seerr = FakeSeerr().install(monkeypatch)
    seerr.add_user(7, FRIEND_ID)
    seerr.titles[("movie", 701)] = {**res(701, "Harvest Moon Rising"), "tagline": "", "genres": []}
    seerr.shelves = {"/api/v1/discover/trending": [res(701, "Harvest Moon Rising"), res(603, "Salt and Static", status=5),
                                                   res(702, "Pale Horizon", status=2)],
                     "/api/v1/discover/movies": [], "/api/v1/discover/tv": [],
                     "/api/v1/discover/movies/upcoming": [], "/api/v1/discover/tv/upcoming": []}
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        tv = c.get("/media/discover", headers={"User-Agent": TV_UA}).text
        assert is_tv(tv) and 'class="poster-grid reqgrid"' in tv
        for tid, word in (("movie-701", "Request"), ("movie-603", "In library"), ("movie-702", "Requested")):
            assert re.search(rf'id="chip-{tid}"[^>]*>{word}<', tv)
        assert '<dialog id="req-dialog"' in tv and "data-req-open" in tv
        inline = "".join(re.findall(r"<style>(.*?)</style>", tv, flags=re.S))
        assert "html.tv" not in inline and ":hover" not in inline          # the TV look lives in tv.css only
        css = re.sub(r"/\*.*?\*/", "", c.get("/static/tv.css").text, flags=re.S)
        # JY-188 (2026-10-25, B.: "JY-186: scale B, chrome on"): six columns became eight (docs/specs/JY-188-tv-scale-b.md)
        assert re.search(r"\.poster-grid\.reqgrid \{ grid-template-columns: repeat\(8, minmax\(0, 1fr\)\)", css)
        assert ".reqdlg" in css and ".reqchip" in css and ":hover" not in css
        # the answer keeps the poster / title / overview and says it is waiting (screen 10: Done focused)
        done = c.post("/media/title/movie/701/request", content="panel=1", headers={
            "HX-Request": "true", "content-type": "application/x-www-form-urlencoded"}).text
        assert "Requested — waiting for approval" in done and "Harvest Moon Rising" in done and "Overview of Harvest Moon Rising." in done
        assert re.search(r"<button[^>]*data-close data-first[^>]*>Done</button>", done)


def test_focus_growth_and_ring_stay_inside_the_overscan_margin(gc):
    """W5 2026-10-22 (real TCL): a focused poster (scale 1.06 + 4 px ring 3 px out) reached 96 % of the height and
    4.6 % from the left. tv.js now keeps room for that growth when it scrolls a row into view, and grows first/last
    column posters inward; its constants must match tv.css."""
    js = gc.get("/static/tv.js").text
    css = gc.get("/static/tv.css").text
    scale = float(re.search(r"\.card-poster\.tv-focus \{[^}]*transform: scale\(([\d.]+)\)", css).group(1))
    ring = re.search(r"\.card-poster\.tv-focus \.card-pic \{[^}]*outline: (\d+)px solid[^}]*outline-offset: (\d+)px", css)
    assert re.search(r"POSTER_GROW = ([\d.]+)", js) and abs(float(re.search(r"POSTER_GROW = ([\d.]+)", js).group(1))
                                                           - (scale - 1) / 2) < 1e-9
    assert int(re.search(r"RING = (\d+)", js).group(1)) == int(ring.group(1)) + int(ring.group(2))
    assert "var bottom = window.innerHeight - OVERSCAN_Y - grow;" in js and "PAD + grow" in js
    assert re.search(r"OVERSCAN_Y = 27, OVERSCAN_X = 48", js) and "--tv-mx: 48px; --tv-my: 27px" in css
    assert "transformOrigin = b.left - grow < OVERSCAN_X ? 'left center'" in js and "'right center'" in js
    assert js.index("centreInShelf(el);") < js.index("edgeOrigin(el);   /*") < js.index("keepRowInView(el);\n  }")


def test_a_focus_the_webview_puts_on_the_top_bar_before_any_key_goes_to_the_first_target(gc):
    """W5 2026-10-22 (release build on the TCL): when the shell focused the WebView after a load, Android put DOM focus
    on the first focusable (the brand link), tv.js accepted it, and OK on a title page went to Overview instead of Play.
    Until the first remote key on a page, a top-bar focusin is redirected to first() (WP-M: title = Play, Overview =
    first poster) unless first() is itself in the top bar."""
    js = gc.get("/static/tv.js").text
    assert "var keyed = false;" in js
    fi = js[js.index("document.addEventListener('focusin'"):]
    assert fi.index("if (!keyed && e.target && e.target.closest && e.target.closest('.topbar'))") < fi.index("current = e.target;")
    assert "if (f && f !== e.target && !f.closest('.topbar')) { setFocus(f); return; }" in fi
    kd = js[js.index("document.addEventListener('keydown'"):]
    assert kd.index("keyed = true;") < kd.index("if (!KEYS[e.key]")


def test_a_top_bar_focus_already_held_when_tv_js_starts_goes_to_the_first_target(gc):
    """W5 2026-10-22 (real TCL): OK on a poster is a full page load of /media/item/<id>; the WebView focused the brand
    before the deferred tv.js added its focusin listener, and restore() kept any existing focus, so the next OK went to
    Overview instead of Resume/Play. restore() (initial run, DOMContentLoaded, every htmx swap) now also replaces a
    top-bar focus by first() until the first remote key, unless first() is itself in the top bar."""
    js = gc.get("/static/tv.js").text
    rs = js[js.index("function restore() {"):]
    rs = rs[:rs.index("\n  }") + 4]
    assert "var a = active(), f = first();" in rs
    assert "if (!a || (!keyed && a.closest('.topbar') && f && !f.closest('.topbar'))) setFocus(f);" in rs
    assert "if (!active()) setFocus(first());" not in rs
    assert "document.addEventListener('DOMContentLoaded', restore);\n  else restore();" in js


def test_a_boosted_page_swap_or_back_resets_the_first_key_guard(gc):
    """W5 2026-10-22 (CDP focus/key log on the real TCL): OK on a poster in /media/movies is NOT a full page load but an
    hx-boost swap of /media/item/<id> into the same document. The Enter keydown set `keyed` on Movies, the WebView then
    focused the brand (the focused poster was gone) and both guards above let it stay, so OK went to Overview instead
    of Play. A boosted response that htmx swaps in, and an htmx history restore (Back), now reset `keyed`; a partial
    swap (request panel, dialog, shelf load) does not, so a user who moved into the top bar stays there."""
    js = gc.get("/static/tv.js").text
    bs = js[js.index("document.addEventListener('htmx:beforeSwap'"):]
    bs = bs[:bs.index("});") + 3]
    assert "if (e.detail.boosted && e.detail.shouldSwap) keyed = false;" in bs
    assert js.count("keyed = false;") == 3 and js.count("keyed = true;") == 1   # the declaration + these two resets
    # reset before the swap (so before the WebView's focusin on the brand) and before afterSettle's restore()
    assert js.index("'htmx:beforeSwap'") < js.index("document.addEventListener('htmx:afterSettle', restore);")
    assert "document.addEventListener('htmx:historyRestore', function () { keyed = false; restore(); });" in js
    assert "document.addEventListener('htmx:historyRestore', restore);" not in js
    # the vendored htmx 2.0.4 merges the request's `boosted` into the beforeSwap detail and reads shouldSwap after it
    htmx = gc.get("/static/htmx.min.js").text
    assert 'version:"2.0.4"' in htmx
    assert "const H={xhr:p,target:c,requestConfig:C,etc:i,boosted:_," in htmx
    assert "var m=ce({shouldSwap:a,serverResponse:p,isError:f,ignoreTitle:h,selectOverride:d,swapOverride:g},i);" in htmx
    assert 'if(!he(l,"htmx:beforeSwap",m))return;' in htmx and "if(m.shouldSwap){" in htmx
    assert ('Ve(r,n,o);Te();Kt(o.tasks);E().setTimeout(function(){window.scrollTo(0,t.scroll)},0);Bt=e;'
            'he(ne().body,"htmx:historyRestore"') in htmx                     # history restore fires after the swap
    # tv.js loads after joey.js, so its beforeSwap listener sees joey.js's asset-version shouldSwap = false
    page = gc.get("/media/movies", headers={"User-Agent": TV_UA}).text
    assert page.index("/static/joey.js?v=") < page.index("/static/tv.js?v=")


# A fake DOM just big enough for tv.js: elements, simple selectors, focus() firing focusin, document listeners.
# JY-187 (2026-10-24): also descendant selectors ("a b"), an x position, a window scroll offset (the top bar is pinned),
# window listeners (fire('window:pageshow', ...)), sessionStorage and a timer queue run by flush().
FAKE_DOM = r"""
var listeners = {}, timers = [], store = {};
function fire(name, ev) { (listeners[name] || []).slice().forEach(function (f) { f(ev); }); }
function setTimeout(f) { timers.push(f); }
function flush() { while (timers.length) timers.shift()(); }
function El(tag, opts) {
  opts = opts || {};
  this.tagName = tag.toUpperCase(); this.name = opts.name || tag; this.attrs = opts.attrs || {};
  this.cls = new Set(opts.cls || []); this.top = opts.top == null ? 300 : opts.top;
  this.left = opts.left == null ? 100 : opts.left;
  this.parentElement = null; this.children = []; this.style = {};
  var self = this;
  this.classList = { add: function (c) { self.cls.add(c); }, remove: function (c) { self.cls.delete(c); },
                     contains: function (c) { return self.cls.has(c); } };
  (opts.kids || []).forEach(function (k) { self.append(k); });
}
El.prototype.append = function (k) { k.parentElement = this; this.children.push(k); };
El.prototype.getAttribute = function (a) { return a in this.attrs ? this.attrs[a] : null; };
El.prototype.removeAttribute = function (a) { delete this.attrs[a]; };
El.prototype.setAttribute = function (a, v) { this.attrs[a] = String(v); };   /* JY-192 */
Object.defineProperty(El.prototype, 'isConnected', { get: function () {
  var p = this; while (p.parentElement) p = p.parentElement; return p === html; } });
El.prototype.getBoundingClientRect = function () {
  var t = this.top - (this.closest('.topbar') ? 0 : window.scrollY);
  return { left: this.left, top: t, width: 100, height: 40, right: this.left + 100, bottom: t + 40 };
};
function simple(el, s) {
  var m = /^([a-z]+)?(.*)$/.exec(s), part, re = /\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]|:not\(([^)]*)\)/g;
  if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
  while ((part = re.exec(m[2]))) {
    if (part[1] && !el.cls.has(part[1])) return false;
    if (part[2] && (!(part[2] in el.attrs) || (part[3] != null && el.attrs[part[2]] !== part[3]))) return false;
    if (part[4] && simple(el, part[4])) return false;
  }
  return true;
}
function matches(el, sel) {
  return sel.split(',').some(function (s) {
    var parts = s.trim().split(/\s+/), i = parts.length - 1;
    if (!simple(el, parts[i--])) return false;
    for (var p = el.parentElement; p && i >= 0; p = p.parentElement) if (simple(p, parts[i])) i--;
    return i < 0;
  });
}
function all(root, sel) {
  var out = [];
  (function walk(n) { n.children.forEach(function (k) { if (matches(k, sel)) out.push(k); walk(k); }); })(root);
  return out;
}
El.prototype.querySelectorAll = function (sel) { return all(this, sel); };
El.prototype.querySelector = function (sel) { return all(this, sel)[0] || null; };
El.prototype.closest = function (sel) { for (var p = this; p; p = p.parentElement) if (matches(p, sel)) return p; return null; };
El.prototype.contains = function (o) { for (var p = o; p; p = p.parentElement) if (p === this) return true; return false; };
El.prototype.focus = function () {
  var was = document.activeElement;
  if (was === this) return;
  document.activeElement = this;
  if (was && was !== body) fire('focusout', { target: was });
  fire('focusin', { target: this });
};
/* JY-194: blur() and dispatchEvent() (records the event types an element was sent, e.g. htmx's 'search' trigger) */
El.prototype.blur = function () {
  if (document.activeElement !== this) return;
  document.activeElement = body; fire('focusout', { target: this });
};
El.prototype.dispatchEvent = function (ev) { (this.sent = this.sent || []).push(ev.type); return true; };
var html = new El('html'), body = new El('body');
html.append(body);
var document = {
  readyState: 'complete', documentElement: html, body: body, activeElement: body,
  addEventListener: function (n, f) { (listeners[n] = listeners[n] || []).push(f); },
  querySelectorAll: function (s) { return all(html, s); },
  querySelector: function (s) { return all(html, s)[0] || null; },
  contains: function (o) { return o.isConnected; }
};
var window = {
  innerHeight: 1080, innerWidth: 1920, scrollY: 0,
  scrollTo: function (x, y) { window.scrollY = Math.max(0, y); },
  scrollBy: function (x, y) { window.scrollY = Math.max(0, window.scrollY + y); },
  location: { pathname: '/media/movies', search: '' },
  addEventListener: function (n, f) { (listeners['window:' + n] = listeners['window:' + n] || []).push(f); },
  sessionStorage: { getItem: function (k) { return k in store ? store[k] : null; },
                    setItem: function (k, v) { store[k] = String(v); } }
};
function getComputedStyle(el) {
  return { visibility: 'visible', display: 'block', position: el.cls.has('topbar') ? 'sticky' : 'static' };
}
"""

FOCUS_HARNESS = FAKE_DOM + r"""
var brand;
function page(kind) {   /* a new page in <body>, as a boosted swap or a history restore puts it there */
  body.children.forEach(function (k) { k.parentElement = null; });
  body.children = [];
  if (!document.activeElement.isConnected) document.activeElement = body;
  brand = new El('a', { name: 'brand', cls: ['brand'], attrs: { href: '/a/media' }, top: 10 });
  body.append(new El('header', { cls: ['topbar'], kids: [brand] }));
  var main = new El('main', { cls: ['page'] });
  if (kind === 'title') {
    main.append(new El('a', { name: 'play', attrs: { href: '/jf/play', 'data-jf-id': 'x' } }));
    main.append(new El('a', { name: 'overview-link', attrs: { href: '/a/media' }, top: 400 }));
  } else {
    main.append(new El('a', { name: 'poster', cls: ['card-poster'], attrs: { href: '/media/item/1' } }));
  }
  body.append(main);
}
function key(k) { fire('keydown', { key: k, preventDefault: function () {} }); }
function now() { return document.activeElement === body ? 'body' : document.activeElement.name; }
page('movies');
/*TV_JS*/
var out = {};
/* 1. the TCL log: OK on a poster -> boosted swap of the title page -> afterSettle -> the WebView focuses the brand */
key('Enter');
fire('htmx:beforeSwap', { detail: { boosted: true, shouldSwap: true } });
page('title'); fire('htmx:afterSettle', {}); brand.focus();
out.boosted_late_brand = now();
/* 2. the same, the brand focused during the swap (before afterSettle's restore()) */
page('movies'); key('Enter');
fire('htmx:beforeSwap', { detail: { boosted: true, shouldSwap: true } });
page('title'); brand.focus(); fire('htmx:afterSettle', {});
out.boosted_early_brand = now();
/* 3. the user moves up into the top bar, then a partial swap (shelf / request panel): the focus stays there */
key('ArrowUp');
out.moved_up = now();
fire('htmx:beforeSwap', { detail: { boosted: false, shouldSwap: true } });
fire('htmx:afterSettle', {}); brand.focus();
out.partial_swap = now();
/* 4. a boosted response htmx does not swap (joey.js's asset-version reload, an error status) changes nothing */
fire('htmx:beforeSwap', { detail: { boosted: true, shouldSwap: false } });
brand.focus();
out.unswapped_boost = now();
/* 5. Back: the cached Movies body is restored, the brand focused during the restore / after it */
key('Enter'); page('movies'); brand.focus(); fire('htmx:historyRestore', { detail: {} });
out.back_early_brand = now();
key('Enter'); page('movies'); fire('htmx:historyRestore', { detail: {} }); brand.focus();
out.back_late_brand = now();
console.log(JSON.stringify(out));
"""


def test_the_first_key_guard_follows_boosted_swaps_under_node(gc, tmp_path):
    """The reset above, run: tv.js in a fake DOM. The W5 sequence (key, boosted swap, brand focus) and Back land on
    first() (title page: Play, Movies: the first poster); a partial or unswapped response leaves the top bar alone.
    Before the fix every case ended on the brand."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = tmp_path / "focus.js"
    script.write_text(FOCUS_HARNESS.replace("/*TV_JS*/", gc.get("/static/tv.js").text), encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {
        "boosted_late_brand": "play", "boosted_early_brand": "play",
        "moved_up": "brand", "partial_swap": "brand", "unswapped_boost": "brand",
        "back_early_brand": "poster", "back_late_brand": "poster"}


# ---- JY-187 (U1, 2026-10-24): Back memory, Up to the current pill, first focus on an empty tab, Down to chip 1 ----
# Findings B1/B2/B3/G3/P5 in JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md. The pages below are the TV layouts in small:
# the top bar (brand, the five guest sections, the sign-out pill), Movies (sticky sub-tabs + a 4-column grid), Overview
# (rows of posters, one title twice) and a title page (Play / Trailer / Watchlist, the 1-10 chips, a shelf). load() runs
# tv.js as a new document does (a full load: Back's reload, the hand-off reopen); boosted() is an htmx boosted swap.
TV_PAGES = FAKE_DOM + r"""
var brand;
function shell(open) {
  body.children.forEach(function (k) { k.parentElement = null; });
  body.children = [];
  if (!document.activeElement.isConnected) document.activeElement = body;
  brand = new El('a', { name: 'brand', cls: ['brand'], attrs: { href: '/a/media' }, top: 10, left: 50 });
  var bar = new El('nav', { cls: ['toplinks'], top: 10, left: 300 });
  [['overview', '/a/media'], ['movies', '/media/movies'], ['tv', '/media/tv'], ['diary', '/media/diary'],
   ['discover', '/media/discover']].forEach(function (s, i) {
    var attrs = { href: s[1] };
    if (s[0] === open) attrs['aria-current'] = 'page';
    bar.append(new El('a', { name: 'pill-' + s[0], attrs: attrs, top: 10, left: 300 + i * 150 }));
  });
  var chip = new El('button', { name: 'userchip', cls: ['userchip'], top: 10, left: 1500 });
  body.append(new El('header', { cls: ['topbar'], top: 0, kids: [brand, bar, chip] }));
  var main = new El('main', { cls: ['page'], top: 60 });
  body.append(main);
  return main;
}
function poster(main, name, id, row, col) {
  main.append(new El('a', { name: name, cls: ['card-poster'], attrs: { href: '/media/item/' + id }, top: 200 + row * 400,
                            left: 100 + col * 200 }));
}
function movies(rows, tab) {
  var main = shell('movies'), sub = new El('nav', { cls: ['sectabs', 'sub'], top: 90, left: 100 });
  [['myfilms', '/media/movies'], ['watchlist', '/media/movies/watchlist'], ['torate', '/media/movies/to-rate']]
    .forEach(function (t, i) {
      var attrs = { href: t[1] };
      if (t[0] === (tab || 'myfilms')) attrs['aria-current'] = 'page';
      sub.append(new El('a', { name: 'tab-' + t[0], attrs: attrs, top: 90, left: 100 + i * 150 }));
    });
  main.append(new El('header', { cls: ['pagehead'], top: 80, kids: [sub] }));
  if (!rows) main.append(new El('a', { name: 'empty-link', cls: ['btn'], attrs: { href: '/media/discover' }, top: 300 }));
  for (var n = 1; n <= rows * 4; n++) poster(main, 'p' + n, n, Math.floor((n - 1) / 4), (n - 1) % 4);
}
function overview() {   /* 4 rows of 4; o14 (row 4, column 2) is the same title as o2 */
  var main = shell('overview');
  for (var n = 1; n <= 16; n++) poster(main, 'o' + n, n === 14 ? 102 : 100 + n, Math.floor((n - 1) / 4), (n - 1) % 4);
}
function title() {
  var main = shell('movies');
  main.append(new El('div', { cls: ['hero-detail-btns'], kids: [
    new El('a', { name: 'play', attrs: { href: '/jf/play', 'data-jf-id': 'x' }, top: 300, left: 100 }),
    new El('a', { name: 'trailer', attrs: { href: '/trailer' }, top: 300, left: 300 }),
    new El('button', { name: 'watchlist', top: 300, left: 500 })] }));
  var pick = new El('form', { cls: ['ratepick'], kids: [new El('input', { attrs: { type: 'hidden' }, top: 380 }),
                                                        new El('span', { cls: ['microlabel'], top: 380 })] });
  for (var i = 1; i <= 10; i++) pick.append(new El('button', { name: 'chip' + i, attrs: { name: 'score' }, top: 380, left: 100 + (i - 1) * 70 }));
  main.append(new El('div', { cls: ['tv-rate'], kids: [pick] }));
  poster(main, 's1', 900, 1, 0);
}
/* JY-194: the friends' Discover page in TV mode: the search field (a full-width pill above the grid; this fake box is
   100 px wide, so it is put mid-screen as the real pill's centre is) and #discover-grid (.reqgrid-wrap, data-q = the
   query it shows) with 3 rows of 4 posters. results(q) is the htmx swap of the grid for a query. */
var field;
function discover(q) {
  var main = shell('discover');
  field = new El('input', { name: 'field', attrs: { type: 'search', name: 'q', 'data-tv-search': '' }, top: 110, left: 860 });
  field.value = q || '';
  main.append(new El('form', { cls: ['toolbar', 'discover-search'], top: 110, kids: [
    new El('div', { cls: ['search'], top: 110, kids: [field] })] }));
  results(q);
}
var gen = 0;
function results(q) {
  var main = document.querySelector('main'), old = main.querySelector('.reqgrid-wrap');
  if (old) { main.children.splice(main.children.indexOf(old), 1); old.parentElement = null; }
  var grid = new El('div', { name: 'grid', cls: ['reqgrid-wrap'], attrs: { id: 'discover-grid', 'data-q': q || '' }, top: 180 });
  gen++;
  for (var n = 1; n <= 12; n++) grid.append(new El('a', { name: (q ? 'r' : 'd') + n, cls: ['card-poster'],
    attrs: { href: '/media/title/movie/' + (q ? 500 : 100) + n, 'data-gen': String(gen) },
    top: 200 + Math.floor((n - 1) / 4) * 400, left: 100 + ((n - 1) % 4) * 200 }));
  main.append(grid);
}
function swapped(q) { results(q); fire('htmx:afterSettle', {}); flush(); }   /* the search partial lands */
function press(k) {   /* a key; true when tv.js prevented its default (no form submit, no native 'search' event) */
  var stopped = false;
  fire('keydown', { key: k, preventDefault: function () { stopped = true; } });
  return stopped;
}
function key(k) { fire('keydown', { key: k, preventDefault: function () {} }); }
function now() { return document.activeElement === body ? 'body' : document.activeElement.name; }
function boot() {
/*TV_JS*/
}
function load(path, build) {   /* a full page load: Back (historyCacheSize 0 + refreshOnHistoryMiss), the hand-off reopen */
  listeners = {}; timers = []; window.scrollY = 0; window.location.pathname = path;
  document.activeElement = body; build(); boot(); flush();
}
function boosted(path, build) {   /* OK on a link: htmx swaps the body, pushes the URL, settles, then scrolls to the top */
  key('Enter');
  fire('htmx:beforeSwap', { detail: { boosted: true, shouldSwap: true } });
  window.location.pathname = path; build();
  fire('htmx:afterSettle', {});
  window.scrollTo(0, 0);
  flush();
}
var out = {};
/*SCENARIO*/
console.log(JSON.stringify(out));
"""


def run_tv_pages(gc, tmp_path, scenario: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = tmp_path / "pages.js"
    script.write_text(TV_PAGES.replace("/*TV_JS*/", gc.get("/static/tv.js").text).replace("/*SCENARIO*/", scenario),
                      encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_back_restores_the_focused_poster_and_the_scroll_under_node(gc, tmp_path):
    """B1 (J3/J4 FAIL on the TCL): Back reloads the page and focus went to poster 1 at scroll 0. tv.js now remembers,
    per URL in sessionStorage, the link last focused with a key inside <main> and the scroll offset, and puts both back
    on a full load (Back, the hand-off reopen), a boosted swap (also after htmx's own scroll to the top) and a pageshow
    from the back-forward cache. A top-bar focus is never remembered; a link no longer on the page falls back to
    first(); of two links to the same title the remembered one comes back."""
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/movies', function () { movies(5); });
out.fresh = now();
['ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowRight'].forEach(key);
out.picked = now(); out.picked_y = window.scrollY;
boosted('/media/item/18', title);
out.title = now();
load('/media/movies', function () { movies(5); });
out.back = now(); out.back_y = window.scrollY;
brand.focus();
out.back_late_brand = now();
boosted('/a/media', overview);
out.ov_fresh = now();
['ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowRight'].forEach(key);
out.ov_picked = now(); out.ov_y = window.scrollY;
boosted('/media/movies', function () { movies(5); });
out.mv_again = now(); out.mv_again_y = window.scrollY;
boosted('/a/media', overview);
out.ov_back = now(); out.ov_back_y = window.scrollY;
key('ArrowLeft'); brand.focus();
fire('window:pageshow', { persisted: true });
out.pageshow = now();
while (now().indexOf('pill-') !== 0 && now() !== 'brand') { out.last_in_main = document.activeElement.attrs.href; key('ArrowUp'); }
out.top = now();
var mem = JSON.parse(store['joeyTV.back'] || '{}');   /* JY-192: by name (tv.js keeps a second key, joeyTV.trail) */
out.mem_overview = mem['/a/media'] && mem['/a/media'].h;
load('/media/movies', function () { movies(2); });
out.missing = now();
""")
    assert out["fresh"] == "p1" and out["picked"] == "p18" and out["picked_y"] > 700
    assert out["title"] == "play"
    assert out["back"] == "p18" and abs(out["back_y"] - out["picked_y"]) < 1                 # J3/J4: focus + scroll
    assert out["back_late_brand"] == "p18"                                                 # the WebView's brand focus
    assert out["ov_fresh"] == "o1" and out["ov_picked"] == "o14" and out["ov_y"] > 300
    assert out["mv_again"] == "p18" and abs(out["mv_again_y"] - out["picked_y"]) < 1       # boosted, after htmx's scroll
    assert out["ov_back"] == "o14" and abs(out["ov_back_y"] - out["ov_y"]) < 1             # the second link to item 102
    assert out["pageshow"] == "o13"
    assert out["top"] == "pill-overview" and out["last_in_main"].startswith("/media/item/")
    assert out["mem_overview"] == out["last_in_main"]                                      # the top bar is not remembered
    assert out["missing"] == "p1"


def test_up_from_the_page_lands_on_the_current_section_pill_under_node(gc, tmp_path):
    """B2/B3 (J5, J8): Up from the sub-tabs or a poster went to the nearest top-bar control, the brand logo, so the
    sign-out pill was 7 presses from an Overview poster. Up into the top bar now lands on `.toplinks a[aria-current]`
    (the open section); inside the top bar Up / Left / Right are unchanged."""
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/movies', function () { movies(2); });
out.stops = [];
['ArrowUp', 'ArrowUp', 'ArrowUp', 'ArrowRight'].forEach(function (k) { key(k); out.stops.push(now()); });
load('/a/media', overview);
out.signout = [];
['ArrowUp', 'ArrowRight', 'ArrowRight', 'ArrowRight', 'ArrowRight', 'ArrowRight'].forEach(function (k) {
  key(k); out.signout.push(now());
});
""")
    assert out["stops"] == ["tab-myfilms", "pill-movies", "pill-movies", "pill-tv"]
    assert out["signout"] == ["pill-overview", "pill-movies", "pill-tv", "pill-diary", "pill-discover", "userchip"]


def test_first_focus_on_an_empty_tab_is_the_current_sub_tab_under_node(gc, tmp_path):
    """G3: on an empty Watchlist / To rate tab first focus landed on "My films" (the first focusable). With no Play and
    no poster it is now the current sub-tab; a poster still wins when there is one."""
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/movies/watchlist', function () { movies(0, 'watchlist'); });
out.empty = now();
load('/media/movies/to-rate', function () { movies(0, 'torate'); });
out.empty_torate = now();
load('/media/movies', function () { movies(1); });
out.with_posters = now();
""")
    assert out == {"empty": "tab-watchlist", "empty_torate": "tab-torate", "with_posters": "p1"}


def test_down_from_the_title_buttons_lands_on_chip_one_under_node(gc, tmp_path):
    """P5 (J9): Down from the title buttons landed on the nearest rating chip (8 from Watchlist). Down from a
    `.hero-detail-btns` control into `.tv-rate` now lands on its first control; the rest of the walk is unchanged."""
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/item/1', title);
out.stops = [now()];
['ArrowRight', 'ArrowRight', 'ArrowDown', 'ArrowRight', 'ArrowDown'].forEach(function (k) { key(k); out.stops.push(now()); });
load('/media/item/2', title);
key('ArrowDown');
out.from_play = now();
""")
    assert out["stops"] == ["play", "trailer", "watchlist", "chip1", "chip2", "s1"]
    assert out["from_play"] == "chip1"


def test_the_tv_pages_carry_what_the_jy187_rules_read(gc):
    """The node tests above skip in the gate (no node there); this one runs everywhere. The rules read the current
    section pill (`.toplinks a[aria-current]`) and sub-tab (`.sectabs.sub [aria-current]`) on a TV Movies tab and the
    title buttons (`.hero-detail-btns`) above the chips (`.tv-rate`); tv.js names those selectors and keeps its memory
    in sessionStorage, restored on pageshow too."""
    tv = {"User-Agent": TV_UA}
    page = gc.get("/media/movies/to-rate", headers=tv).text
    assert is_tv(page)
    bar = re.search(r'<nav class="toplinks"[^>]*>(.*?)</nav>', page, flags=re.S).group(1)
    assert re.findall(r'<a href="([^"]+)" aria-current="page">', bar) == ["/media/movies"]
    sub = re.search(r'<nav class="sectabs sub"[^>]*>(.*?)</nav>', page, flags=re.S).group(1)
    assert re.findall(r'<a href="([^"]+)" aria-current="page">', sub) == ["/media/movies/to-rate"]
    item = "f11f" * 8
    gc.fake.items[item] = {"Id": item, "Type": "Movie", "Name": "Chip Film", "ProductionYear": 2001,
                           "Overview": "A synopsis line.", "ProviderIds": {"Tmdb": "777"}, "RunTimeTicks": 100 * 600_000_000}
    film = gc.get(f"/media/item/{item}", headers=tv).text
    assert film.index('class="hero-detail-btns"') < film.index('<div class="tv-rate"')   # JY-192: the strip gains id + hidden
    js = gc.get("/static/tv.js").text
    for needle in (".toplinks a[aria-current]", "'.sectabs.sub [aria-current]'", "'.hero-detail-btns'", "'.tv-rate'",
                   "window.sessionStorage", "addEventListener('pageshow'"):
        assert needle in js, needle


# ---- JY-194 (U8, 2026-10-25): Discover search on the TV (finding R2; tv-v2 shell 04-discover screens 1 to 3) ----

def test_up_from_the_grid_reaches_the_search_field_and_down_comes_back_under_node(gc, tmp_path):
    """First focus stays on the first poster (or the JY-187 memory). Up from the first row lands on the search field,
    not the top bar (from poster 1 the brand scored nearer); Up from the field is JY-187's current pill; Down from the
    field is the first poster. Passing over the field never makes it editable (no keyboard pops up)."""
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/discover', function () { discover(''); });
out.first = now();
key('ArrowUp'); out.up = now(); out.locked = field.readOnly === true;
key('ArrowUp'); out.up2 = now();
load('/media/discover', function () { discover(''); });
key('ArrowUp'); key('ArrowDown'); out.down = now();
key('ArrowRight'); key('ArrowRight'); key('ArrowRight'); key('ArrowUp'); out.up_from_4 = now();
key('ArrowDown'); out.down_again = now(); out.still_locked = field.readOnly === true;
""")
    assert out == {"first": "d1", "up": "field", "locked": True, "up2": "pill-discover", "down": "d1",
                   "up_from_4": "field", "down_again": "d1", "still_locked": True}


def test_ok_opens_the_keyboard_and_enter_shows_the_results_under_node(gc, tmp_path):
    """OK on the read-only field makes it editable (the Android TV keyboard comes up for an editable focused input) and
    stops the form submit. A results swap while typing leaves focus and the keyboard alone. Enter in the editable field
    never submits the form: it fires the field's own htmx 'search' trigger only when the grid does not already show
    that query (no second call after the debounce), then focus goes to the first result; leaving locks the field."""
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/discover', function () { discover(''); });
key('ArrowUp');
out.ok_stopped = press('Enter'); out.ok_editable = field.readOnly === false; out.ok_on = now();
field.value = 'apothecary';
swapped('apothecary');                         /* the debounced keyup trigger's swap lands while typing */
out.typing_on = now(); out.typing_editable = field.readOnly === false;
out.enter_stopped = press('Enter'); out.enter_sent = (field.sent || []).length;
out.enter_on = now(); out.enter_locked = field.readOnly === true;
key('ArrowUp'); press('Enter');
field.value = 'apothecary diaries';            /* Enter before the debounce fired: the 'search' trigger runs now */
out.enter2_stopped = press('Enter'); out.enter2_sent = (field.sent || []).slice();
swapped('apothecary diaries');
out.after_swap = now(); out.after_swap_gen = document.activeElement.attrs['data-gen'] === String(gen);
""")
    assert out == {"ok_stopped": True, "ok_editable": True, "ok_on": "field",
                   "typing_on": "field", "typing_editable": True,
                   "enter_stopped": True, "enter_sent": 0, "enter_on": "r1", "enter_locked": True,
                   "enter2_stopped": True, "enter2_sent": ["search"], "after_swap": "r1", "after_swap_gen": True}


def test_back_from_results_returns_to_trending_with_the_field_focused_under_node(gc, tmp_path):
    """Back (the shell asks window.joeyTV.back() first) with a query showing clears the field, fires its 'search'
    trigger with no query (the cached trending grid), focuses the field and returns true; with no query it returns
    false as before (the shell goes back). Also for a page loaded with ?q=."""
    out = run_tv_pages(gc, tmp_path, r"""
load('/media/discover', function () { discover(''); });
key('ArrowUp'); press('Enter'); field.value = 'apothecary'; swapped('apothecary'); press('Enter');
out.back = window.joeyTV.back(); out.value = field.value; out.sent = (field.sent || []).slice(); out.on = now();
out.locked = field.readOnly === true;
swapped('');
out.trending_on = now();
out.back_again = window.joeyTV.back();
load('/media/discover', function () { discover('apothecary'); });
out.loaded_q_first = now();
out.loaded_back = window.joeyTV.back(); out.loaded_on = now(); out.loaded_value = field.value;
""")
    assert out == {"back": True, "value": "", "sent": ["search"], "on": "field", "locked": True,
                   "trending_on": "field", "back_again": False,
                   "loaded_q_first": "r1", "loaded_back": True, "loaded_on": "field", "loaded_value": ""}


def test_tv_discover_shows_the_search_field_on_the_existing_trigger(monkeypatch, tmp_path):
    """Gate-run (no node): the friends' TV Discover page carries the field tv.js reads, on the existing endpoint and the
    existing debounce (keyup changed delay:400ms, plus the 'search' event); the grid says which query it shows; tv.css
    shows this one toolbar (every other stays hidden) as the 56 px pill; the household Discover is untouched."""
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyseerr": {"summary": "x", "requests": []}})
    seerr = FakeSeerr().install(monkeypatch)
    seerr.add_user(7, FRIEND_ID)
    seerr.shelves = {"/api/v1/discover/trending": [res(701, "Harvest Moon Rising")],
                     "/api/v1/discover/movies": [], "/api/v1/discover/tv": [],
                     "/api/v1/discover/movies/upcoming": [], "/api/v1/discover/tv/upcoming": []}
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        tv = c.get("/media/discover", headers={"User-Agent": TV_UA}).text
        assert is_tv(tv)
        form = re.search(r'<form class="toolbar discover-search"[^>]*>(.*?)</form>', tv, flags=re.S)
        assert form, "the search form carries the class tv.css shows"
        field = re.search(r"<input[^>]*data-tv-search[^>]*>", form.group(1), flags=re.S).group(0)
        assert 'hx-get="/media/discover/search"' in field and 'hx-trigger="keyup changed delay:400ms, search"' in field
        assert 'hx-target="#discover-grid"' in field and "readonly" not in field     # tv.js locks it, only in TV mode
        assert '<div id="discover-grid" class="reqgrid-wrap" data-q="">' in tv
        part = c.get("/media/discover/search?q=harvest", headers={"User-Agent": TV_UA, "HX-Request": "true"}).text
        assert '<div id="discover-grid" class="reqgrid-wrap" data-q="harvest">' in part
        css = re.sub(r"/\*.*?\*/", "", c.get("/static/tv.css").text, flags=re.S)
        js = c.get("/static/tv.js").text
    assert re.search(r"html\.tv form\.toolbar[,{ ]", css)                                 # the other toolbars stay hidden
    assert re.search(r"html\.tv form\.toolbar\.discover-search \{[^}]*display: block", css)
    assert re.search(r"html\.tv \.discover-search \.input \{[^}]*height: 56px", css)
    for needle in ("'[data-tv-search]'", "'.reqgrid-wrap'", "'data-q'", "new Event('search')"):
        assert needle in js, needle
    household = (Path(guest.__file__).parent / "templates" / "media_discover.html").read_text(encoding="utf-8")
    assert "data-tv-search" not in household and "discover-search" not in household


def test_enter_before_the_debounce_sends_one_request_under_node(gc, tmp_path):
    """Review should-fix (2026-10-25): type fast and press Enter within 400 ms, and Enter's search ran, then the pending
    keyup debounce sent the same query again. tv.js now cancels (htmx:beforeRequest) a keyup request from the field for
    the query Enter already sent or the grid already shows; the 'search' requests and a new query still go out, also
    the same query typed again after Back."""
    out = run_tv_pages(gc, tmp_path, r"""
function request(type) {   /* htmx asks before it sends; true = tv.js cancelled it */
  var stopped = false;
  fire('htmx:beforeRequest', { detail: { elt: field, requestConfig: { triggeringEvent: { type: type } } },
                               preventDefault: function () { stopped = true; } });
  return stopped;
}
load('/media/discover', function () { discover(''); });
key('ArrowUp'); press('Enter');
field.value = 'apothecary';
press('Enter');
out.enter_search = request('search');
out.late_keyup = request('keyup');
swapped('apothecary');
out.keyup_after_swap = request('keyup');
key('ArrowUp'); press('Enter'); field.value = 'apothecary diaries';
out.new_query = request('keyup');
window.joeyTV.back(); out.back_search = request('search'); swapped('');
press('Enter'); field.value = 'apothecary';
out.same_again = request('keyup');
""")
    assert out == {"enter_search": False, "late_keyup": True, "keyup_after_swap": True, "new_query": False,
                   "back_search": False, "same_again": False}


# ---- JY-188 (U2): density B, compact chrome, the 18 px floor, scrim, contrast, sign-in collapse, 404 layout ----

def _tv_css(gc) -> str:
    return re.sub(r"/\*.*?\*/", "", gc.get("/static/tv.css").text, flags=re.S)


def _lum(hexcolor: str) -> float:
    rgb = [int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_jy188_every_font_size_in_tv_css_is_at_least_18px(gc):
    sizes = [float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", _tv_css(gc))]
    assert sizes and min(sizes) >= 18, f"JY-188 (O2/R4/Y3): nothing under 18 px, found {min(sizes)}"


def test_jy188_density_b_with_compact_chrome(gc):
    css = _tv_css(gc)
    assert "--tv-bar: 64px" in css and re.search(r"\.topbar-in \{[^}]*padding: var\(--tv-my\) var\(--tv-mx\) 1px", css)   # 27 + 36 + 1
    assert re.search(r"\.sectabs\.sub a \{[^}]*height: 36px", css)                                                      # 64 + 4 + 36 = 104
    assert re.search(r"\.carousel > \* \{ flex: 0 0 104px; width: 104px; \}", css)
    assert re.search(r"\.carousel \{ gap: 14px;", css)
    assert re.search(r"\.libgrid, html\.tv \.poster-grid\.reqgrid \{ grid-template-columns: repeat\(8, minmax\(0, 1fr\)\); gap: 8px 14px", css)
    # caption: title 18 one line always; meta 18 under the focused card only
    assert re.search(r"\.card-poster \.row-title \{[^}]*font-size: 18px; line-height: 20px; height: 20px", css)
    assert re.search(r"\.card-poster \.row-meta \{[^}]*font-size: 18px;[^}]*visibility: hidden", css)
    assert re.search(r"\.card-poster\.tv-focus \.row-meta \{ visibility: visible", css)
    assert "repeat(6" not in css and "132px" not in css


def test_jy188_scrim_and_text_greys(gc):
    css = _tv_css(gc)
    assert re.search(r"\.hero-detail-bd \{ background-image: linear-gradient\(90deg[^;]*var\(--bd-pick\)", css)
    assert re.search(r"\.tv-facts \{[^}]*color: var\(--tv-t3\)", css)
    assert re.search(r"\.tv-syn \{[^}]*color: var\(--tv-t2\)", css)
    assert re.search(r"html\.tv \.sep[^{]*\{ color: var\(--tv-t4\)", css)


def test_jy188_play_button_is_4_5_to_1_or_better(gc):
    css = _tv_css(gc)
    colour = re.search(r"--tv-primary: (#[0-9a-f]{6})", css).group(1)
    ratio = (_lum("#ffffff") + 0.05) / (_lum(colour) + 0.05)
    assert ratio >= 4.5, ratio
    assert re.search(r"\.hero-detail-btns \.btn-white \{ background: var\(--tv-primary\)", css)


def test_jy188_sign_in_form_collapses_the_quick_connect_block(gc):
    assert re.search(r"\.signin-panel:has\(details\[open\]\) #qc \{ display: none; \}", _tv_css(gc))


def test_jy188_404_has_a_tv_layout(gc):
    css = _tv_css(gc)
    assert re.search(r"\.sec\.nf \{[^}]*align-items: center", css) and re.search(r"\.sec\.nf \.nf-back \{[^}]*min-height: 56px", css)
    html = gc.get("/nope-not-a-page", headers={"User-Agent": TV_UA}).text
    assert 'class="sec narrow nf"' in html and 'class="nf-back"' in html
