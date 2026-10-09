"""WP24 — the real Open-Meteo connector: full WMO table + live fetch shape.

The live HTTP call itself is proven on the NAS (WP24 step 4); here the fetch is
intercepted so the suite stays offline by construction.
"""

import json

import requests

from connectors.stubs import OpenMeteo


def test_every_wmo_code_0_99_maps_to_a_word():
    for code in range(100):
        text = OpenMeteo.condition(code)
        assert isinstance(text, str) and text.strip(), f"code {code} has no text"


def test_documented_codes_keep_their_exact_words():
    assert OpenMeteo.condition(0) == "clear"
    assert OpenMeteo.condition(61) == "light rain"  # pinned by the committed sample
    assert OpenMeteo.condition(95) == "thunderstorms"


def test_fixture_transform_still_composes_the_pinned_summary(snapshots):
    envelope = OpenMeteo().run()
    assert envelope["status"] == "ok"
    assert envelope["data"]["summary"] == "18.3 °C · light rain"
    assert envelope["data"]["today_min_c"] <= envelope["data"]["today_max_c"]


def test_live_fetch_builds_the_agreed_request(monkeypatch, snapshots):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("WEATHER_LAT", "-37.84")
    monkeypatch.setenv("WEATHER_LON", "144.88")
    monkeypatch.setenv("TZ", "Australia/Melbourne")

    fixture_raw = json.loads(
        (OpenMeteo().fixture_dir / "raw.json").read_text(encoding="utf-8")
    )
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return fixture_raw

    def fake_get(url, params=None, timeout=None):
        seen.update(url=url, params=params, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)

    envelope = OpenMeteo().run()
    assert envelope["status"] == "ok"
    assert envelope["data"]["summary"] == "18.3 °C · light rain"
    assert seen["url"] == OpenMeteo.FORECAST_URL
    assert seen["timeout"] == 10
    assert seen["params"]["latitude"] == "-37.84"
    assert seen["params"]["longitude"] == "144.88"
    assert seen["params"]["current"] == "temperature_2m,weather_code"
    # Weather upgrade (2026-10-06, approved by B.): the one GET also carries the next
    # hours and 7 days. Was daily = the first three fields and forecast_days == 1.
    assert (
        seen["params"]["daily"]
        == "temperature_2m_min,temperature_2m_max,precipitation_probability_max,"
        "weather_code,sunrise,sunset,uv_index_max,wind_speed_10m_max"
    )
    assert (
        seen["params"]["hourly"]
        == "temperature_2m,precipitation_probability,apparent_temperature"
    )
    assert seen["params"]["forecast_days"] == 7
    assert seen["params"]["timezone"] == "Australia/Melbourne"
    assert len(envelope["data"]["hourly"]) == 24 and len(envelope["data"]["days"]) == 7


def test_live_mode_without_coordinates_fails_naming_the_variable(monkeypatch, snapshots):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.delenv("WEATHER_LAT", raising=False)
    monkeypatch.delenv("WEATHER_LON", raising=False)
    envelope = OpenMeteo().run()
    assert envelope["status"] == "error"
    assert "WEATHER_LAT" in envelope["error"]


# ---- Weather upgrade (2026-10-06): hourly + 7-day fields off the committed fixture ----


def test_fixture_summary_and_secondary_are_unchanged_by_the_upgrade(snapshots):
    data = OpenMeteo().run()["data"]
    assert data["summary"] == "18.3 °C · light rain"
    assert data["secondary"] == "12.7–24.1 °C · 55% rain"


def test_transform_emits_24_hours_from_the_current_hour(snapshots):
    hourly = OpenMeteo().run()["data"]["hourly"]
    assert len(hourly) == 24
    assert hourly[0] == {"time": "2026-01-01T08:00", "temp_c": 18.3,
                         "rain_prob_pct": 55, "feels_c": 16.4}
    assert hourly[-1]["time"] == "2026-01-02T07:00"   # clipped, not the whole 7 x 24
    assert all(set(h) == {"time", "temp_c", "rain_prob_pct", "feels_c"} for h in hourly)


def test_transform_emits_7_days_with_words(snapshots):
    days = OpenMeteo().run()["data"]["days"]
    assert [d["date"] for d in days] == [f"2026-01-0{i}" for i in range(1, 8)]
    assert days[0] == {
        "date": "2026-01-01", "min_c": 12.7, "max_c": 24.1, "rain_prob_pct": 55,
        "condition_text": "light rain", "sunrise": "05:57", "sunset": "20:44",
        "uv_max": 9.1, "wind_max_kmh": 24.5,
    }
    assert days[2]["condition_text"] == "clear"
    assert all(d["condition_text"].strip() for d in days)


def test_transform_tolerates_nulls_and_a_short_payload():
    raw = {
        "current": {"time": "2026-01-01T22:15", "temperature_2m": 10, "weather_code": 3},
        "daily": {
            "time": ["2026-01-01", "2026-01-02"],
            "temperature_2m_min": [8, None], "temperature_2m_max": [14, 15],
            "precipitation_probability_max": [0, None], "weather_code": [3, None],
        },
        "hourly": {
            "time": ["2026-01-01T21:00", "2026-01-01T22:00", "2026-01-01T23:00"],
            "temperature_2m": [11, None, 9], "precipitation_probability": [0, 5, None],
        },
    }
    data = OpenMeteo().transform(raw)
    assert data["summary"] == "10 °C · overcast"
    assert [h["time"] for h in data["hourly"]] == ["2026-01-01T22:00", "2026-01-01T23:00"]
    assert data["hourly"][0] == {"time": "2026-01-01T22:00", "temp_c": None,
                                 "rain_prob_pct": 5, "feels_c": None}
    assert data["days"][1]["min_c"] is None and data["days"][1]["condition_text"] == "unknown"
    assert data["days"][0]["sunrise"] is None


def test_transform_without_hourly_or_extra_daily_still_composes():
    raw = {
        "current": {"time": "2026-01-01T08:00", "temperature_2m": 18.3, "weather_code": 61},
        "daily": {"time": ["2026-01-01"], "temperature_2m_min": [12.7],
                  "temperature_2m_max": [24.1], "precipitation_probability_max": [55]},
    }
    data = OpenMeteo().transform(raw)
    assert data["summary"] == "18.3 °C · light rain"
    assert data["secondary"] == "12.7–24.1 °C · 55% rain"
    assert data["hourly"] == [] and len(data["days"]) == 1


# ---- 2026-10-09 review (C-06, C-07): no coordinates in errors; blank TZ means auto ----


def _live(monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("WEATHER_LAT", "-37.84")
    monkeypatch.setenv("WEATHER_LON", "144.88")


def test_a_failed_forecast_reports_status_only_never_the_url(monkeypatch, snapshots, caplog):
    _live(monkeypatch)
    url = f"{OpenMeteo.FORECAST_URL}?latitude=-37.84&longitude=144.88"

    def fake_get(*a, **k):
        raise requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")

    monkeypatch.setattr(requests, "get", fake_get)
    with caplog.at_level("WARNING", logger="connectors"):
        envelope = OpenMeteo().run()
    assert envelope["status"] == "error"
    assert envelope["error"] == "RuntimeError: Open-Meteo forecast failed (connection refused)"
    on_disk = (snapshots / "open_meteo.json").read_text(encoding="utf-8")
    for text in (envelope["error"], on_disk, caplog.text):
        assert "-37.84" not in text and "latitude" not in text and "open-meteo.com" not in text


def test_an_http_error_reports_its_status(monkeypatch, snapshots):
    _live(monkeypatch)

    class Bad:
        status_code = 400

        def raise_for_status(self):
            raise requests.HTTPError("400 Client Error for url: https://api.open-meteo.com/?latitude=-37.84",
                                     response=self)

    monkeypatch.setattr(requests, "get", lambda *a, **k: Bad())
    assert OpenMeteo().run()["error"] == "RuntimeError: Open-Meteo forecast failed (HTTP 400)"


def test_a_blank_tz_asks_open_meteo_for_auto(monkeypatch, snapshots):
    _live(monkeypatch)
    monkeypatch.setenv("TZ", "")
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        raise requests.Timeout()

    monkeypatch.setattr(requests, "get", fake_get)
    OpenMeteo().run()
    assert seen["timezone"] == "auto"
