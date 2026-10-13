"""Formerly test_apex_shell.py ("Apex" was the 2026-10-06 restyle round's name).
Shell (MediaHub guide, restyle Phase 2, 2026-10-06): top bar with one pill per section, phone tab bar with
five slots (the fifth becomes "More" past five sections), the _pagehead.html page header on every page, a
single dark theme (no toggle, no Google Fonts), a tokens-only stylesheet, and the hub greeting on the home clock."""
import html as htmlmod
import importlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.hub.helpers import ARR, JELLY, make_area, shelf_area, write_envelope, write_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "hub" / "templates"
CSS = (REPO_ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
SAMPLES = REPO_ROOT / "config" / "sample_snapshots"
MEL = ZoneInfo("Australia/Melbourne")


@pytest.fixture()
def main(tmp_path, monkeypatch):
    # nas_stats, not make_tile's open_meteo default: weather tiles never render on
    # area pages any more (2026-10-08), and beta's pagehead must count 1 tile.
    fixture = write_registry(tmp_path, shelf_area(), make_area("beta", "b-t", snapshot="nas_stats"),
                             make_area("gamma", "g-t", snapshot="nas_stats"))
    monkeypatch.setenv("AREAS_PATH", str(fixture))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    for cid, data in (("jellyfin", JELLY), ("arr", ARR)):
        write_envelope(tmp_path / "snaps", cid, age_minutes=1, data=data)
    import hub.main
    importlib.reload(hub.main)
    return hub.main


def _reload(tmp_path, monkeypatch, *areas):
    if areas:
        monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, *areas)))
    else:
        monkeypatch.delenv("AREAS_PATH", raising=False)
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    return hub.main


def topbar_of(html):
    return re.search(r'<header class="topbar">.*?</header>', html, re.S).group(0)


def pills_of(html):
    nav = re.search(r'<nav class="toplinks" aria-label="Sections">(.*?)</nav>', topbar_of(html), re.S).group(1)
    return re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', nav)


def tabbar_of(html):
    return re.search(r'<nav class="tabbar" aria-label="Sections \(phone\)">(.*)</nav>', html, re.S).group(1)


def bar_items(html):
    """(href, label) of the bar's own slots — the More sheet's links excluded."""
    bar = tabbar_of(html).split('<details class="more">', 1)[0]
    return re.findall(r'<a href="([^"]+)"[^>]*>.*?<span>([^<]+)</span></a>', bar, re.S)


# (a) top bar: brand, one pill per visible section in rail order, user chip; no rail, no toggle, no web fonts
def test_top_bar_has_one_pill_per_section_in_rail_order(main):
    with TestClient(main.app) as c:
        html = c.get("/").text
    assert pills_of(html) == [("/", "Hub"), ("/weather", "Weather"), ("/a/alpha", "Alpha"),
                              ("/a/beta", "Beta"), ("/a/gamma", "Gamma")]
    bar = topbar_of(html)
    assert '<a href="/" aria-current="page">Hub</a>' in bar and bar.count("aria-current") == 1
    assert "<small>Local preview</small>" in bar and '<span class="uname">Not signed in</span>' in bar


@pytest.mark.parametrize("route", ["/", "/a/beta", "/media/diary", "/weather"])
def test_single_dark_theme_and_no_rail_or_toggle(main, route):
    with TestClient(main.app) as c:
        html = c.get(route).text
    head = html.split("</head>", 1)[0]
    assert 'class="rail"' not in html and "railfoot" not in html and 'aria-label="Areas list"' not in html
    assert "data-theme" not in html and "joey-theme" not in html and "themetoggle" not in html
    assert "fonts.googleapis.com" not in html
    assert re.findall(r'<meta name="theme-color"[^>]*>', head) == ['<meta name="theme-color" content="#09090b">']


@pytest.mark.parametrize("route, current", [("/a/beta", "/a/beta"), ("/media/diary", "/a/alpha"),
                                            ("/a/alpha", "/a/alpha"), ("/weather", "/weather")])
def test_current_section_marked_once_in_both_bars(main, route, current):
    with TestClient(main.app) as c:
        html = c.get(route).text
    bar = topbar_of(html)
    if current == "/a/alpha":   # Media pages carry the Media phone bar (2026-10-07, test_media_phone_nav.py) and, from
        # 2026-10-13 (nav-tidy), the Media section row in the top bar INSTEAD of the Joey pills (test_media_nav.py)
        assert 'aria-label="Sections"' not in bar and ">Alpha<" not in bar and bar.count("aria-current") == 1
        return
    assert f'<a href="{current}" aria-current="page">' in bar and bar.count("aria-current") == 1
    assert re.search(rf'<a href="{current}" aria-current="page">', tabbar_of(html))


def test_brand_is_one_home_link_with_the_kangaroo_mark(main):
    with TestClient(main.app) as c:
        bar = topbar_of(c.get("/").text)
        img = c.get("/static/brand-joey.jpg")
    brand = re.search(r'<a class="brand" href="/" aria-label="Joey home">(.*?)</a>', bar, re.S).group(1)
    assert "/static/brand-joey.jpg?v=" in brand and 'width="24"' in brand and "<b>Joey</b>" in brand
    assert "joeyhome.net" not in bar
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8" and len(img.content) > 1000


# (b) phone tab bar: min(5, sections) slots, hidden areas absent, "More" only past five
def test_tab_bar_five_sections_no_more(main):
    with TestClient(main.app) as c:
        html = c.get("/").text
    assert [label for _, label in bar_items(html)] == ["Hub", "Weather", "Alpha", "Beta", "Gamma"]
    assert "<details" not in tabbar_of(html) and "More" not in tabbar_of(html)


def test_tab_bar_more_than_five_uses_more_sheet_and_skips_hidden(tmp_path, monkeypatch):
    m = _reload(tmp_path, monkeypatch, {**make_area("one"), "hidden": True}, make_area("two"),
                make_area("three"), make_area("four"), make_area("five"))
    with TestClient(m.app) as c:
        html = c.get("/").text
    tabs = tabbar_of(html)
    assert "/a/one" not in tabs and "/a/one" not in topbar_of(html)
    assert [label for _, label in bar_items(html)] == ["Hub", "Weather", "Two", "Three"]
    sheet = tabs.split('<div class="sheet">', 1)[1]
    assert "<span>More</span>" in tabs and "/a/four" in sheet and "/a/five" in sheet
    assert len(pills_of(html)) == 6


def test_more_is_marked_when_the_current_section_sits_in_the_sheet(tmp_path, monkeypatch):
    m = _reload(tmp_path, monkeypatch, *(make_area(a) for a in ("two", "three", "four", "five")))
    with TestClient(m.app) as c:
        html = c.get("/a/five").text
    assert '<summary class="on">' in tabbar_of(html)


def test_real_registry_sections_are_exactly_five(tmp_path, monkeypatch):
    m = _reload(tmp_path, monkeypatch)
    with TestClient(m.app) as c:
        html = c.get("/").text
    assert [label for _, label in bar_items(html)] == ["Hub", "Media", "Weather", "Calendar", "Server"]
    assert "<details" not in tabbar_of(html)
    assert [label for _, label in pills_of(html)] == ["Hub", "Media", "Weather", "Calendar", "Server"]


def test_rail_section_home_areas_sit_between_hub_and_weather(tmp_path, monkeypatch):
    m = _reload(tmp_path, monkeypatch, make_area("alpha"), {**make_area("beta"), "rail_section": "home"},
                make_area("gamma"))
    with TestClient(m.app) as c:
        html = c.get("/").text
    assert [h for h, _ in pills_of(html)] == ["/", "/a/beta", "/weather", "/a/alpha", "/a/gamma"]


# (c) the page header include: renders title / sub / eyebrow, and every page uses it
def test_pagehead_macro_renders_title_sub_eyebrow_and_backdrop(main):
    tpl = main.templates.env.from_string(
        '{% from "_pagehead.html" import pagehead %}'
        '{{ pagehead("Films", sub="12 seen · 3 to rate", eyebrow="This week", backdrop="bd/x.jpg",'
        ' actions=[{"href": "/go", "label": "Open"}]) }}')
    out = tpl.render()
    assert '<header class="pagehead">' in out and "<h1>Films</h1>" in out
    assert '<p class="pagehead-sub">12 seen · 3 to rate</p>' in out
    assert '<span class="eyebrow">This week</span>' in out
    assert "--bd: url('/img/bd/x.jpg?h=1280')" in out and '<a class="btn btn-glass" href="/go">Open</a>' in out
    plain = main.templates.env.from_string('{% from "_pagehead.html" import pagehead %}{{ pagehead("Hub") }}').render()
    assert "pagehead-bd" not in plain and "eyebrow" not in plain and "pagehead-sub" not in plain


@pytest.mark.parametrize("name", ["hub.html", "area.html", "media_base.html", "weather.html", "server.html"])
def test_five_templates_use_the_pagehead_include(name):
    src = (TEMPLATES / name).read_text(encoding="utf-8")
    assert '{% from "_pagehead.html" import pagehead %}' in src and 'class="pagehead' not in src


def test_media_pages_carry_section_tabs_in_the_header(main):
    with TestClient(main.app) as c:
        body = c.get("/media/movies").text.split("<main", 1)[1]
    head = re.search(r'<header class="pagehead">.*?</header>', body, re.S).group(0)
    assert '<nav class="sectabs sectabs-page" aria-label="Media sections">' in head
    assert '<nav class="sectabs sub"' in head
    assert head.index('class="sectabs sectabs-page"') < head.index("<h1>")   # tabs on the band, title at its foot


# (d) tokens on one dark :root block; no literal colour anywhere else
def _root_block():
    return re.search(r"(?m)^:root\s*\{(.*?)\}", CSS, re.S).group(1)


def test_tokens_defined_on_a_single_dark_root_block():
    root = _root_block()
    assert len(set(re.findall(r"(--[\w-]+)\s*:", root))) > 20
    assert "color-scheme: dark" in root
    assert "prefers-color-scheme" not in CSS and "[data-theme=" not in CSS


def test_no_literal_colour_outside_the_token_block():
    rest = CSS.replace(_root_block(), "")
    rest = re.sub(r"/\*.*?\*/", "", rest, flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", rest)
    assert not re.findall(r"\brgba?\(", rest)


def test_retired_shell_css_is_gone():
    for sel in (".rail", ".railsec", ".railfoot", ".themetoggle", "nav.tabs", "mediatabs", "--rail", "--ic-moon"):
        assert sel not in CSS, sel
    for sel in (".topbar", ".tabbar", ".pagehead", ".sectabs", ".toplinks"):
        assert re.search(rf"(?m)^{re.escape(sel)}\b", CSS), sel


# (e) the real pages render in the shell with the sample snapshots
@pytest.fixture()
def sample_client(tmp_path, monkeypatch):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    for p in SAMPLES.glob("*.json"):
        if not p.stem.startswith("_"):
            write_envelope(snaps, p.stem, age_minutes=1, data=json.loads(p.read_text(encoding="utf-8"))["data"])
    m = _reload(tmp_path, monkeypatch)
    return TestClient(m.app)


@pytest.mark.parametrize("route", ["/", "/a/media", "/a/server", "/server", "/weather",
                                   "/media/movies", "/media/diary", "/media/discover"])
def test_pages_render_in_the_shell_with_sample_snapshots(sample_client, route):
    with sample_client as c:
        r = c.get(route)
    assert r.status_code == 200
    html = r.text
    for cls in ('class="topbar"', 'class="tabbar"', 'class="pagehead"'):
        assert html.count(cls) == 1, cls
    assert 'class="rail"' not in html


# hub greeting on a pinned morning / afternoon / evening clock; it leads the header's sub-line
@pytest.mark.parametrize("hour, minute, part", [(8, 30, "morning"), (13, 5, "afternoon"), (19, 45, "evening")])
def test_hub_greeting_follows_the_home_clock(main, monkeypatch, hour, minute, part):
    monkeypatch.setattr(main.shell, "_now_home", lambda: datetime(2026, 10, 6, hour, minute, tzinfo=MEL))
    with TestClient(main.app) as c:
        body = htmlmod.unescape(c.get("/").text.split("<main", 1)[1])
    assert "<h1>Hub</h1>" in body
    # no Access header in tests = not signed in, so no name (2026-10-06; named form in test_identity.py)
    assert (f'<p class="pagehead-sub">Good {part}. Here\'s what\'s happening at home today, Tuesday 6 October.'
            " · Feeds ") in body


def test_home_clock_is_melbourne(main):
    now = main._now_home()
    assert now.utcoffset() == datetime.now(MEL).utcoffset()


def test_area_page_header_names_the_area_and_counts_tiles(main):
    with TestClient(main.app) as c:
        body = c.get("/a/beta").text.split("<main", 1)[1]
    assert '<header class="pagehead">' in body and "<h1>Beta</h1>" in body
    assert '<p class="pagehead-sub">1 tile</p>' in body and 'class="dot"' not in body


def test_hub_main_names_no_area_for_media():
    """Moved from test_media.py (2026-10-09, decision 2): the Media code keys by connector id, never an area name."""
    hub_dir = REPO_ROOT / "hub"   # W3: main.py's Media code moved to these two modules
    text = "".join((hub_dir / f).read_text(encoding="utf-8") for f in ("main.py", "media_home.py", "media_pages.py"))
    assert "JELLYFIN_SNAPSHOT_ID" in text and "MEDIA_STATUS_SNAPSHOT_ID" in text
    assert '"media"' not in text
