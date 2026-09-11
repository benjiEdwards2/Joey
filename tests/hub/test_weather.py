"""Hub weather glimpse + /weather detail page (2026-09-11 — supersedes D18).

The glimpse reuses the registry tile that reads the open_meteo snapshot, so
states/staleness stay single-sourced; /weather renders the same snapshot's
today-only fields. The condition WORD always renders beside the glyph —
colour/icon is never the only encoding.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, write_registry
from tests.hub.test_store import write_envelope

WX_DATA = {
    "summary": "9.7 °C · partly cloudy", "secondary": "8–15 °C · 20% rain",
    "now_c": 9.7, "condition_text": "partly cloudy",
    "today_min_c": 8.0, "today_max_c": 15.1, "rain_prob_pct": 20,
}


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    fixture = write_registry(
        tmp_path,
        make_area("alpha", "weather-t", snapshot="open_meteo", stale_after_minutes=180),
        make_area("beta", "other-t", snapshot="jellyfin", stale_after_minutes=120),
    )
    monkeypatch.setenv("AREAS_PATH", str(fixture))

    def build(snapshot_dir):
        monkeypatch.setenv("SNAPSHOT_DIR", str(snapshot_dir))
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build, tmp_path


def test_glimpse_renders_on_hub_and_links_to_detail(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=12, data=WX_DATA)
    with build(snaps) as client:
        html = client.get("/").text
        assert 'class="cardlink wx" href="/weather"' in html
        assert "9.7 °C · partly cloudy" in html and "8–15 °C · 20% rain" in html
        assert '<div class="glyph">' in html          # the requested small image
        assert "12m ago" in html                       # fresh, faint timestamp


def test_glimpse_absent_snapshot_shows_not_connected_no_glyph(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "never-created") as client:
        r = client.get("/")
        assert r.status_code == 200
        html = r.text
        assert 'href="/weather"' in html and "Not connected" in html
        assert '<div class="glyph">' not in html       # no condition => no icon


def test_glimpse_stale_keeps_value_with_badge(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=400, data=WX_DATA)
    with build(snaps) as client:
        html = client.get("/").text
        assert "9.7 °C · partly cloudy" in html and "stale 6h" in html


def test_detail_page_renders_todays_fields(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=30, data=WX_DATA)
    with build(snaps) as client:
        r = client.get("/weather")
        assert r.status_code == 200
        html = r.text
        assert "9.7" in html and "partly cloudy" in html   # word beside the glyph
        assert "8.0" in html and "15.1" in html and "20%" in html
        assert "updated 30m ago" in html
        assert "Open-Meteo" in html


def test_detail_page_absent_snapshot_is_not_connected_not_a_crash(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "never-created") as client:
        r = client.get("/weather")
        assert r.status_code == 200
        assert "Not connected" in r.text


def test_glyph_mapping_first_match_wins():
    import hub.main as m
    assert m.weather_glyph("thunderstorm with hail") == "wx-thunder"
    assert m.weather_glyph("light rain") == "wx-rain"
    assert m.weather_glyph("snow showers") == "wx-snow"   # snow beats shower
    assert m.weather_glyph("freezing drizzle") == "wx-snow"
    assert m.weather_glyph("fog") == "wx-fog"
    assert m.weather_glyph("clear sky") == "wx-sun"
    assert m.weather_glyph("overcast") == "wx-cloud"
    assert m.weather_glyph(None) == "wx-cloud"
