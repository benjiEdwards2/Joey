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
    assert (
        seen["params"]["daily"]
        == "temperature_2m_min,temperature_2m_max,precipitation_probability_max"
    )
    assert seen["params"]["forecast_days"] == 1
    assert seen["params"]["timezone"] == "Australia/Melbourne"


def test_live_mode_without_coordinates_fails_naming_the_variable(monkeypatch, snapshots):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.delenv("WEATHER_LAT", raising=False)
    monkeypatch.delenv("WEATHER_LON", raising=False)
    envelope = OpenMeteo().run()
    assert envelope["status"] == "error"
    assert "WEATHER_LAT" in envelope["error"]
