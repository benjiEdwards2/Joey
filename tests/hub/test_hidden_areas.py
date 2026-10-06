"""Hidden (parked) areas + the three-card hub row (B., 2026-10-06)."""
import importlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.test_registry import AREAS_YAML, make_area, write_registry
from tests.hub.test_store import write_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "config" / "sample_snapshots"
PARKED = {"kitchen", "money", "desk", "house", "car"}


def test_hidden_defaults_false_and_is_accepted(tmp_path):
    reg = load_registry(write_registry(tmp_path, make_area("a"), {**make_area("b"), "hidden": True}))
    assert [(a.id, a.hidden) for a in reg.areas] == [("a", False), ("b", True)]
    assert [a.id for a in reg.visible_areas] == ["a"]


def test_hidden_area_is_still_validated(tmp_path):
    bad = {**make_area("b"), "hidden": True, "accent": "red"}
    with pytest.raises(ValueError, match="accent"):
        load_registry(write_registry(tmp_path, make_area("a"), bad))


def test_real_registry_parks_exactly_five():
    reg = load_registry(AREAS_YAML)
    assert {a.id for a in reg.areas if a.hidden} == PARKED
    assert [a.id for a in reg.visible_areas] == ["calendar", "media", "server"]  # server added 2026-10-06


def _client(monkeypatch, tmp_path, registry=None, drop=()):
    if registry:
        monkeypatch.setenv("AREAS_PATH", str(registry))
    else:
        monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    for p in SAMPLES.glob("*.json"):
        if not p.stem.startswith("_") and p.stem not in drop:
            write_envelope(snaps, p.stem, age_minutes=1, data=json.loads(p.read_text(encoding="utf-8"))["data"])
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    import hub.main
    importlib.reload(hub.main)
    return TestClient(hub.main.app)


def test_top_bar_and_phone_bar_skip_hidden_areas(tmp_path, monkeypatch):
    reg = write_registry(tmp_path, {**make_area("one"), "hidden": True}, make_area("two"),
                         make_area("three"), make_area("four"), make_area("five"))
    with _client(monkeypatch, tmp_path, reg) as c:
        html = c.get("/").text
    top = html.split('aria-label="Sections"', 1)[1].split("</nav>", 1)[0]
    assert "/a/one" not in top and "/a/two" in top
    tabs = html.split('aria-label="Sections (phone)"', 1)[1]
    bar, sheet = tabs.split('<div class="sheet">', 1)
    assert "/a/one" not in tabs
    # Hub, Weather, two, three in the bar; four and five in the More sheet (six sections > five slots)
    assert all(f"/a/{i}" in bar for i in ("two", "three")) and "/a/four" in sheet and "/a/five" in sheet


def test_parked_page_still_serves(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as c:
        r = c.get("/a/money")
    assert r.status_code == 200 and "<h1>Money</h1>" in r.text


def test_hub_row_is_media_weather_calendar_and_spans_calendar(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as c:
        body = c.get("/").text.split("<main", 1)[1]
    row = re.search(r'<section class="tiles[^"]*".*?</section>', body, re.S).group(0)
    # Server area (2026-10-06) makes it four cards: a full row, so no `few` / span2 any more
    assert re.match(r'<section class="tiles"', row)
    names = re.findall(r'<div class="microlabel">([^<]+)</div>', row)
    assert names == ["Media", "Calendar", "Weather", "Server"]  # Weather sits before the last card
    assert re.search(r'<a class="panel tile" href="/a/server"', row)
    assert row.count("span2") == 0
    for name in ("Food", "Money", "Desk", "House", "Car"):
        assert f'<div class="microlabel">{name}</div>' not in body


def test_calendar_page_has_no_weather_kpi_tile_but_keeps_the_band(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as c:
        body = c.get("/a/calendar").text
    kpis = re.search(r'<section class="tiles areatiles".*?</section>', body, re.S).group(0)
    assert "light rain" not in kpis and "Weather" not in kpis
    assert 'class="sec wxglimpse"' in body and "light rain" not in kpis


def test_css_has_span_rule_and_no_literal_colour():
    css = (REPO_ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert re.search(r"\.tiles\.few\s*>\s*\.span2\s*\{\s*grid-column:\s*span 2", css)
    assert re.search(r"\.tiles\.few\s*>\s*\.span2\s*\{\s*grid-column:\s*1 / -1", css)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css.split("/* ---- Pages (restyle Phase 4", 1)[1])
