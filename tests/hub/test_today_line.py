"""E5 (H1, 2026-10-13): the hub's Today line — one sentence from data the hub already holds, each clause dropped when
its source has nothing to say (never invented). hub/today.py is pure; the hub page puts it after E3's date."""
import importlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hub.shell import home_now
from hub.today import short_title, today_line
from tests.hub.helpers import write_envelope

MEL = timezone(timedelta(hours=11))
NOW = datetime(2026, 10, 13, 9, 20, tzinfo=MEL)
TODAY = NOW.date()


def snap(data):
    """A connected snapshot stand-in (store.connected reads .status and .data)."""
    return SimpleNamespace(status="ok", data=data, age_minutes=1)


def wx(chances=None, state="fresh"):
    hourly = None if chances is None else [
        {"time": f"2026-10-13T{9 + i:02d}:00", "temp_c": 15, "feels_c": 14, "rain_prob_pct": c}
        for i, c in enumerate(chances)]
    return {"st": {"state": state}, "data": {"hourly": hourly} if hourly is not None else {}}


def up(*events, day=TODAY, state="fresh"):
    groups = [{"day": day, "label": "Today", "events": list(events)}] if events else []
    return {"st": {"state": state}, "groups": groups}


def ev(title, start="09:30", **extra):
    return {"title": title, "start_text": start, "time_text": start, "owner": "shared", **extra}


def arrived(title, hours_ago):
    return {"title": title, "kind": "episode", "when": "", "at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def line(snaps=None, upcoming=None, weather=None, server=None):
    return today_line(snaps or {}, upcoming, weather, server, "both", NOW)


# ---- each clause ----

def test_rain_clause_from_the_hourly_data():
    assert line(weather=wx([10, 20, 80])) == "Rain from 11:00"
    assert line(weather=wx([10, 20, 29])) == "Dry today"


def test_weather_without_hourly_data_or_not_connected_says_nothing():
    assert line(weather=wx(None)) is None
    assert line(weather=wx([90], state="off")) is None


def test_events_clause_counts_today_and_names_the_first():
    assert line(upcoming=up(ev("Dentist"), ev("Gym", "18:00"))) == "2 events · first 9:30 Dentist"
    assert line(upcoming=up(ev("Dentist", "10:05"))) == "1 event · 10:05 Dentist"
    assert line(upcoming=up(ev("Bins out", "All day"), ev("Gym"))) == "2 events · first Bins out all day"


def test_nothing_on_today_only_when_the_calendar_is_connected():
    assert line(upcoming=up()) == "Nothing on today"
    assert line(upcoming=up(ev("Later"), day=TODAY + timedelta(days=1))) == "Nothing on today"
    assert line(upcoming=up(ev("Dentist"), state="off")) is None
    assert line(upcoming=None) is None


def test_media_release_rows_do_not_count_as_events():
    assert line(upcoming=up(ev("Severance · S02E04", "New episode", release=True))) == "Nothing on today"


def test_new_arrivals_since_yesterday_two_titles_then_more():
    a = {"arr": snap({"arrived": [arrived("Severance · S02E03 · Who Is Alive?", 2), arrived("Dune", 20),
                                  arrived("Andor · S02 · 3 episodes", 30), arrived("Old", 24 * 3)]})}
    assert line(snaps=a) == "New: Severance S02E03 and Dune +1 more"
    one = {"arr": snap({"arrived": [arrived("Dune", 1)]})}
    assert line(snaps=one) == "New: Dune"


def test_arrivals_older_than_yesterday_or_without_a_time_say_nothing():
    old = {"arr": snap({"arrived": [arrived("Old", 24 * 3), {"title": "No time", "kind": "movie", "when": "1h ago"}]})}
    assert line(snaps=old) is None
    assert line(snaps={"arr": SimpleNamespace(status="error", data=None, age_minutes=1)}) is None


def test_server_word_only_when_it_needs_attention():
    assert line(server={"name": "Server", "state": "warn"}) == "Server needs attention"
    assert line(server={"name": "Server", "state": "fresh"}) is None
    assert line(server={"name": "Box", "state": "warn"}) == "Box needs attention"   # the registry's name, not code's


def test_all_clauses_in_order_joined_by_dots():
    out = line(snaps={"arr": snap({"arrived": [arrived("Severance · S02E03 · X", 1)]})},
               upcoming=up(ev("Dentist"), ev("Gym", "18:00")), weather=wx([0, 0, 0, 0, 0, 0, 70]),
               server={"name": "Server", "state": "warn"})
    assert out == "Rain from 15:00 · 2 events · first 9:30 Dentist · New: Severance S02E03 · Server needs attention"
    assert not out.endswith(".")


def test_empty_case_is_none():
    assert line() is None


def test_short_title():
    assert short_title("Severance · S02E03 · Who Is Alive?") == "Severance S02E03"
    assert short_title("Severance · S02 · 3 episodes") == "Severance S02"
    assert short_title("Dune: Part Two") == "Dune: Part Two"


def test_today_module_never_names_an_area():
    text = (Path(__file__).resolve().parents[2] / "hub" / "today.py").read_text(encoding="utf-8")
    for name in ('"server"', '"calendar"', '"media"', '"weather"', "'server'"):
        assert name not in text.lower()


# ---- on the hub page ----

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
SAMPLE_DATA = {p.stem: json.loads(p.read_text(encoding="utf-8"))["data"]
               for p in SAMPLES.glob("*.json") if not p.stem.startswith("_")}


@pytest.fixture()
def hub_sub(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def get(**override):
        for cid, d in {**SAMPLE_DATA, **override}.items():
            write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        with TestClient(hub.main.app) as c:
            body = c.get("/").text
        head = re.search(r'<header class="pagehead">.*?</header>', body, re.S).group(0)
        return hub.main, re.search(r'<p class="pagehead-sub">(.*?)</p>', head, re.S).group(1)
    return get


def test_hub_sub_is_the_date_then_the_today_line(hub_sub):
    day = home_now().date()   # the home day, as the Today line counts it - the NAS gate runs on a UTC clock (2026-10-14)
    gcal = {**SAMPLE_DATA["gcal"], "events": [{"title": "Bins out", "start": day.isoformat(),
                                               "end": (day + timedelta(days=1)).isoformat(),
                                               "all_day": True, "owner": "shared"}]}
    at = datetime.now(timezone.utc).isoformat()
    arr = {**SAMPLE_DATA["arr"], "arrived": [{"title": "Severance · S02E03 · Who Is Alive?", "kind": "episode",
                                              "when": "just now", "at": at, "poster": None, "item_key": None}]}
    main, sub = hub_sub(gcal=gcal, arr=arr)
    now = main.shell._now_home()
    assert sub.startswith(f"{now:%a} {now.day} {now:%b} · ")
    assert "1 event · Bins out all day" in sub and "New: Severance S02E03" in sub
    assert sub.index("Bins out") < sub.index("New: ")
