"""Hub weather glimpse + /weather detail page (2026-09-11 — supersedes D18).

The glimpse reuses the registry tile that reads the open_meteo snapshot, so
states/staleness stay single-sourced; /weather renders the same snapshot's
today-only fields. The condition WORD always renders beside the glyph —
colour/icon is never the only encoding.
"""
import html as htmllib
import importlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.hub.helpers import make_area, write_envelope, write_registry

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
        # WP-T2 (2026-10-19): the Weather tile left the hub row; the full-width glimpse carries the figures and links on
        assert 'href="/weather"' in html and 'class="panel tile dup" href="/weather"' not in html
        assert "9.7&nbsp;°C" in html and "partly cloudy" in html and "8.0&nbsp;°C" in html and "15.1&nbsp;°C" in html and "20%" in html
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
        assert "9.7 °C · partly cloudy" in html and "Stale · 6h ago" in html


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
        assert "Updated 30m ago" in html
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


# ---- Weather upgrade (2026-10-06): hero extras, 24-hour SVG chart, 7-day strip ----

SAMPLE_WX = json.loads(
    (Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "open_meteo.json")
    .read_text(encoding="utf-8")
)["data"]


def _weather_html(app_factory, data):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=5, data=data)
    with build(snaps) as client:
        r = client.get("/weather")
        assert r.status_code == 200
        return r.text


def test_upgraded_hero_renders_feels_wind_uv_and_sun_times_as_text(app_factory):
    html = _weather_html(app_factory, SAMPLE_WX)
    assert "18.3 °C" in html and "light rain" in html          # word beside the glyph
    assert "Feels like 16.4 °C" in html
    assert "24.5 km/h" in html
    assert "9.1" in html and "very high" in html               # UV number AND its word
    assert "05:57 · 20:44" in html


def test_24_hour_chart_is_inline_svg_with_text_values(app_factory):
    html = _weather_html(app_factory, SAMPLE_WX)
    assert '<svg class="wxchart"' in html and "<polyline" in html
    assert "<script" not in html.split('<svg class="wxchart"')[1].split("</svg>")[0]
    assert ">18.3°</text>" in html and ">55%</text>" in html    # labels on the chart itself
    assert "08:00 · 18.3 °C" in html                            # per-point <title>
    # the hour list carries all 24 values in words, so the chart is never the only encoding
    hours = html.split('class="listbox wxhours"')[1].split("</ol>")[0]
    assert hours.count('<li class="row">') == 24
    assert '<div class="row-title">08:00</div>' in hours and "55% rain" in hours and "18.3 °C" in hours
    assert '<div class="row-title">07:00</div>' in hours


def test_7_day_strip_has_glyph_word_range_and_rain(app_factory):
    html = _weather_html(app_factory, SAMPLE_WX)
    week = html.split('class="listbox wxdays"')[1].split("</ol>")[0]
    assert week.count('<li class="row">') == 7
    assert '<div class="row-title">Today</div>' in week and '<div class="row-title">Fri 2</div>' in week   # 2026-01-02 is a Friday
    assert "12.7–24.1 °C" in week and "55% rain" in week
    assert "partly cloudy" in week and "clear" in week
    assert week.count('<span class="glyph">') == 7


def test_old_envelope_without_new_fields_renders_without_the_new_panels(app_factory):
    html = _weather_html(app_factory, WX_DATA)                  # pre-upgrade shape
    assert "9.7" in html and "partly cloudy" in html and "20%" in html
    assert '<svg class="wxchart"' not in html and 'wxdays' not in html
    assert "Feels like" not in html and "km/h" not in html
    assert "arrive with the next refresh" in html


def test_malformed_forecast_rows_never_crash(app_factory):
    data = {**WX_DATA, "hourly": [None, {"time": "2026-01-01T08:00"}, "x"],
            "days": [{"date": "not-a-date"}, 7]}
    html = _weather_html(app_factory, data)
    assert "9.7" in html
    assert '<svg class="wxchart"' not in html                   # no temperatures => no chart
    assert '<div class="row-title">Today</div>' in html and "unknown" not in html.lower()
    week = html.split('class="listbox wxdays"')[1].split("</ol>")[0]
    assert '<div class="row-meta">—' in week                     # a missing condition word is "—" (guide §9)


def test_glimpse_is_unchanged_by_the_forecast_fields(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=12, data=SAMPLE_WX)
    with build(snaps) as client:
        html = client.get("/").text
        assert 'href="/weather"' in html and 'class="panel tile dup" href="/weather"' not in html   # WP-T2: no Weather tile
        assert "18.3&nbsp;°C" in html and "light rain" in html and "12.7&nbsp;°C" in html and "24.1&nbsp;°C" in html and "55%" in html
        assert '<svg class="wxchart"' not in html and 'wxdays' not in html


def test_zero_degrees_renders_as_0_not_a_dash(app_factory):
    """D-52: 0 °C is a temperature, not a missing value — the hour rows and the 7-day range print "0"."""
    data = {**WX_DATA, "hourly": [{"time": "2026-07-01T06:00", "temp_c": 0, "feels_c": -3, "rain_prob_pct": 0}],
            "days": [{"date": "2026-07-01", "condition_text": "frost", "min_c": 0, "max_c": 0.0, "rain_prob_pct": 0}]}
    html = _weather_html(app_factory, data)
    hours = html.split('class="listbox wxhours"')[1].split("</ol>")[0]
    week = html.split('class="listbox wxdays"')[1].split("</ol>")[0]
    assert '<span class="row-side">0 °C</span>' in hours
    assert '<span class="row-side">0–0 °C</span>' in week


def test_place_name_comes_from_weather_place(app_factory, monkeypatch):
    """H-36 / D-18: the labels follow WEATHER_PLACE (default Newport VIC), like the coordinates follow WEATHER_LAT/LON."""
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=12, data=SAMPLE_WX)
    with build(snaps) as client:
        assert "Newport VIC" in client.get("/").text and "Newport VIC" in client.get("/weather").text
        monkeypatch.setenv("WEATHER_PLACE", "Castlemaine VIC")
        hub, page = client.get("/").text, client.get("/weather").text
    assert "Newport VIC" not in hub + page
    # E3 (U10, 2026-10-13): the "Today" and "Rain radar" labels no longer repeat the place (4 -> 2: the page head's
    # sub-line and the Windy caption)
    # WP-T2 (2026-10-19): the hub's Weather tile is gone, so the place shows once there (the glimpse heading)
    assert hub.count("Castlemaine VIC") >= 1 and page.count("Castlemaine VIC") == 2


# ---- Windy radar embed (RADAR SUPERSESSION, 2026-10-07; moved from test_weather_radar.py 2026-10-09 when the
# parked BOM radar was removed, decision 5) ----

def _windy_page(app_factory, data):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=5, data=data)
    with build(snaps) as client:
        r = client.get("/weather")
        assert r.status_code == 200
        return r.text


def _windy_src(page):
    panel = page.split('class="sec wxradar"')[1].split("</section>")[0]
    m = re.search(r'<iframe class="wxwindy" src="([^"]+)"', panel)
    assert m, "Windy iframe missing"
    return panel, htmllib.unescape(m.group(1))


@pytest.fixture()
def coords(monkeypatch):
    monkeypatch.setenv("WEATHER_LAT", "-37.84")
    monkeypatch.setenv("WEATHER_LON", "144.88")


def test_radar_panel_is_a_windy_embed_with_the_home_coords(app_factory, coords):
    page = _windy_page(app_factory, WX_DATA)
    panel, src = _windy_src(page)
    assert src.startswith("https://embed.windy.com/embed2.html?")
    for part in ("lat=-37.84", "lon=144.88", "overlay=radar", "zoom=8", "metricTemp=%C2%B0C",
                 "metricWind=km%2Fh", "detectRotation=false"):
        assert part in src.split("?", 1)[1].split("&"), part
    assert 'title="Interactive rain radar map' in panel and 'loading="lazy"' in panel
    assert "Interactive radar · windy.com · needs internet" in panel
    # no BOM layer stack on the page, and the page itself runs no script for the radar
    assert "wxrframe" not in page and "/weather/radar/" not in page and "<script" not in panel


def test_windy_coords_follow_the_weather_env(app_factory, monkeypatch):
    monkeypatch.setenv("WEATHER_LAT", "-33.87")
    monkeypatch.setenv("WEATHER_LON", "151.21")
    _, src = _windy_src(_windy_page(app_factory, WX_DATA))
    assert "lat=-33.87&lon=151.21&detailLat=-33.87&detailLon=151.21" in src


@pytest.mark.parametrize("lat,lon", [(None, None), ("x", "144.88"), ("-137", "144.88")])
def test_windy_falls_back_to_newport_when_env_missing_or_bad(app_factory, monkeypatch, lat, lon):
    for k, v in (("WEATHER_LAT", lat), ("WEATHER_LON", lon)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    _, src = _windy_src(_windy_page(app_factory, WX_DATA))
    assert "lat=-37.84&lon=144.88" in src


def test_windy_panel_renders_when_the_weather_snapshot_is_absent(app_factory, coords):
    build, tmp_path = app_factory
    with build(tmp_path / "never-created") as client:
        r = client.get("/weather")
    assert r.status_code == 200 and "Not connected" in r.text
    _, src = _windy_src(r.text)
    assert "lat=-37.84" in src


def test_windy_iframe_css_keeps_the_square_capped_slot():
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    rule = css.split(".wxwindy {")[1].split("}")[0]
    assert "aspect-ratio: 1" in rule and "min(100%, 78vh)" in rule and "border: 0" in rule
