"""Apex shell (2026-10-06): rail with labelled areas, light+dark theme toggle with a pre-paint
script, a tokens-only stylesheet, and the hub greeting computed on the home clock."""
import html as htmlmod
import importlib
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.hub.test_media_shelves import JELLY, ARR, shelf_area
from tests.hub.test_registry import make_area, write_registry
from tests.hub.test_store import write_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS = (REPO_ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
MEL = ZoneInfo("Australia/Melbourne")


@pytest.fixture()
def main(tmp_path, monkeypatch):
    fixture = write_registry(tmp_path, shelf_area(), make_area("beta", "b-t"), make_area("gamma", "g-t"))
    monkeypatch.setenv("AREAS_PATH", str(fixture))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    for cid, data in (("jellyfin", JELLY), ("arr", ARR)):
        write_envelope(tmp_path / "snaps", cid, age_minutes=1, data=data)
    import hub.main
    importlib.reload(hub.main)
    return hub.main


def rail_of(html):
    return re.search(r'<aside class="rail".*?</aside>', html, re.S).group(0)


# (a) the rail lists every registry area by name, linked to /a/<id>
def test_rail_lists_every_area_by_name(main):
    with TestClient(main.app) as c:
        html = c.get("/").text
    rail = rail_of(html)
    for a in main.registry.areas:
        assert re.search(rf'<a href="/a/{a.id}"[^>]*>.*?</span>{re.escape(a.name)}</a>', rail, re.S), a.id
    assert '<a href="/" class="on" aria-current="page">' in rail and 'href="/weather"' in rail
    assert ">Home<" in rail and ">Areas<" in rail and "Services" not in rail
    # signed-in user (2026-10-06): brand reads just "Joey"; footer shows the user (none here: no Access header)
    assert "joeyhome.net" not in rail and "<b>Not signed in</b>" in rail and "Local preview" in rail


def test_rail_marks_the_active_area(main):
    with TestClient(main.app) as c:
        rail = rail_of(c.get("/a/beta").text)
    assert re.search(r'<a href="/a/beta"[^>]*class="on" aria-current="page"', rail)
    assert rail.count('class="on"') == 1


# (b) theme toggle + pre-paint script on hub, an area page and a media page
@pytest.mark.parametrize("route", ["/", "/a/beta", "/media/diary"])
def test_theme_toggle_and_prepaint_script(main, route):
    with TestClient(main.app) as c:
        html = c.get(route).text
    head = html.split("</head>", 1)[0]
    assert "localStorage.getItem('joey-theme')" in head and "setAttribute('data-theme'" in head
    assert head.index("joey-theme") < head.index("control-surface.css")   # applied before first paint
    assert re.search(r'<button class="iconbtn themetoggle" type="button" data-theme-toggle', html)
    assert html.count('name="theme-color"') == 2 and 'media="(prefers-color-scheme: dark)"' in head
    assert "fonts.googleapis.com/css2?family=Geist" in head


def _block(selector_regex):
    m = re.search(selector_regex + r"\s*\{(.*?)\}", CSS, re.S)
    assert m, selector_regex
    return m.group(1)


def _props(body):
    return set(re.findall(r"(--[\w-]+)\s*:", body))


def _token_blocks():
    light = _block(r"(?m)^:root")
    dark_media = _block(r':root:not\(\[data-theme="light"\]\)')
    dark_attr = _block(r':root\[data-theme="dark"\]')
    return light, dark_media, dark_attr


# (c) tokens on :root, redefined in both dark blocks — same names, both directions
def test_tokens_defined_on_root_and_redefined_in_both_dark_blocks():
    light, dark_media, dark_attr = _token_blocks()
    assert "@media (prefers-color-scheme: dark)" in CSS
    lp, mp, ap = _props(light), _props(dark_media), _props(dark_attr)
    assert len(lp) > 20
    assert lp == ap, (lp ^ ap)
    assert lp == mp, (lp ^ mp)
    assert "color-scheme: dark" in dark_media and "color-scheme: dark" in dark_attr


# (d) no literal hex colour anywhere outside the three token blocks
def test_no_hex_colour_outside_token_blocks():
    rest = CSS
    for body in _token_blocks():
        rest = rest.replace(body, "")
    rest = re.sub(r"/\*.*?\*/", "", rest, flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", rest)
    assert not re.findall(r"\brgba?\(", rest)


# (e) hub greeting on a pinned morning / afternoon / evening clock
@pytest.mark.parametrize("hour, minute, part", [(8, 30, "morning"), (13, 5, "afternoon"), (19, 45, "evening")])
def test_hub_greeting_follows_the_home_clock(main, monkeypatch, hour, minute, part):
    monkeypatch.setattr(main, "_now_home", lambda: datetime(2026, 10, 6, hour, minute, tzinfo=MEL))
    with TestClient(main.app) as c:
        body = htmlmod.unescape(c.get("/").text.split("<main", 1)[1])
    assert "<h1>Hub</h1>" in body
    # no Access header in tests = not signed in, so no name (2026-10-06; named form in test_identity.py)
    assert (f"Good {part}. Here's what's happening at home today, Tuesday 6 October.") in body


def test_home_clock_is_melbourne(main):
    now = main._now_home()
    assert now.utcoffset() == datetime.now(MEL).utcoffset()


def test_area_page_heading_replaces_dot_h2(main):
    with TestClient(main.app) as c:
        body = c.get("/a/beta").text.split("<main", 1)[1]
    assert '<div class="pagehead">' in body and "<h1>Beta</h1>" in body
    assert 'class="dot"' not in body and "1 tile" in body


# rail_section + brand link (B., 2026-10-06)
def _home_main(tmp_path, monkeypatch, *areas):
    fixture = write_registry(tmp_path, *areas)
    monkeypatch.setenv("AREAS_PATH", str(fixture))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    return hub.main


def test_rail_home_section_area_sits_between_hub_and_weather_and_order_is_kept(tmp_path, monkeypatch):
    m = _home_main(tmp_path, monkeypatch, make_area("alpha"), {**make_area("beta"), "rail_section": "home"},
                   make_area("gamma"), {**make_area("delta"), "rail_section": "home"})
    with TestClient(m.app) as c:
        rail = rail_of(c.get("/").text)
    home = re.search(r'<nav class="nav" aria-label="Home">(.*?)</nav>', rail, re.S).group(1)
    areas = re.search(r'<nav class="nav" aria-label="Areas list">(.*?)</nav>', rail, re.S).group(1)
    pos = [home.index(x) for x in ('href="/"', 'href="/a/beta"', 'href="/a/delta"', 'href="/weather"')]
    assert pos == sorted(pos)
    assert 'href="/a/beta"' not in areas and 'href="/a/delta"' not in areas
    assert areas.index('href="/a/alpha"') < areas.index('href="/a/gamma"')


def test_real_registry_media_renders_in_home_nav_not_areas_nav(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        rail = rail_of(c.get("/").text)
    home = re.search(r'<nav class="nav" aria-label="Home">(.*?)</nav>', rail, re.S).group(1)
    areas = re.search(r'<nav class="nav" aria-label="Areas list">(.*?)</nav>', rail, re.S).group(1)
    assert 'href="/a/media"' in home and 'href="/a/media"' not in areas


def test_brand_block_is_one_home_link_with_kangaroo_image(main):
    with TestClient(main.app) as c:
        rail = rail_of(c.get("/").text)
        img = c.get("/static/brand-joey.jpg")
    brand = re.search(r'<a class="brand" href="/" aria-label="Joey home">(.*?)</a>', rail, re.S).group(1)
    assert "/static/brand-joey.jpg?v=" in brand and "<b>Joey</b>" in brand and "joeyhome.net" not in brand  # 2026-10-06: just "Joey"
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8" and len(img.content) > 1000
