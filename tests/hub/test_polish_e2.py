"""WP E2 UI polish batch (2026-10-13, review_ui.md section (c)): template / stylesheet / script pins for U1, U2, U6, U8,
U10, U11, U16, U17, U18, U19, U21, U22, U23 and the evaluation's P3c / P6 / font preload. Source-level on purpose: each
check pins the markup or rule that carries the behaviour (the rendering pages have their own tests)."""
import re

from tests.hub.helpers import env  # noqa: F401  (fixture: the film-page env, Jellyfin + Jellyseerr faked)
from tests.hub.test_area_pages import site  # noqa: F401  (fixture: get(route) -> (hub.main, <main> html))
from pathlib import Path

HUB = Path(__file__).resolve().parents[2] / "hub"
TEMPLATES = HUB / "templates"
CSS = (HUB / "static" / "control-surface.css").read_text(encoding="utf-8")
JS = (HUB / "static" / "joey.js").read_text(encoding="utf-8")
KEEP = 'hx-swap="innerHTML show:none"'


def tpl(name):
    return (TEMPLATES / name).read_text(encoding="utf-8")


def rules(css=CSS):
    """Flattened `selector{body}` text with comments stripped (one space between tokens)."""
    return re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", css, flags=re.S))


# U1 --------------------------------------------------------------------------------------------------------------

def test_action_forms_keep_the_scroll_position():
    """Mark watched / Reset / Hide / season toggle, watchlist x, Follow / Unfollow, server Ignore / Unignore all re-render
    the same page: they swap the boosted body with show:none (the F1 pattern) instead of jumping to the top."""
    for name, expected in (("_resume_acts.html", 5), ("media_watchlist.html", 1), ("media_following.html", 1),
                           ("_follow_show.html", 1), ("_film_makers.html", 1), ("_film_collection.html", 1),
                           ("media_person.html", 1), ("server.html", 2)):
        src = tpl(name)
        forms = [m for m in re.findall(r'<form[^>]*method="post"[^>]*>', src)
                 if "/ignore" in m or "/unignore" in m or name != "server.html"]
        assert len(forms) == expected, (name, len(forms))
        assert all(KEEP in f for f in forms), (name, [f for f in forms if KEEP not in f])


# U2 + load bar ---------------------------------------------------------------------------------------------------

def test_loadbar_markup_and_rules():
    base = tpl("base.html")
    assert '<body hx-boost="true" hx-indicator="#loadbar">' in base
    assert '<div id="loadbar" class="loadbar htmx-indicator" aria-hidden="true"></div>' in base
    flat = rules()
    bar = re.search(r"\.loadbar \{([^}]*)\}", flat).group(1)
    assert "position: fixed" in bar and "height: 2px" in bar and "var(--primary)" in bar and "pointer-events: none" in bar
    assert "bottom: calc(56px + var(--tab-lift) + env(safe-area-inset-bottom))" in bar       # above the phone tab bar
    assert re.search(r"@media \(min-width: 768px\) \{ \.loadbar \{ bottom: auto; top: env\(safe-area-inset-top, 0px\); \} \}", flat)
    shown = re.search(r"\.loadbar\.htmx-indicator\.htmx-request \{([^}]*)\}", flat).group(1)
    assert "opacity: 1" in shown and re.search(r"transition: opacity \.2s \.15s", shown)    # appears after ~150 ms
    assert re.search(r"@media \(prefers-reduced-motion: reduce\) \{ \.loadbar \{ animation: none; background: var\(--primary\); \} \}", flat)
    assert "a.htmx-request, button.htmx-request { opacity: .6; }" in flat


def test_every_page_carries_the_loadbar(site):
    from fastapi.testclient import TestClient
    main, _ = site("/")
    with TestClient(main.app) as c:
        html = c.get("/?owner_view=both").text
    assert 'hx-indicator="#loadbar"' in html and html.count('id="loadbar"') == 1


# Font preload ----------------------------------------------------------------------------------------------------

def test_font_preload_is_the_exact_url_the_stylesheet_requests(site):
    from fastapi.testclient import TestClient
    base = tpl("base.html")
    pre = re.search(r'<link rel="preload" href="([^"]+)" as="font" type="font/woff2" crossorigin>', base)
    assert pre, "no GeistVF preload"
    face = re.search(r'font-family: "Geist"; src: url\("([^"]+)"\)', CSS).group(1)
    # the stylesheet is /static/control-surface.css, so its url() resolves under /static/: the preload must match it
    assert pre.group(1) == "/static/" + face == "/static/fonts/GeistVF.woff2"
    assert base.index('rel="preload"') < base.index('rel="stylesheet"')
    main, _ = site("/")
    with TestClient(main.app) as c:
        assert 'rel="preload" href="/static/fonts/GeistVF.woff2"' in c.get("/?owner_view=both").text
        r = c.get(pre.group(1))
        assert r.status_code == 200 and r.content[:4] == b"wOF2"


# P3c prefetch cancel on scroll -------------------------------------------------------------------------------------

def test_prefetch_script_cancels_on_touchmove_and_fires_on_a_still_touch():
    block = JS.split("F2 fast item pages", 1)[1]
    for ev in ("touchstart", "touchmove", "touchend", "touchcancel", "mouseover"):
        assert f"addEventListener('{ev}'" in block, ev
    assert "setTimeout(function () { pending = null; go(href); }, 60)" in block      # the 60 ms hover / hold path


def test_prefetch_behaviour_under_node():
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    block = JS.split("F2 fast item pages", 1)[1]
    block = block[block.index("(function () {"):]
    harness = """
const listeners = {}, fetched = [], timers = [];
const document = {addEventListener: (t, f) => { listeners[t] = f; }};
global.setTimeout = (f, ms) => { timers.push({f, ms}); return timers.length; };
global.clearTimeout = (id) => { if (id) timers[id - 1] = null; };
global.fetch = (href) => { fetched.push(href); return {then: (ok) => ok()}; };
%s
const link = (href) => ({target: {closest: () => ({getAttribute: () => href})}});
const flush = () => { timers.forEach((t) => t && t.f()); timers.length = 0; };
// 1. touchstart then touchmove (a scroll): nothing is fetched, even after the 60 ms
listeners.touchstart(link('/media/item/a')); listeners.touchmove({}); flush();
// 2. a quick tap: touchstart then touchend before 60 ms -> fetched at touchend
listeners.touchstart(link('/media/item/b')); listeners.touchend({});
// 3. a held touch: the 60 ms timer fires it
listeners.touchstart(link('/media/item/c')); flush();
// 4. hover: 60 ms path unchanged
listeners.mouseover(link('/media/title/movie/5')); if (timers.filter(Boolean)[0].ms !== 60) throw new Error('hover delay');
flush();
console.log(JSON.stringify(fetched));
""" % block
    out = subprocess.run([node, "-e", harness], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    # a (scrolled) is never fetched; b (quick tap), c (held 60 ms) and the hover link are
    assert out.stdout.strip() == '["/media/item/b","/media/item/c","/media/title/movie/5"]'


# U8 tap targets, U10 weather, U11 carousels, U15 contrast, U18 / U19, U21 ------------------------------------------

def test_phone_tap_targets_come_last_in_the_file():
    flat = rules()
    tail = flat[flat.index("@media (max-width: 767px) { .ratepick .chip"):]
    assert "height: 40px; min-width: 40px" in tail and ".ratepick { gap: 6px; }" in tail
    assert ".btn-mini { padding: 12px; margin: -8px; }" in tail
    assert ".sechead > a { padding: 10px 0 10px 12px; margin: -10px 0; }" in tail
    assert ".seg a, .sectabs a { min-height: 36px; }" in tail
    # the block beats the base rules above; E4 (2026-10-13): later dated tail blocks (E4 film page, ...) may follow it as
    # long as none of them restyles these controls again
    after = tail.split(".seg a, .sectabs a { min-height: 36px; } }", 1)[1]
    for sel in (".ratepick .chip", ".ratepick {", ".btn-mini {", ".sechead > a", ".seg a", ".sectabs a"):
        assert sel not in after, sel


def test_weather_phone_order_and_chart_text():
    flat = rules()
    assert "@media (max-width: 1099px) { .wxapp > .wxweek { order: 1; } .wxapp > .wxhourly { order: 2; } .wxapp > .wxradar { order: 3; } }" in flat
    assert "@media (max-width: 639px) { .wxchart text { font-size: 24px; } }" in flat
    assert "@media (min-width: 1100px) { .wxapp {" in flat            # the two-column desktop layout is untouched


def test_carousel_peek_and_gutter():
    flat = rules()
    assert ".carousel > * { flex: 0 0 104px; width: 104px; scroll-snap-align: start; }" in flat
    assert ".carousel { scroll-padding-inline: 16px; }" in flat
    assert "scroll-padding-inline: 0; }" in flat.split("@media (min-width: 640px) { .carousel {", 1)[1]
    assert 16 + 3 * (104 + 12) == 364                                  # 390 px phone: about 26 px of the 4th card shows


def test_contrast_tokens_and_no_tiny_text():
    flat = rules()
    assert "--text-5: #82828b;" in flat and "--text-5: #71717a" not in flat
    # inactive phone tab labels and the mini icon button sit on --text-4
    assert re.search(r"\.tabbar > a, \.tabbar summary \{[^}]*font-size: 11px; color: var\(--text-4\)", flat)
    assert re.search(r"\.btn-mini \{[^}]*color: var\(--text-4\)", flat)
    sizes = [float(x) for x in re.findall(r"font-size: ([\d.]+)px", flat)]
    assert min(sizes) >= 10, sorted(set(sizes))[:3]


def test_hover_lift_is_hover_capable_only_and_still_under_reduced_motion():
    flat = rules()
    assert "@media (hover: hover) { .card-poster:hover img { transform: translateY(-4px); } }" in flat
    assert "@media (hover: hover) { .card-cell:hover .card-pic > img { transform: translateY(-4px); } }" in flat
    assert not re.search(r"(?<!\{ )\.card-(poster|cell):hover[^{]*\{ transform", flat)      # no unguarded lift left
    assert re.search(r"@media \(prefers-reduced-motion: reduce\) \{ \.card-poster img, \.card-pic > img, [^}]*transition: none; \}", flat)


def test_anchors_clear_the_sticky_bar_globally():
    flat = rules()
    assert "[id] { scroll-margin-top: 72px; }" in flat
    assert ".seasons, .epseason { scroll-margin-top" not in flat      # the old two-class rule is folded in


def test_glimpse_stats_are_one_row_of_four():
    assert ".wxglimpse .stats { grid-template-columns: repeat(4, minmax(0, 1fr)); }" in rules()
    assert 'class="sec wxglimpse"' in tpl("_weather_glimpse.html")


# U16 headings ---------------------------------------------------------------------------------------------------

def test_section_labels_are_headings():
    for p in TEMPLATES.glob("*.html"):
        assert '<div class="seclabel"' not in p.read_text(encoding="utf-8"), p.name
    assert "h2.seclabel { display: block; font-size: 12px; }" in rules()


# U17 / U22 / U23 --------------------------------------------------------------------------------------------------

def test_a_full_shelf_prints_no_count_and_the_hub_shelf_links_to_the_diary():
    from hub.media_home import SHELF_MAX
    from hub.shell import templates
    assert templates.env.globals["shelf_max"] == SHELF_MAX          # E3: the templates read the global, not a literal 15
    hub = tpl("hub.html")
    assert "{% if shelf.watched | length < shelf_max %}" in hub
    assert '<a href="/media/diary">All</a>' in hub.split('id="recent"', 1)[1]
    assert 's["items"] | length < shelf_max' in tpl("area_shelves.html")
    assert "< 15" not in hub and "< 15" not in tpl("area_shelves.html")


def kpi_html(value):
    from hub import shell
    src = '{% from "_kpi.html" import kpi %}{{ kpi(none, "Micro", "Label", "hub", st, "you", value=value) }}'
    st = {"state": "fresh", "value": None, "note": None, "secondary": None, "age_text": ""}
    return shell.templates.env.from_string(src).render(st=st, value=value)


def test_tile_values_are_big_only_when_numeric():
    for numeric in ("3", "1,261", "98%", "12.5"):
        assert f'tile-value stat-number">{numeric}<' in kpi_html(numeric), numeric
    for word in ("All clear", "Ted Lasso", "The Mongoose", "LAN", "2 of 9"):
        assert f'tile-value stat-word">{word}<' in kpi_html(word), word


def test_placeholder_poster_is_zinc():
    from hub.images import fallback_svg
    svg = fallback_svg("Ab").decode()
    assert 'fill="#18181b"' in svg and 'fill="#52525b"' in svg and 'font-family="system-ui, sans-serif"' in svg
    assert "#1c1f26" not in svg and "#6b7280" not in svg and ">AB<" in svg


# P6 phone-sized backdrops ------------------------------------------------------------------------------------------

def pagehead_html(backdrop):
    from hub import shell
    src = '{% from "_pagehead.html" import pagehead %}{{ pagehead("T", backdrop=bd) }}'
    return shell.templates.env.from_string(src).render(bd=backdrop)


def test_backdrops_carry_a_small_size_for_tmdb_but_not_jellyfin_refs():
    tm = pagehead_html("tmdb:/wide.jpg")
    assert "--bd: url('/img/tmdb%3A/wide.jpg?h=1280'); --bd-sm: url('/img/tmdb%3A/wide.jpg?h=600')" in tm
    jf = pagehead_html("jfb:abc")
    assert "?h=1280" in jf and "--bd-sm" not in jf and "h=600" not in jf      # /img sizes a jfb: backdrop at 1280 anyway
    for name in ("media_film.html", "_film_macros.html"):
        assert "--bd-sm: url('/img/" in tpl(name) and "startswith('jfb:')" in tpl(name), name
    awards = tpl("media_awards.html")
    assert '<source media="(max-width: 767px)" srcset="/img/{{ hbd }}?h=600">' in awards and "startswith('jfb:')" in awards


def test_backdrop_gradients_paint_the_picked_size():
    flat = rules()
    assert "var(--bd)" not in re.sub(r"--bd-pick: var\(--bd\);|var\(--bd-sm, var\(--bd\)\)", "", flat)
    assert ".pagehead-bd, .hero-detail-bd, .partof-bd { --bd-pick: var(--bd); }" in flat
    assert "@media (max-width: 767px) { .pagehead-bd, .hero-detail-bd, .partof-bd { --bd-pick: var(--bd-sm, var(--bd)); } }" in flat


# U6 film page says things once ------------------------------------------------------------------------------------

def test_film_page_names_runtime_and_certificate_once_and_drops_the_extra_star(env):
    from tests.hub.film_page import whole
    from tests.hub.conftest import main_of
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    facts = re.search(r'<div class="facts-line">(.*?)</div>', b, re.S).group(1)
    assert "1h 52m" not in facts and b.count("1h 52m") == 1                         # the Numbers strip only
    assert "<dt>Runtime</dt>" not in b
    assert 'aria-label="Rate"' not in b and 'class="scorepill sp-you" href="#rate"' in b   # the pill stays, the star goes
    src = tpl("media_film.html")
    for verb in ("Added to your server", ">Watched {{", ">Requested {{"):
        assert verb not in src, verb
