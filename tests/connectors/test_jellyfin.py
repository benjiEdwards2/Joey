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
                        "raw_latest", "raw_counts", "raw_history", "raw_movies", "raw_shows",
                        "raw_her_resume", "raw_her_nextup", "raw_her_history",
                        "raw_her_movies", "raw_her_shows"}


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
            kind = (params or {}).get("IncludeItemTypes")
            key = ("raw_resume" if path.endswith("/Items/Resume")
                   else "raw_movies" if path.endswith("/Items") and kind == "Movie"
                   else "raw_shows" if path.endswith("/Items") and kind == "Series"
                   else "raw_history" if path.endswith("/Items") else "raw_latest")
        return FakeResponse(raw[key])

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Jellyfin().run()

    assert envelope["status"] == "ok", envelope["error"]
    paths = [c[0][len(URL):] for c in calls]
    assert paths == ["/Users", "/System/Info/Public", "/Sessions", "/Users/user-fixture-2/Items/Resume",
                     "/Shows/NextUp", "/Users/user-fixture-2/Items/Latest", "/Items/Counts",
                     "/Users/user-fixture-2/Items", "/Users/user-fixture-2/Items",
                     "/Users/user-fixture-2/Items"]
    assert all(c[3] == 10 for c in calls)
    assert all(c[1]["Authorization"] == f"MediaBrowser Token={KEY}" for c in calls)
    assert calls[4][2]["UserId"] == "user-fixture-2"
    hist = calls[7][2]
    assert hist["Filters"] == "IsPlayed" and hist["SortBy"] == "DatePlayed" and hist["Limit"] == 500
    assert hist["IncludeItemTypes"] == "Movie,Episode" and "UserData" in hist["Fields"]
    assert envelope["data"]["history"]["recent"][0]["title"].startswith("Quiet Coast")
    assert calls[8][2] == {"IncludeItemTypes": "Movie", "Recursive": "true", "SortBy": "SortName",
                           "SortOrder": "Ascending", "Limit": 2000,
                           "Fields": "DateCreated,ProviderIds,Genres,ProductionYear,Overview"}
    assert calls[9][2] == {"IncludeItemTypes": "Series", "Recursive": "true", "SortBy": "SortName",
                           "SortOrder": "Ascending", "Limit": 2000,
                           "Fields": "DateCreated,ProviderIds,Genres,ProductionYear,Status,"
                                     "RecursiveItemCount,Overview"}
    assert [m["title"] for m in envelope["data"]["movies"]][0] == "The Long Road Home"
    jsonschema.validate(envelope["data"], SCHEMA)


def test_failure_never_leaks_the_url_or_key(live, monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise requests.ConnectionError(f"Max retries exceeded for url: {url} key={KEY}")

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Jellyfin().run()
    assert envelope["status"] == "error"
    dumped = json.dumps(envelope)
    assert "example.invalid" not in dumped and KEY not in dumped
    assert "Jellyfin users failed (connection refused)" in envelope["error"]


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
    assert recent[0] == {"title": "Quiet Coast · S02E04 · Late Tide", "kind": "episode", "jf_id": "hist-fixture-1",
                         "watched_at": "2025-12-31T21:10:00.0000000Z", "when": "2 hours ago",
                         "poster": "jf:series-fixture-1", "item_key": "jf:series-fixture-1",
                         "show_key": "jf:series-fixture-1", "season_key": "jf:season-1-2",
                         "episode_key": "jf:hist-fixture-1", "season": 2, "episode": 4,
                         "show_title": "Quiet Coast"}
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


# ---- Georgina's view (2026-10-05): JELLYFIN_USER_HER, exact name, never the admin ----

def test_pick_her_user_is_exact_match_or_none():
    assert Jellyfin.pick_her_user(USERS, "Other")["Id"] == "u3"
    assert Jellyfin.pick_her_user(USERS, "other") is None      # exact, case included
    assert Jellyfin.pick_her_user(USERS, "Nobody") is None     # never falls back to the admin
    assert Jellyfin.pick_her_user(USERS, None) is None and Jellyfin.pick_her_user(USERS, "") is None
    assert Jellyfin.pick_her_user([], "Other") is None


def test_fixture_mode_always_carries_her_block_from_the_georgina_user(snapshots, raw, monkeypatch):
    monkeypatch.setenv("JELLYFIN_USER_HER", "someone else")  # fixture mode never reads the real env
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["her"]["user"] == "georgina"
    assert [u["title"] for u in data["her"]["up_next"]] == [
        "Cold Harbour", "Garden Lane · S01E02 · Hedgerow"]
    assert data["her"]["history"]["recent"][0]["title"] == "Garden Lane · S01E01 · First Frost"
    assert all("Quiet Coast" not in r["title"] for r in data["her"]["history"]["recent"])
    assert data["up_next"][0]["title"] == "Dust and Daylight"  # B.'s top-level fields unchanged


def test_transform_emits_null_her_when_the_keys_are_absent(raw):
    raw = {k: v for k, v in raw.items() if not k.startswith("raw_her_")}
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["her"] is None


def test_schema_rejects_a_malformed_her_block(raw):
    data = Jellyfin().transform(raw)
    data["her"] = {"user": "georgina", "up_next": [], "history": {}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, SCHEMA)


def _live_calls(monkeypatch, raw):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url[len(URL):], params))
        path = url[len(URL):]
        key = {"/Users": "raw_users", "/System/Info/Public": "raw_system", "/Sessions": "raw_sessions",
               "/Items/Counts": "raw_counts"}.get(path)
        if key is None and path == "/Shows/NextUp":
            key = "raw_her_nextup" if (params or {}).get("UserId") == "user-fixture-3" else "raw_nextup"
        if key is None:
            her = "user-fixture-3" in path
            kind = (params or {}).get("IncludeItemTypes")
            if path.endswith("/Items") and kind in ("Movie", "Series"):
                key = f"raw_{'her_' if her else ''}{'movies' if kind == 'Movie' else 'shows'}"
            else:
                key = ("raw_her_resume" if her else "raw_resume") if path.endswith("/Items/Resume") else (
                    "raw_her_history" if her else "raw_history") if path.endswith("/Items") else "raw_latest"
        return FakeResponse(raw[key])

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


def test_live_fetch_calls_her_endpoints_only_when_set_and_found(live, monkeypatch, raw):
    monkeypatch.setenv("JELLYFIN_USER_HER", "georgina")
    calls = _live_calls(monkeypatch, raw)
    envelope = Jellyfin().run()
    assert envelope["status"] == "ok", envelope["error"]
    paths = [c[0] for c in calls]
    assert paths[-5:] == ["/Users/user-fixture-3/Items/Resume", "/Shows/NextUp", "/Users/user-fixture-3/Items",
                          "/Users/user-fixture-3/Items", "/Users/user-fixture-3/Items"]
    assert calls[-5][1]["Limit"] == 10 and calls[-5][1]["MediaTypes"] == "Video"
    assert calls[-4][1]["UserId"] == "user-fixture-3" and calls[-4][1]["Limit"] == 10
    assert calls[-3][1]["Filters"] == "IsPlayed" and calls[-3][1]["Limit"] == 500
    assert calls[-2][1]["IncludeItemTypes"] == "Movie" and calls[-2][1]["Limit"] == 2000
    assert calls[-1][1]["IncludeItemTypes"] == "Series" and "Status" in calls[-1][1]["Fields"]
    assert [m["title"] for m in envelope["data"]["her"]["movies"]][0] == "Harbour Lights"
    assert len(envelope["data"]["her"]["shows"]) == 2
    assert envelope["data"]["her"]["user"] == "georgina"
    assert envelope["data"]["up_next"][0]["title"] == "Dust and Daylight"  # B.'s side still the admin's
    jsonschema.validate(envelope["data"], SCHEMA)


def test_live_fetch_skips_her_when_env_unset(live, monkeypatch, raw):
    monkeypatch.delenv("JELLYFIN_USER_HER", raising=False)
    calls = _live_calls(monkeypatch, raw)
    envelope = Jellyfin().run()
    assert envelope["status"] == "ok" and envelope["data"]["her"] is None
    assert not any("user-fixture-3" in c[0] or (c[1] or {}).get("UserId") == "user-fixture-3" for c in calls)


def test_live_fetch_with_unknown_her_name_is_not_an_error_and_never_uses_the_admin(live, monkeypatch, raw):
    monkeypatch.setenv("JELLYFIN_USER_HER", "Nobody")
    calls = _live_calls(monkeypatch, raw)
    envelope = Jellyfin().run()
    assert envelope["status"] == "ok" and envelope["data"]["her"] is None
    assert len(calls) == 10  # exactly B.'s calls, nothing extra
    assert "Nobody" not in json.dumps(envelope)


def test_history_rows_carry_jf_id_for_deep_links(raw):
    data = Jellyfin().transform(raw)
    jsonschema.validate(data, SCHEMA)
    assert data["history"]["recent"][0]["jf_id"] == "hist-fixture-1"
    assert all(r["jf_id"] for r in data["history"]["recent"] + data["history"]["on_this_day"])


def test_episode_rows_carry_show_season_episode_keys_and_movies_carry_none(history):
    ep = history["recent"][0]
    assert (ep["show_key"], ep["season_key"], ep["episode_key"]) == (
        "jf:series-fixture-1", "jf:season-1-2", "jf:hist-fixture-1")
    movie = history["recent"][3]
    assert movie["show_key"] is movie["season_key"] is movie["episode_key"] is None
    assert movie["season"] is movie["episode"] is movie["show_title"] is None


def test_episode_without_season_id_has_null_season_key():
    from connectors.stubs import _jf_levels
    levels = _jf_levels({"Id": "e1", "Type": "Episode", "SeriesId": "s1", "SeriesName": "Show",
                         "ParentIndexNumber": 1, "IndexNumber": 2})
    assert levels["season_key"] is None and levels["show_key"] == "jf:s1"
    assert levels["episode_key"] == "jf:e1" and (levels["season"], levels["episode"]) == (1, 2)


def test_up_next_and_now_playing_episode_rows_carry_level_keys(snapshots, raw):
    data = Jellyfin().transform(raw)
    ep = next(r for r in data["up_next"] if r["kind"] == "episode")
    assert ep["show_key"] == ep["item_key"] and ep["episode_key"] == "jf:" + ep["jf_id"]
    assert ep["season_key"].startswith("jf:season-")
    playing = next(r for r in data["now_playing"] if r["item_key"] and r["item_key"].startswith("jf:series"))
    assert playing["show_key"] == playing["item_key"] and playing["season"] is not None


def test_on_this_day_is_the_melbourne_calendar_day(snapshots):
    """C-08: at 2026-01-01T00:00Z it is Jan 1 11:00 in Melbourne. 2024-12-31T20:00Z was Jan 1
    local (on this day); 2025-01-01T20:00Z was already Jan 2 local (not)."""
    from datetime import datetime, timezone

    items = [{"Name": n, "Type": "Movie", "Id": n, "UserData": {"LastPlayedDate": at, "PlayCount": 1}}
             for n, at in (("Local Jan 1", "2024-12-31T20:00:00Z"), ("Local Jan 2", "2025-01-01T20:00:00Z"))]
    history = Jellyfin._history(items, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert [(d["title"], d["years_ago"]) for d in history["on_this_day"]] == [("Local Jan 1", 1)]


# ---- C-09 (2026-10-09): the library lists and her view are partial-ok ----


def _failing(monkeypatch, raw, fail):
    """_live_calls, except calls whose (path, params) satisfy `fail` time out."""
    calls = _live_calls(monkeypatch, raw)
    ok_get = requests.get

    def fake_get(url, headers=None, params=None, timeout=None):
        if fail(url[len(URL):], params or {}):
            calls.append((url[len(URL):], params))
            raise requests.Timeout(f"Read timed out for url: {url}")
        return ok_get(url, headers=headers, params=params, timeout=timeout)

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


def test_a_failed_library_list_drops_only_that_list(live, monkeypatch, raw, caplog):
    monkeypatch.delenv("JELLYFIN_USER_HER", raising=False)
    _failing(monkeypatch, raw, lambda path, p: p.get("IncludeItemTypes") == "Movie")
    with caplog.at_level("WARNING", logger="connectors"):
        envelope = Jellyfin().run()
    assert envelope["status"] == "ok", envelope["error"]
    data = envelope["data"]
    assert "movies" not in data and len(data["shows"]) > 0
    assert data["summary"] and data["up_next"]            # the core feed is untouched
    jsonschema.validate(data, SCHEMA)
    assert "Jellyfin movies failed (timeout)" in caplog.text
    assert "example.invalid" not in caplog.text and KEY not in caplog.text


def test_a_failed_her_call_makes_her_null_and_keeps_the_feed_ok(live, monkeypatch, raw):
    monkeypatch.setenv("JELLYFIN_USER_HER", "georgina")
    _failing(monkeypatch, raw, lambda path, p: path == "/Users/user-fixture-3/Items/Resume")
    envelope = Jellyfin().run()
    assert envelope["status"] == "ok", envelope["error"]
    assert envelope["data"]["her"] is None and envelope["data"]["movies"]
    jsonschema.validate(envelope["data"], SCHEMA)


def test_a_failed_core_call_still_fails_the_feed(live, monkeypatch, raw):
    _failing(monkeypatch, raw, lambda path, p: path == "/Sessions")
    envelope = Jellyfin().run()
    assert envelope["status"] == "error"
    assert envelope["error"] == "RuntimeError: Jellyfin sessions failed (timeout)"
