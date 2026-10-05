"""Media Phase 1 — the real Jellyfin connector: transform off the fixtures,
user selection, live fetch shape, and the no-URL/key-leak guarantee.

Live HTTP is always intercepted, so the suite stays offline by construction.
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import requests

from connectors.stubs import Jellyfin

URL = "http://jelly.example.invalid:8096"
KEY = "SECRETKEYvalue"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data" / "jellyfin.schema.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture()
def raw():
    return Jellyfin().fetch_fixture()


def test_requires_the_url_and_api_key_names():
    assert Jellyfin.requires_env == ("JELLYFIN_URL", "JELLYFIN_API_KEY")


def test_fixture_dir_is_one_file_per_fetch_key(raw):
    assert set(raw) == {"raw_users", "raw_system", "raw_sessions", "raw_resume", "raw_nextup",
                        "raw_latest", "raw_counts", "raw_history"}


def test_now_playing_rows_carry_a_play_method_word(raw):
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert [p["play_method"] for p in data["now_playing"]] == ["Direct play", "Transcoding"]
    assert data["now_playing"][1]["title"] == "Quiet Coast · S02E04 · Late Tide"
    assert data["now_playing"][0]["progress_pct"] == 25
    assert data["summary"] == "2 playing now"
    assert data["secondary"] == "The Long Road Home · Sample Person · Direct play"


def test_play_method_falls_back_to_transcoding_info(raw):
    raw = copy.deepcopy(raw)
    session = raw["raw_sessions"][0]
    del session["PlayState"]["PlayMethod"]
    assert Jellyfin().transform(raw)["now_playing"][0]["play_method"] == "Direct play"
    session["TranscodingInfo"] = {"IsVideoDirect": False}
    assert Jellyfin().transform(raw)["now_playing"][0]["play_method"] == "Transcoding"
    session["PlayState"]["PlayMethod"] = "DirectStream"
    assert Jellyfin().transform(raw)["now_playing"][0]["play_method"] == "Direct stream"


def test_up_next_merges_resume_then_nextup_without_duplicates(raw):
    up = Jellyfin().transform(raw)["up_next"]
    assert [(u["title"], u["kind"], u["remaining_text"]) for u in up] == [
        ("Dust and Daylight", "movie", "31 min left"),
        ("Quiet Coast · S02E05 · Break of Dawn", "episode", "30 min left"),
        ("Northern Lines · S01E03 · The Understudy", "episode", "Next episode"),
    ]


def test_nothing_playing_summary_counts_up_next(raw):
    raw = copy.deepcopy(raw)
    raw["raw_sessions"] = []
    data = Jellyfin().transform(raw)
    assert data["summary"] == "Nothing playing · 3 up next"
    assert data["secondary"] == "Dust and Daylight"
    jsonschema.validate(data, SCHEMA)


USERS = [
    {"Id": "u1", "Name": "Plain", "Policy": {"IsAdministrator": False}},
    {"Id": "u2", "Name": "Boss", "Policy": {"IsAdministrator": True}},
    {"Id": "u3", "Name": "Other", "Policy": {"IsAdministrator": False}},
]


def test_user_selection_order():
    assert Jellyfin.pick_user(USERS, "Other")["Id"] == "u3"
    assert Jellyfin.pick_user(USERS, None)["Id"] == "u2"          # first admin
    assert Jellyfin.pick_user(USERS, "Nobody")["Id"] == "u2"      # unknown name -> admin
    assert Jellyfin.pick_user([USERS[0], USERS[2]], None)["Id"] == "u1"  # first user
    with pytest.raises(RuntimeError):
        Jellyfin.pick_user([], None)


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("JELLYFIN_URL", URL + "/")
    monkeypatch.setenv("JELLYFIN_API_KEY", KEY)
    monkeypatch.delenv("JELLYFIN_USER", raising=False)
    return snapshots


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_live_fetch_calls_the_documented_endpoints(live, monkeypatch, raw):
    monkeypatch.setenv("JELLYFIN_USER", "Sample Partner")
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, headers, params, timeout))
        path = url[len(URL):]
        key = {"/Users": "raw_users", "/System/Info/Public": "raw_system", "/Sessions": "raw_sessions",
               "/Shows/NextUp": "raw_nextup", "/Items/Counts": "raw_counts"}.get(path)
        if key is None:
            key = ("raw_resume" if path.endswith("/Items/Resume")
                   else "raw_history" if path.endswith("/Items") else "raw_latest")
        return FakeResponse(raw[key])

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Jellyfin().run()

    assert envelope["status"] == "ok", envelope["error"]
    paths = [c[0][len(URL):] for c in calls]
    assert paths == ["/Users", "/System/Info/Public", "/Sessions", "/Users/user-fixture-2/Items/Resume",
                     "/Shows/NextUp", "/Users/user-fixture-2/Items/Latest", "/Items/Counts",
                     "/Users/user-fixture-2/Items"]
    assert all(c[3] == 10 for c in calls)
    assert all(c[1]["Authorization"] == f"MediaBrowser Token={KEY}" for c in calls)
    assert calls[4][2]["UserId"] == "user-fixture-2"
    hist = calls[7][2]
    assert hist["Filters"] == "IsPlayed" and hist["SortBy"] == "DatePlayed" and hist["Limit"] == 500
    assert hist["IncludeItemTypes"] == "Movie,Episode" and "UserData" in hist["Fields"]
    assert envelope["data"]["history"]["recent"][0]["title"].startswith("Quiet Coast")
    jsonschema.validate(envelope["data"], SCHEMA)


def test_failure_never_leaks_the_url_or_key(live, monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise requests.ConnectionError(f"Max retries exceeded for url: {url} key={KEY}")

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Jellyfin().run()
    assert envelope["status"] == "error"
    dumped = json.dumps(envelope)
    assert "example.invalid" not in dumped and KEY not in dumped
    assert "ConnectionError" in envelope["error"]


def test_http_failure_reason_is_the_status_code(live, monkeypatch):
    class Fake401:
        status_code = 401

        def raise_for_status(self):
            raise requests.HTTPError(f"401 for url: {URL}/Users", response=self)

    monkeypatch.setattr(requests, "get", lambda *a, **k: Fake401())
    envelope = Jellyfin().run()
    assert "HTTP 401" in envelope["error"] and "example.invalid" not in envelope["error"]


def test_live_mode_without_key_fails_naming_the_variable(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("JELLYFIN_URL", URL)
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    envelope = Jellyfin().run()
    assert envelope["status"] == "error" and "JELLYFIN_API_KEY" in envelope["error"]


# ---- watch history (Phase 4a) — the fixture's pinned "now" is 2026-01-01T00:00Z

@pytest.fixture()
def history(snapshots, raw):
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    return data["history"]


def test_history_windows_and_hours(history):
    assert (history["week_count"], history["month_count"]) == (8, 16)
    assert history["hours_month"] == 18.7
    assert history["hours_total"] == 45.1  # PlayCount x runtime, summed


def test_recent_is_newest_first_capped_and_episode_titles_carry_the_show(history):
    recent = history["recent"]
    assert len(recent) == 20
    assert recent[0] == {"title": "Quiet Coast · S02E04 · Late Tide", "kind": "episode",
                         "watched_at": "2025-12-31T21:10:00.0000000Z", "when": "2 hours ago",
                         "poster": "jf:series-fixture-1", "item_key": "jf:series-fixture-1"}
    assert recent[3]["title"] == "Harbour Lights" and recent[3]["kind"] == "movie"
    stamps = [r["watched_at"] for r in recent]
    assert stamps == sorted(stamps, reverse=True)


def test_most_played_groups_episodes_by_show_and_sorts_movies_by_plays(history):
    assert history["most_played_shows"][0] == {"title": "Quiet Coast", "episodes": 6, "hours": 4.5,
                                               "poster": "jf:series-fixture-1",
                                               "item_key": "jf:series-fixture-1"}
    assert [s["title"] for s in history["most_played_shows"]] == [
        "Quiet Coast", "Night Ferry", "Northern Lines", "Harbour Watch"]
    movies = history["most_played_movies"]
    assert movies[0]["title"] == "The Long Road Home" and movies[0]["plays"] == 3
    assert len(movies) == 10 and all(m["plays"] >= 1 for m in movies)


def test_on_this_day_lists_earlier_years_only(history):
    assert [(d["title"], d["kind"], d["years_ago"]) for d in history["on_this_day"]] == [
        ("Salt Flats", "movie", 1), ("Copper Hills", "movie", 2)]


def test_absent_raw_history_gives_an_empty_block(snapshots, raw):
    raw = copy.deepcopy(raw)
    del raw["raw_history"]
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["history"] == {
        "recent": [], "week_count": 0, "month_count": 0, "hours_total": 0.0, "hours_month": 0.0,
        "most_played_shows": [], "most_played_movies": [], "on_this_day": []}


def test_history_older_than_a_month_counts_only_toward_all_time(snapshots, raw):
    raw = copy.deepcopy(raw)
    raw["raw_history"]["Items"] = [i for i in raw["raw_history"]["Items"]
                                   if i["UserData"]["LastPlayedDate"] < "2025-11-01"]
    h = Jellyfin().transform(raw)["history"]
    assert h["week_count"] == h["month_count"] == 0 and h["hours_month"] == 0
    assert h["hours_total"] > 0


# ---- poster refs: the hub's /img proxy turns these into art

def test_poster_refs_prefer_the_series_for_episodes(raw):
    data = Jellyfin().transform(raw)
    movie, episode = data["now_playing"]
    assert (movie["poster"], movie["backdrop"]) == ("jf:item-fixture-1", "jfb:item-fixture-1")
    assert (episode["poster"], episode["backdrop"]) == ("jf:series-fixture-1", "jfb:series-fixture-1")
    assert data["up_next"][1]["poster"] == "jf:series-fixture-1"
    assert data["latest"][0]["poster"] == "jf:item-fixture-6"
    assert data["latest"][1]["poster"] == "jf:series-fixture-1"


def test_episode_without_a_series_id_falls_back_to_its_own_id(raw):
    raw = copy.deepcopy(raw)
    del raw["raw_sessions"][1]["NowPlayingItem"]["SeriesId"]
    assert Jellyfin().transform(raw)["now_playing"][1]["poster"] == "jf:item-fixture-2"


def test_item_key_is_tmdb_for_movies_and_the_series_for_episodes(raw):
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    playing = {p["title"]: p["item_key"] for p in data["now_playing"]}
    assert playing["The Long Road Home"] == "tmdb:101"            # ProviderIds.Tmdb present
    assert playing["Quiet Coast · S02E04 · Late Tide"] == "jf:series-fixture-1"  # episode -> series
    latest = {r["title"]: r["item_key"] for r in data["latest"]}
    assert latest["Desert Crossing"] == "jf:item-fixture-8"       # movie without a Tmdb id
    assert all(r["item_key"] for r in data["history"]["recent"] + data["up_next"])


# ---- deep-link ids (2026-10-05) ----

def test_rows_carry_their_own_jf_id_and_the_data_a_server_id(raw):
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["server_id"] == "server-fixture-1"
    episode = next(p for p in data["now_playing"] if "Quiet Coast" in p["title"])
    assert episode["poster"] == "jf:series-fixture-1"           # art uses the series...
    assert episode["jf_id"] == raw["raw_sessions"][1]["NowPlayingItem"]["Id"]  # ...the link the episode
    assert episode["jf_id"] != "series-fixture-1"
    assert data["up_next"][1]["jf_id"] == "item-fixture-4"
    assert all(r["jf_id"] for r in data["latest"])


def test_absent_raw_system_gives_a_null_server_id(raw):
    raw = copy.deepcopy(raw)
    del raw["raw_system"]
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["server_id"] is None
