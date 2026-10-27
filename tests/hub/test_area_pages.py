"""Formerly test_apex_areas.py ("Apex" was the 2026-10-06 restyle round's name).
Apex area pages (2026-10-06; restyle Phase 4): non-media areas as a row of summary tiles (one .panel.tile per
registry tile), Calendar with the Next 7 days rows + Weather glimpse, a quiet sentence when nothing is connected,
/weather as a stats strip + panels. Real registry + committed sample snapshots; media pages untouched."""
import importlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.helpers import write_envelope
from tests.hub.test_hub_page import EVENTS, SAMPLE_DATA

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def get(route, drop=(), lan=False):
        data = {**SAMPLE_DATA, "gcal": {**SAMPLE_DATA["gcal"], "events": EVENTS}}
        for cid, d in data.items():
            if cid not in drop:
                write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        # E3 (2026-10-13): `lan=True` asks from a LAN address, so LAN-only Server links show (shell.from_lan)
        with TestClient(hub.main.app, client=("192.168.68.20" if lan else "testclient", 50000)) as client:
            html = client.get(f"{route}?owner_view=both").text
        return hub.main, html.split("<main", 1)[1].split("</main>", 1)[0]

    return get


def non_media(main):
    return [a for a in main.shell.registry.areas if a.layout != "shelves"]


def test_each_area_renders_one_kpi_card_per_tile(site):
    main, _ = site("/")
    for a in non_media(main):
        _, body = site(f"/a/{a.id}", lan=True)   # E3: on the LAN, so the Server page's LAN-only tile shows too
        if a.layout == "server":   # WP-T3 (2026-10-19, S3): the Server page has no tile row; the hub card summarises it
            assert 'class="tiles areatiles' not in body
            continue
        k = re.search(r'<section class="tiles areatiles[^"]*".*?</section>', body, re.S).group(0)   # E3: + srvtiles
        # weather renders on the hub and /weather only (2026-10-08) — never as an area tile
        shown = [t for t in a.tiles if t.snapshot != "open_meteo"]
        assert k.count('panel tile') == len(shown), a.id
        for t in shown:
            assert f'<div class="microlabel">{t.label}</div>' in k, (a.id, t.label)
        assert 'class="grid"' not in body


def test_link_tile_opens_new_tab_and_detail_tile_links_to_route(site):
    _, body = site("/a/calendar")
    assert re.search(r'<a class="panel tile" href="https://calendar.google.com" target="_blank"', body)
    assert "Open ↗" in body


def test_detail_tile_links_to_its_route(tmp_path, monkeypatch):
    import textwrap
    cfg = tmp_path / "areas.yaml"
    cfg.write_text(textwrap.dedent("""
        areas:
          - id: desk
            name: Desk
            icon: desk
            summary_tile: files
            tiles:
              - {id: files, label: NAS files, tier: embed, owner: you, snapshot: nas_stats,
                 stale_after_minutes: 120, detail: /weather, setup_note: x}
    """), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(cfg))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    write_envelope(tmp_path / "snaps", "nas_stats", age_minutes=1, data=SAMPLE_DATA["nas_stats"])
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        html = client.get("/a/desk").text
    assert re.search(r'<a class="panel tile" href="/weather"', html)


def test_plain_tile_is_not_a_link(site):
    _, body = site("/a/house")
    k = re.search(r'<section class="tiles areatiles".*?</section>', body, re.S).group(0)
    assert "<a " not in k and 'class="panel tile"' in k


def test_calendar_has_upcoming_rows_with_owner_words(site):
    _, body = site("/a/calendar")
    assert 'class="row upc"' in body and "uptable" not in body and "uplist" not in body
    for word in ("You", "Her"):
        assert f'<span class="row-side">{word}</span>' in body
    assert '<span class="row-side"></span>' in body and ">Shared<" not in body   # E3 (2026-10-13): no "Shared" word
    assert ">All</a>" not in body.split('class="band a"', 1)[1].split("</section>", 1)[0]   # already on the calendar page
    assert 'class="band a"' in body
    # weather lives on the hub and /weather only (2026-10-08) — no glimpse or tile here
    # (the nav rail's Weather link still renders on every page, so match the card markers)
    assert "wxglimpse" not in body and "Newport VIC" not in body


def test_all_not_connected_area_shows_quiet_sentence(tmp_path, monkeypatch):
    # JY-220 (2026-10-27): the real Money area was the only all-unconnected page; a synthetic area now pins the sentence.
    from tests.hub.helpers import make_area, write_registry
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, make_area("alpha", snapshot="nas_stats", setup_note="Set X."))))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        body = client.get("/a/alpha").text
    assert "Nothing connected yet. Set X." in body


def test_connected_area_has_no_quiet_sentence(site):
    _, body = site("/a/house")
    assert "Nothing connected yet" not in body


def test_weather_page_is_a_stats_strip_and_pages_have_no_literal_hex(site):
    _, body = site("/weather")
    assert re.search(r'<section class="sec wxpage"', body) and 'class="stats wxstats"' in body   # E3: .wxstats (U10)
    assert "Newport VIC" in body and "°C" in body
    for route in ("/weather", "/a/calendar", "/a/house", "/a/desk", "/a/kitchen"):
        assert not HEX.search(site(route)[1]), route


def test_media_area_unchanged(site):
    _, body = site("/a/media")
    sections = re.search(r'<nav class="sectabs sectabs-page".*?</nav>', body, re.S).group(0)
    assert "Movies" in sections and "uptable" not in body and "areatiles" not in body
