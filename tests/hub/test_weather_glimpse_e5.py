"""E5 (W1 + BACKLOG "7-day forecast on the weather glimpse", 2026-10-13): rain timing in words from the open_meteo
hourly data, the glimpse's one extra 7-day row, and the 375 px fix (a value never breaks between number and unit)."""
import importlib
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.weather import RAIN_LIKELY_PCT, rain_words, week_strip
from tests.hub.helpers import make_area, write_envelope, write_registry

NOW = datetime(2026, 10, 13, 9, 20)
CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def hours(chances, start="2026-10-13T09:00"):
    """Hourly rows from `start`, one per chance (None = a missing value)."""
    base = datetime.fromisoformat(start)
    return [{"time": f"{base + timedelta(hours=i):%Y-%m-%dT%H:%M}", "temp_c": 15.0, "feels_c": 14.0,
             "rain_prob_pct": c} for i, c in enumerate(chances)]


def test_first_wet_hour_and_the_peak_chance():
    h = hours([10, 20, 30, 70, 40])           # 09:00 … 13:00
    assert rain_words(h, NOW) == "Rain likely from 11:00 · 70%"
    assert rain_words(h, NOW, short=True) == "Rain from 11:00"


def test_dry_when_every_hour_left_today_is_under_the_threshold():
    h = hours([RAIN_LIKELY_PCT - 1] * 15)    # to 23:00
    assert rain_words(h, NOW) == "Dry until tomorrow"
    assert rain_words(h, NOW, short=True) == "Dry today"


def test_hours_already_gone_and_tomorrows_hours_do_not_count():
    h = hours([90, 10, 10], start="2026-10-13T08:00")      # 08:00 has gone by 09:20
    assert rain_words(h, NOW, short=True) == "Dry today"
    late = datetime(2026, 10, 13, 22, 10)
    h = hours([10, 10, 95, 95], start="2026-10-13T22:00")   # 00:00 and 01:00 are tomorrow
    assert rain_words(h, late, short=True) == "Dry today"


def test_no_hourly_data_drops_the_words():
    assert rain_words(None, NOW) is None and rain_words([], NOW) is None
    assert rain_words(hours([None, None]), NOW) is None                       # no chance in any hour
    assert rain_words(hours([80], start="2026-10-12T09:00"), NOW) is None    # yesterday's snapshot
    assert rain_words([{"time": "junk", "rain_prob_pct": 80}], NOW) is None


def test_week_strip_is_letter_glyph_word_and_max():
    days = [{"date": "2026-10-13", "max_c": 24.1, "condition_text": "light rain"},
            {"date": "2026-10-14", "max_c": 18.0, "condition_text": "clear sky"},
            {"date": "junk", "max_c": 1}]
    assert week_strip({"days": days}) == [
        {"letter": "T", "name": "Today", "glyph": "wx-rain", "word": "light rain", "max": "24.1"},
        {"letter": "W", "name": "Wednesday", "glyph": "wx-sun", "word": "clear sky", "max": "18"}]
    assert week_strip({}) == []


@pytest.fixture()
def hub_html(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(
        tmp_path, make_area("alpha", "weather-t", snapshot="open_meteo", stale_after_minutes=180))))

    def get(data):
        snaps = tmp_path / "snaps"
        write_envelope(snaps, "open_meteo", age_minutes=12, data=data)
        monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
        import hub.main
        importlib.reload(hub.main)
        with TestClient(hub.main.app) as client:
            return client.get("/").text
    return get


BASE = {"summary": "18.3 °C · light rain", "now_c": 18.3, "condition_text": "light rain",
        "today_min_c": 12.7, "today_max_c": 24.1, "rain_prob_pct": 70}


def _glimpse(html):
    return html.split('class="sec wxglimpse"')[1].split("</section>")[0]


def test_glimpse_shows_the_rain_words_and_seven_days(hub_html):
    from hub.ids import home_now
    now = home_now()
    day = now.strftime("%Y-%m-%d")
    hourly = [{"time": f"{day}T{h:02d}:00", "temp_c": 15, "feels_c": 14, "rain_prob_pct": 80}
              for h in range(now.hour, 24)]
    days = [{"date": f"2026-10-{13 + i}", "min_c": 10, "max_c": 20 + i, "rain_prob_pct": 10,
             "condition_text": "clear sky", "sunrise": "06:00", "sunset": "19:00", "uv_max": 5, "wind_max_kmh": 10}
            for i in range(7)]
    g = _glimpse(hub_html({**BASE, "hourly": hourly, "days": days}))
    assert f'<span class="wxrain">Rain likely from {now.hour:02d}:00 · 80%</span>' in g
    assert g.count("<li>") == 7 and '<ol class="wxstrip" aria-label="Next 7 days">' in g
    assert '<span class="vh">Today · clear sky · 20 °C</span>' in g and ">26°<" in g   # word + number, never glyph alone


def test_glimpse_without_hourly_or_days_has_no_rain_words_and_no_row(hub_html):
    g = _glimpse(hub_html(BASE))
    assert "wxrain" not in g and "wxstrip" not in g and "Updated 12m ago" in g


def test_no_value_can_break_between_number_and_unit(hub_html):
    """Eyes-on at 375 px (2026-10-13): '18.3 / °C' wrapped. Each value is number + NBSP + unit, kept on one line."""
    g = _glimpse(hub_html(BASE))
    for v in ("18.3", "12.7", "24.1"):
        assert f"{v}&nbsp;°C" in g and f"{v} °C" not in g
    assert re.search(r"\.wxglimpse \.stat-number \{ white-space: nowrap; \}", CSS)
    phone = CSS.split("@media (max-width: 399px) {", 1)[1].split("}\n}", 1)[0]
    assert ".wxglimpse .stat-number { font-size: 18px; }" in phone
    assert CSS.index("/* ---- E5 features (2026-10-13) ---- */") < CSS.index(".wxstrip {")
