"""E5 (H2, 2026-10-13): media releases in Next 7 days. A gcal tile with `show_media_releases: true` merges the arr
snapshot's calendar rows (monitored films; episodes of shows watched lately, in progress or followed) into its list as
their own row type with a "Media" word chip; the hub Calendar card's per-day bars stay calendar only."""
import importlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from hub import upcoming
from hub.registry import Tile, load_registry
from tests.hub.helpers import AREAS_YAML, write_envelope

MEL = timezone(timedelta(hours=11))
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=MEL)


def snap(data):
    return SimpleNamespace(status="ok", data=data, age_minutes=1)


def cal(title, days_ahead, kind="episode", label=""):
    return {"title": title, "kind": kind, "date": (NOW.date() + timedelta(days=days_ahead)).isoformat(),
            "label": label, "poster": None, "item_key": None}


JELLY = {"shows": [{"title": "Severance", "last_played_at": (NOW - timedelta(days=3)).isoformat()},
                   {"title": "Old Show", "last_played_at": (NOW - timedelta(days=90)).isoformat()}],
         "up_next": [{"show_title": "The Bear", "title": "The Bear · S03E02 · Next"}],
         "her": {"up_next": [{"show_title": "Bluey"}], "shows": []}}


@pytest.fixture(autouse=True)
def no_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))   # no follows unless a test adds one


def rows(this_week, view="both", jelly=JELLY):
    snaps = {"arr": snap({"this_week": this_week}), "jellyfin": snap(jelly)}
    return [(d, r["title"], r["time_text"]) for d, r in upcoming.release_rows(snaps, view, NOW)]


def test_films_always_and_episodes_only_for_shows_being_watched():
    got = rows([cal("Dune", 1, "movie", "Digital"), cal("Severance · S02E04 · Woe's Hollow", 2, label=""),
                cal("The Bear · S03E03 · Doors", 3, label="Finale"), cal("Old Show · S05E01 · Back", 1, label="Premiere"),
                cal("Never Watched · S01E01 · Pilot", 1, label="Premiere")])
    assert [t for _, t, _ in got] == ["Dune", "Severance · S02E04 · Woe's Hollow", "The Bear · S03E03 · Doors"]
    assert [w for _, _, w in got] == ["Digital release", "New episode", "Finale"]


def test_owner_view_picks_whose_watching_counts():
    week = [cal("Bluey · S03E10 · Cricket", 1), cal("Severance · S02E04 · X", 1)]
    assert [t for _, t, _ in rows(week, "her")] == ["Bluey · S03E10 · Cricket"]
    assert [t for _, t, _ in rows(week, "you")] == ["Severance · S02E04 · X"]
    assert len(rows(week, "both")) == 2


def test_a_followed_show_counts(monkeypatch):
    from hub import media_follow
    monkeypatch.setattr(media_follow, "follows", lambda: [{"kind": "show", "name": "The Studio"},
                                                          {"kind": "person", "name": "Never Watched"}])
    got = rows([cal("The Studio · S01E05 · X", 2), cal("Never Watched · S01E01 · Pilot", 2)], jelly={})
    assert [t for _, t, _ in got] == ["The Studio · S01E05 · X"]


def test_window_and_bad_rows():
    got = rows([cal("Past", -1, "movie"), cal("Today", 0, "movie", "Cinemas"), cal("Day 7", 7, "movie"),
                {"title": "No date", "kind": "movie"}, {"date": "junk", "title": "X", "kind": "movie"}])
    assert [(t, w) for _, t, w in got] == [("Today", "In cinemas")]


def test_not_connected_arr_adds_nothing():
    assert upcoming.release_rows({}, "both", NOW) == []
    assert upcoming.release_rows({"arr": SimpleNamespace(status="error", data=None)}, "both", NOW) == []


def test_merge_puts_releases_after_the_days_events_and_slots_new_days():
    groups = [{"day": NOW.date(), "label": "Today", "events": [{"title": "Dentist"}]}]
    rel = [(NOW.date() + timedelta(days=2), {"title": "Dune", "release": True}),
           (NOW.date(), {"title": "Severance", "release": True})]
    out = upcoming.merge_releases(groups, rel, NOW.date())
    assert [(g["label"], [e["title"] for e in g["events"]]) for g in out] == [
        ("Today", ["Dentist", "Severance"]), (upcoming._day_label(NOW.date() + timedelta(days=2), NOW.date()), ["Dune"])]
    assert upcoming.per_day_counts(out, NOW.date())[:3] == [1, 0, 0]       # the bars stay calendar only


def test_registry_field_defaults_off_and_is_on_for_the_calendar_tile():
    assert Tile(id="t", label="T", tier="embed", owner="shared").show_media_releases is False
    reg = load_registry(AREAS_YAML)
    on = [t for a in reg.areas for t in a.tiles if t.show_media_releases]
    assert [t.snapshot for t in on] == ["gcal"]


def test_upcoming_keys_on_snapshot_ids_not_area_names():
    text = (Path(upcoming.__file__)).read_text(encoding="utf-8")
    assert "ARR_SNAPSHOT_ID" in text and '"media"' not in text.lower() and '"calendar"' not in text.lower()


# ---- on the hub page (real areas.yaml) ----

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
SAMPLE_DATA = {p.stem: json.loads(p.read_text(encoding="utf-8"))["data"]
               for p in SAMPLES.glob("*.json") if not p.stem.startswith("_")}


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    monkeypatch.delenv("AREAS_PATH", raising=False)
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def get(areas_path=None, **override):
        if areas_path:
            monkeypatch.setenv("AREAS_PATH", str(areas_path))
        for cid, d in {**SAMPLE_DATA, **override}.items():
            write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        with TestClient(hub.main.app) as c:
            return c.get("/").text
    return get


def _page_data():
    today = datetime.now().astimezone().date()
    played = datetime.now(timezone.utc).isoformat()
    jelly = {**SAMPLE_DATA["jellyfin"], "shows": [{**SAMPLE_DATA["jellyfin"]["shows"][0], "title": "Severance",
                                                   "last_played_at": played}]}
    arr = {**SAMPLE_DATA["arr"], "this_week": [
        {"title": "Severance · S02E04 · Woe's Hollow", "kind": "episode", "date": (today + timedelta(days=2)).isoformat(),
         "label": "", "poster": None, "item_key": "tvdb:1"},
        {"title": "Nobody Watches This · S01E01 · Pilot", "kind": "episode",
         "date": (today + timedelta(days=2)).isoformat(), "label": "Premiere", "poster": None, "item_key": "tvdb:2"}]}
    gcal = {**SAMPLE_DATA["gcal"], "events": [{"title": "Dinner at Sam's", "start": (today + timedelta(days=2)).isoformat(),
                                               "end": (today + timedelta(days=3)).isoformat(), "all_day": True,
                                               "owner": "shared"}]}
    return {"jellyfin": jelly, "arr": arr, "gcal": gcal}


def test_hub_next_7_days_shows_the_release_row_with_its_word_chip(hub):
    body = hub(**_page_data())
    band = re.search(r'<section class="sec upcoming".*?</section>', body, re.S).group(0)
    assert "Dinner at Sam&#39;s" in band and "Severance · S02E04 · Woe&#39;s Hollow" in band
    assert "Nobody Watches This" not in band                                    # not watched, not followed
    assert band.index("Dinner at Sam") < band.index("Severance")              # the day's own events first
    row = band.split('<div class="row upc upc-release">', 1)[1].split('<div class="row upc', 1)[0]
    assert '<span class="upc-chip">Media</span>' in row and "New episode" in row


def test_the_calendar_cards_bars_count_events_only(hub):
    body = hub(**_page_data())
    import hub.main as m
    up = m.hub_upcoming(m.shell.get_snapshots(), "both")
    assert sum(up["per_day"]) == 1 and sum(len(g["events"]) for g in up["groups"]) == 2


def test_flag_off_means_no_release_rows(hub, tmp_path):
    raw = yaml.safe_load(AREAS_YAML.read_text(encoding="utf-8"))
    for a in raw["areas"]:
        for t in a["tiles"]:
            t.pop("show_media_releases", None)
    off = tmp_path / "areas.yaml"
    off.write_text(yaml.safe_dump(raw), encoding="utf-8")
    body = hub(areas_path=off, **_page_data())
    assert "upc-release" not in body and "Severance · S02E04" not in body
