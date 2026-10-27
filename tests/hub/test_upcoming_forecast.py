"""JY-160 (2026-10-27, option A, built ahead of B.'s pick): each day group in Next 7 days carries that day's forecast
from the open_meteo snapshot's days[] - glyph, condition word, low-high, rain chance - on the hub and /a/<calendar>.
No new call: the snapshots find_upcoming is already given. Household data: the media front serves neither page."""
import importlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub.main import build_upcoming
from hub.upcoming import attach_forecast
from hub.weather import day_forecasts, forecast_line
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import guest_client, sign_in
from tests.hub.helpers import make_area, write_envelope, write_registry

MEL = timezone(timedelta(hours=11))
NOW = datetime(2026, 1, 5, 8, 0, tzinfo=MEL)     # Mon 05 Jan 2026


def ev(title, start, end, all_day=False, owner="shared"):
    return {"title": title, "start": start, "end": end, "all_day": all_day, "owner": owner}


def day(date, cond="light rain", lo=12.7, hi=24.1, rain=60):
    return {"date": date, "condition_text": cond, "min_c": lo, "max_c": hi, "rain_prob_pct": rain}


# ---- the pure helpers ----

def test_day_forecasts_keyed_by_date_with_the_words_and_numbers():
    got = day_forecasts({"days": [day("2026-01-05"), day("2026-01-06", "clear sky", 15.0, 31.2, 5)]})
    assert set(got) == {"2026-01-05", "2026-01-06"}
    assert got["2026-01-05"] == {"glyph": "wx-rain", "word": "Light rain", "lo": "12.7", "hi": "24.1", "rain": 60}
    assert got["2026-01-06"]["glyph"] == "wx-sun" and got["2026-01-06"]["lo"] == "15"


def test_forecast_line_reads_as_one_short_line():
    f = day_forecasts({"days": [day("2026-01-05", "light rain", 12.0, 24.0, 60)]})["2026-01-05"]
    assert forecast_line(f) == "Light rain · 12–24 °C · rain 60%"


def test_missing_parts_drop_only_themselves():
    only_word = {"glyph": "wx-cloud", "word": "Overcast", "lo": None, "hi": None, "rain": None}
    assert forecast_line(only_word) == "Overcast"
    no_rain = {"glyph": "wx-cloud", "word": "Overcast", "lo": "10", "hi": "20", "rain": None}
    assert forecast_line(no_rain) == "Overcast · 10–20 °C"
    only_hi = {"glyph": "wx-cloud", "word": "Overcast", "lo": None, "hi": "20", "rain": 5}
    assert forecast_line(only_hi) == "Overcast · 20 °C · rain 5%"


def test_malformed_or_absent_weather_gives_nothing_never_a_crash():
    assert day_forecasts({}) == {} and day_forecasts(None) == {}
    junk = {"days": ["x", None, {"date": 5}, {"condition_text": "rain"}, day("not-a-date"),
                     {"date": "2026-01-05"}]}
    assert day_forecasts(junk) == {}    # no date, a bad date, or nothing to say: no entry


def test_bool_numbers_are_not_numbers():
    f = day_forecasts({"days": [{"date": "2026-01-05", "condition_text": "rain", "min_c": True, "max_c": False,
                                 "rain_prob_pct": True}]})["2026-01-05"]
    assert (f["lo"], f["hi"], f["rain"]) == (None, None, None)


def test_attach_forecast_adds_wx_to_the_groups_and_leaves_events_alone():
    events = [ev("A", "2026-01-05T09:00+11:00", "2026-01-05T09:30+11:00"),
              ev("B", "2026-01-07T09:00+11:00", "2026-01-07T09:30+11:00")]
    groups = build_upcoming(events, "both", NOW)
    before = [dict(e) for g in groups for e in g["events"]]
    attach_forecast(groups, {"days": [day("2026-01-05"), day("2026-01-06")]})
    assert groups[0]["wx"].startswith("Light rain")
    assert groups[0]["wx_glyph"] == "wx-rain"
    assert "wx" not in groups[1]                       # Wed 7 Jan: past the snapshot's days, no line
    assert [e for g in groups for e in g["events"]] == before   # criterion 5: event dicts unchanged


# ---- the rendered pages ----

@pytest.fixture()
def app(tmp_path, monkeypatch):
    fixture = write_registry(tmp_path, make_area("alpha", "cal-t", snapshot="gcal", stale_after_minutes=120))
    monkeypatch.setenv("AREAS_PATH", str(fixture))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def build():
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    return build, snaps


def _live_days():
    today = datetime.now().astimezone().date()
    return today, today + timedelta(days=1)


def _events():
    """Today (in progress), tomorrow, and day+3 - the last has no forecast row."""
    now = datetime.now().astimezone()
    today, tomorrow = _live_days()
    far = today + timedelta(days=3)
    t1 = now - timedelta(minutes=30)
    return [ev("Timed today", t1.isoformat(), (t1 + timedelta(hours=1)).isoformat()),
            ev("Away", str(tomorrow), str(tomorrow + timedelta(days=1)), all_day=True),
            ev("Past the forecast", str(far), str(far + timedelta(days=1)), all_day=True)]


def _weather(days):
    return {"summary": "W", "condition_text": "x", "days": days}


def _lines(html):
    return re.findall(r'<div class="upc-wx"[^>]*>(.*?)</div>', html, re.S)


@pytest.mark.parametrize("path", ["/a/alpha", "/"])
def test_each_day_with_a_forecast_row_shows_its_line(app, path):
    build, snaps = app
    today, tomorrow = _live_days()
    write_envelope(snaps, "gcal", age_minutes=5, data={"summary": "S", "events": _events()})
    write_envelope(snaps, "open_meteo", age_minutes=5, data=_weather([
        day(str(today), "light rain", 12.0, 24.0, 60), day(str(tomorrow), "clear sky", 15.0, 31.0, 5)]))
    with build() as client:
        html = client.get(path).text
    lines = [re.sub(r"<[^>]+>|\s+", " ", x).strip() for x in _lines(html)]
    assert len(lines) == 2, lines                       # the third day has no forecast row: no line, no dash
    assert lines[0].endswith("Light rain · 12–24 °C · rain 60%") and lines[0].startswith("Today")
    assert lines[1].endswith("Clear sky · 15–31 °C · rain 5%") and lines[1].startswith("Tomorrow")
    sec = html[html.index('aria-label="Next 7 days"'):]      # the hub's Today line and Calendar card name events too
    assert sec.index("Light rain") < sec.index("Timed today") < sec.index("Clear sky") < sec.index("Away")


def test_no_weather_snapshot_means_no_lines_and_the_page_still_renders(app):
    build, snaps = app
    write_envelope(snaps, "gcal", age_minutes=5, data={"summary": "S", "events": _events()})
    for path in ("/a/alpha", "/"):
        with build() as client:
            r = client.get(path)
        assert r.status_code == 200 and "Timed today" in r.text and "upc-wx" not in r.text


def test_rendering_opens_no_connection(app, monkeypatch):
    """Criterion 2: the line comes from the snapshot, not a live call."""
    import socket

    real_connect = socket.socket.connect

    def no_network(self, address, *a, **k):
        if str(address[0]) not in ("127.0.0.1", "::1", "localhost"):   # the event loop's own loopback pipe is fine
            raise AssertionError("render must not open a connection")
        return real_connect(self, address, *a, **k)
    build, snaps = app
    today, _ = _live_days()
    write_envelope(snaps, "gcal", age_minutes=5, data={"summary": "S", "events": _events()})
    write_envelope(snaps, "open_meteo", age_minutes=5, data=_weather([day(str(today))]))
    with build() as client:
        monkeypatch.setattr(socket.socket, "connect", no_network)
        assert "Light rain" in client.get("/a/alpha").text


# ---- the media front never serves the calendar ----

def test_the_media_front_serves_no_calendar_and_no_forecast(monkeypatch, tmp_path):
    today, tomorrow = _live_days()
    c, fake = guest_client(monkeypatch, tmp_path, {
        "gcal": {"summary": "S", "events": [ev("SENTINEL_CAL_EVENT", str(tomorrow), str(tomorrow + timedelta(days=1)),
                                               all_day=True)]},
        "open_meteo": _weather([day(str(today), "SENTINELWX", 1.0, 2.0, 99),
                                day(str(tomorrow), "SENTINELWX", 1.0, 2.0, 99)])})
    with c:
        sign_in(c, fake, FRIEND_ID)
        seen = {}
        for path in ("/", "/a/calendar", "/a/media", "/weather", "/server"):
            r = c.get(path, follow_redirects=False)
            seen[path] = r.status_code
            assert "SENTINELWX" not in r.text and "SENTINEL_CAL_EVENT" not in r.text and "upc-wx" not in r.text, path
        assert seen["/"] == 303                         # the hub root goes to the guest home, never the hub
        assert seen["/a/calendar"] == 404 and seen["/weather"] == 404
        assert seen["/a/media"] == 200
