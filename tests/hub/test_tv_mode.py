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


def test_tv_discover_is_the_six_column_grid_with_chips_and_the_panel(monkeypatch, tmp_path):
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
        assert re.search(r"\.poster-grid\.reqgrid \{ grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)", css)
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
FOCUS_HARNESS = r"""
var listeners = {};
function fire(name, ev) { (listeners[name] || []).forEach(function (f) { f(ev); }); }
function El(tag, opts) {
  opts = opts || {};
  this.tagName = tag.toUpperCase(); this.name = opts.name || tag; this.attrs = opts.attrs || {};
  this.cls = new Set(opts.cls || []); this.top = opts.top == null ? 300 : opts.top;
  this.parentElement = null; this.children = []; this.style = {};
  var self = this;
  this.classList = { add: function (c) { self.cls.add(c); }, remove: function (c) { self.cls.delete(c); },
                     contains: function (c) { return self.cls.has(c); } };
  (opts.kids || []).forEach(function (k) { self.append(k); });
}
El.prototype.append = function (k) { k.parentElement = this; this.children.push(k); };
El.prototype.getAttribute = function (a) { return a in this.attrs ? this.attrs[a] : null; };
El.prototype.removeAttribute = function (a) { delete this.attrs[a]; };
Object.defineProperty(El.prototype, 'isConnected', { get: function () {
  var p = this; while (p.parentElement) p = p.parentElement; return p === html; } });
El.prototype.getBoundingClientRect = function () {
  return { left: 100, top: this.top, width: 100, height: 40, right: 200, bottom: this.top + 40 };
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
function matches(el, sel) { return sel.split(',').some(function (s) { return simple(el, s.trim()); }); }
function all(root, sel) {
  var out = [];
  (function walk(n) { n.children.forEach(function (k) { if (matches(k, sel)) out.push(k); walk(k); }); })(root);
  return out;
}
El.prototype.querySelectorAll = function (sel) { return all(this, sel); };
El.prototype.querySelector = function (sel) { return all(this, sel)[0] || null; };
El.prototype.closest = function (sel) { for (var p = this; p; p = p.parentElement) if (matches(p, sel)) return p; return null; };
El.prototype.contains = function (o) { for (var p = o; p; p = p.parentElement) if (p === this) return true; return false; };
El.prototype.focus = function () { document.activeElement = this; fire('focusin', { target: this }); };
var html = new El('html'), body = new El('body');
html.append(body);
var document = {
  readyState: 'complete', documentElement: html, body: body, activeElement: body,
  addEventListener: function (n, f) { (listeners[n] = listeners[n] || []).push(f); },
  querySelectorAll: function (s) { return all(html, s); },
  querySelector: function (s) { return all(html, s)[0] || null; },
  contains: function (o) { return o.isConnected; }
};
var window = { innerHeight: 1080, innerWidth: 1920, scrollTo: function () {}, scrollBy: function () {}, location: {} };
function getComputedStyle(el) {
  return { visibility: 'visible', display: 'block', position: el.cls.has('topbar') ? 'sticky' : 'static' };
}
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
