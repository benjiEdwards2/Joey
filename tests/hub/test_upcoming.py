"""Calendar upcoming-events list (2026-09-11): next 7 days, day-grouped, on any
area page whose tiles read the gcal snapshot. Owner chips are text (colour never
the only encoding); the owner view filters the list with Q9 semantics.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub.main import build_upcoming
from hub.registry import load_registry
from tests.hub.test_registry import AREAS_YAML, make_area, write_registry
from tests.hub.test_store import write_envelope

MEL = timezone(timedelta(hours=11))
NOW = datetime(2026, 1, 5, 8, 0, tzinfo=MEL)  # Mon 05 Jan 2026, 08:00 local


def ev(title, start, end, all_day=False, owner="shared"):
    return {"title": title, "start": start, "end": end,
            "all_day": all_day, "owner": owner}


def test_window_excludes_finished_and_beyond_seven_days():
    events = [
        ev("Done earlier", "2026-01-05T06:00+11:00", "2026-01-05T07:00+11:00"),
        ev("In window", "2026-01-08T10:00+11:00", "2026-01-08T11:00+11:00"),
        ev("Eighth day out", "2026-01-12T10:00+11:00", "2026-01-12T11:00+11:00"),
    ]
    groups = build_upcoming(events, "both", NOW)
    titles = [e["title"] for g in groups for e in g["events"]]
    assert titles == ["In window"]


def test_day_labels_today_tomorrow_then_date():
    events = [
        ev("A", "2026-01-05T09:00+11:00", "2026-01-05T09:30+11:00"),
        ev("B", "2026-01-06T09:00+11:00", "2026-01-06T09:30+11:00"),
        ev("C", "2026-01-07T09:00+11:00", "2026-01-07T09:30+11:00"),
    ]
    groups = build_upcoming(events, "both", NOW)
    assert [g["label"] for g in groups] == ["Today", "Tomorrow", "Wed 07 Jan"]
    assert groups[0]["events"][0]["time_text"] == "09:00 – 09:30"


def test_all_day_exclusive_end_and_in_progress_groups_under_today():
    events = [
        # ICS exclusive end: covered Jan 4 only — over by today, excluded.
        ev("Yesterday", "2026-01-04", "2026-01-05", all_day=True),
        # Started Jan 3, runs through Jan 7 — in progress, shows under Today.
        ev("Leave", "2026-01-03", "2026-01-08", all_day=True),
    ]
    groups = build_upcoming(events, "both", NOW)
    assert len(groups) == 1 and groups[0]["label"] == "Today"
    assert groups[0]["events"] == [
        {"title": "Leave", "time_text": "All day", "owner": "shared"}]


def test_owner_view_semantics_q9():
    events = [
        ev("Mine", "2026-01-06T09:00+11:00", "2026-01-06T10:00+11:00", owner="you"),
        ev("Hers", "2026-01-06T11:00+11:00", "2026-01-06T12:00+11:00", owner="her"),
        ev("Ours", "2026-01-06T13:00+11:00", "2026-01-06T14:00+11:00", owner="shared"),
    ]
    def titles(view):
        return [e["title"] for g in build_upcoming(events, view, NOW) for e in g["events"]]
    assert titles("both") == ["Mine", "Hers", "Ours"]
    assert titles("you") == ["Mine", "Ours"]
    assert titles("her") == ["Hers", "Ours"]


def test_malformed_event_skipped_never_a_crash():
    events = [
        {"title": "No dates", "owner": "you"},
        ev("Bad start", "not-a-date", "2026-01-06T10:00+11:00"),
        ev("Fine", "2026-01-06T09:00+11:00", "2026-01-06T10:00+11:00"),
    ]
    groups = build_upcoming(events, "both", NOW)
    assert [e["title"] for g in groups for e in g["events"]] == ["Fine"]


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    fixture = write_registry(
        tmp_path,
        make_area("alpha", "cal-t", snapshot="gcal", stale_after_minutes=120),
    )
    monkeypatch.setenv("AREAS_PATH", str(fixture))

    def build(snapshot_dir):
        monkeypatch.setenv("SNAPSHOT_DIR", str(snapshot_dir))
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build, tmp_path


def _live_events():
    """Events relative to the real clock, since the route uses datetime.now()."""
    now = datetime.now().astimezone()
    t1 = now + timedelta(hours=2)
    d2 = (now + timedelta(days=1)).date()
    return [
        ev("Timed today", t1.isoformat(), (t1 + timedelta(hours=1)).isoformat(), owner="you"),
        ev("Away", str(d2), str(d2 + timedelta(days=1)), all_day=True, owner="her"),
    ]


def test_route_renders_grouped_list_with_owner_chips(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "gcal", age_minutes=5,
                   data={"summary": "S", "events": _live_events()})
    with build(snaps) as client:
        html = client.get("/a/alpha").text
        assert "Next 7 days" in html
        assert "Timed today" in html and "Away" in html
        assert "All day" in html
        assert ">You</span>" in html and ">Her</span>" in html
        assert "Today" in html and "Tomorrow" in html


def test_route_owner_view_filters_the_list(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "gcal", age_minutes=5,
                   data={"summary": "S", "events": _live_events()})
    with build(snaps) as client:
        html = client.get("/a/alpha?owner_view=you").text
        assert "Timed today" in html and "Away" not in html


def test_route_empty_window_states_it_in_words(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "gcal", age_minutes=5, data={"summary": "S", "events": []})
    with build(snaps) as client:
        html = client.get("/a/alpha").text
        assert "Next 7 days" in html
        assert "Nothing in the next 7 days" in html


def test_route_absent_snapshot_renders_no_list(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "never-created") as client:
        r = client.get("/a/alpha")
        assert r.status_code == 200
        assert "Next 7 days" not in r.text
        assert "Not connected" in r.text  # the tile carries the state


def test_real_registry_carries_the_google_calendar_link():
    reg = load_registry(AREAS_YAML)
    hrefs = [t.href for a in reg.areas for t in a.tiles if t.tier.value == "link"]
    assert "https://calendar.google.com" in hrefs
