"""Media Phase 2 — the Radarr + Sonarr connector: transform off the fixtures
(arrival/upgrade split, season grouping, this-week labels, queue, disk), the
one-app-down partial-ok rule, and the no-URL/key-leak guarantee.

Live HTTP is always intercepted, so the suite stays offline by construction.
"""

import copy
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest
import requests

from connectors.stubs import ARR_LIMIT, Arr

RADARR, SONARR = "http://radarr.example.invalid:7878", "http://sonarr.example.invalid:8989"
RKEY, SKEY = "RADARRSECRETkey", "SONARRSECRETkey"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data" / "arr.schema.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture()
def raw(snapshots):  # fixture mode pins the connector clock to the fixtures' "now"
    return Arr().fetch_fixture()


@pytest.fixture()
def data(raw):
    out = Arr().transform(raw)
    jsonschema.validate(out, SCHEMA)
    return out


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("RADARR_URL", RADARR + "/")
    monkeypatch.setenv("RADARR_API_KEY", RKEY)
    monkeypatch.setenv("SONARR_URL", SONARR)
    monkeypatch.setenv("SONARR_API_KEY", SKEY)
    # live mode reads the real clock; pin it so the fixture dates stay in the window
    monkeypatch.setattr("connectors.stubs._now", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    return snapshots


class Resp:
    def __init__(self, payload=None, code=200):
        self.payload, self.status_code = payload, code

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} for url: {RADARR}/x")
            err.response = self
            raise err

    def json(self):
        return self.payload


def fake_requests(monkeypatch, fixtures, behaviour=None):
    """Answer each call from the fixture for (app, endpoint); behaviour(app) may
    return an exception to raise or an HTTP status to fail with."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None, **kw):
        app = "radarr" if url.startswith(RADARR) else "sonarr"
        endpoint = url.rsplit("/", 1)[1]
        calls.append({"app": app, "url": url, "headers": headers, "params": params, "timeout": timeout})
        outcome = behaviour(app) if behaviour else None
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            return Resp(code=outcome)
        return Resp(fixtures[f"raw_{app}_{endpoint}"])

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


def test_requires_env_names_all_four_variables():
    assert Arr.requires_env == ("RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY")


def test_fixture_dir_is_eight_raw_files(raw):
    # WP-S3 (2026-10-06): + the radarr/sonarr count payloads and prowlarr indexer stats
    assert set(raw) == {f"raw_{a}_{e}" for a in ("radarr", "sonarr")
                        for e in ("history", "calendar", "queue", "diskspace")} | {
        "raw_radarr_movie", "raw_sonarr_series", "raw_sonarr_missing", "raw_prowlarr_indexerstats"}


def test_arrivals_exclude_upgrades_and_old_imports(data):
    titles = [r["title"] for r in data["arrived"]]
    assert titles == ["Quiet Coast · S02 · 3 episodes", "Harbour Lights",
                      "Night Ferry · S01E04 · Last Crossing", "Desert Crossing"]
    assert [r["kind"] for r in data["arrived"]] == ["season", "movie", "episode", "movie"]
    assert [r["when"] for r in data["arrived"]] == ["3 hours ago", "yesterday", "2 days ago", "3 days ago"]
    assert "Salt Flats" not in titles and "Paper Lanterns" not in titles
    assert data["summary"] == "4 arrived this week · 2 downloading"
    assert data["secondary"] == "Quiet Coast · S02 · 3 episodes"


def test_updates_come_from_the_deleted_for_upgrade_record_or_the_flag(data):
    by_title = {r["title"]: r for r in data["updated"]}
    assert by_title["Salt Flats"]["what"] == "Upgraded to 4K"           # movieFileDeleted + import
    assert by_title["Paper Lanterns"]["what"] == "Upgraded to Blu-ray"  # data.isUpgrade flag
    assert by_title["Quiet Coast · S01E01 · Pilot"]["kind"] == "episode"  # episodeFileDeleted
    assert len(by_title) == 3


def test_upgrade_text_falls_back_to_resolution_then_plain(raw):
    raw = copy.deepcopy(raw)
    rec = next(r for r in raw["raw_radarr_history"]["records"] if r["movieId"] == 4)
    rec["quality"] = {"quality": {"name": "WEBDL-1080p", "resolution": 1080}}
    assert Arr().transform(raw)["updated"][-1]["what"] == "Upgraded to 1080p"
    rec["quality"] = {}
    assert Arr().transform(raw)["updated"][-1]["what"] == "Upgraded"


def test_a_season_imported_together_is_one_line(data, raw):
    assert sum(1 for r in data["arrived"] if r["kind"] == "season") == 1
    one = copy.deepcopy(raw)
    one["raw_sonarr_history"]["records"] = [r for r in one["raw_sonarr_history"]["records"]
                                            if r["id"] not in (42, 43)]
    titles = [r["title"] for r in Arr().transform(one)["arrived"]]
    assert "Quiet Coast · S02E01 · First Light" in titles  # a lone episode keeps its name


def test_this_week_labels_and_on_disk_disc_releases_are_skipped(data):
    rows = {r["title"]: r for r in data["this_week"]}
    assert rows["Midnight Harbour"]["label"] == "Digital"
    assert rows["Glass Orchard"]["label"] == "Disc"
    assert rows["Far Shore"]["label"] == "Cinemas"
    assert rows["Night Ferry · S02E01 · New Moorings"]["label"] == "Premiere"
    assert rows["Harbour Watch · S01E08 · Landfall"]["label"] == "Finale"
    assert "Quiet Coast · S02E04 · Late Tide" not in rows   # imported this week: only under Just arrived
    assert "Desert Crossing" not in rows                    # disc release already on disk
    assert not any("Far Too Early" in t for t in rows)      # outside the 7-day window
    assert [r["date"] for r in data["this_week"]] == sorted(r["date"] for r in data["this_week"])


def test_queue_percent_status_and_time_left(data):
    movie, episode = data["downloading"]
    assert (movie["title"], movie["pct"], movie["status_text"], movie["time_left"]) == \
        ("Midnight Harbour", 75, "Downloading", "14 min")
    assert (episode["pct"], episode["time_left"]) == (25, "1h 05m")


def test_disk_is_deduplicated_by_path_across_both_apps(data):
    assert [d["path"] for d in data["disk"]] == ["/movies", "/data", "/tv"]
    assert data["disk"][0] == {"path": "/movies", "free_gb": 1117.6, "total_gb": 3725.3, "pct_used": 70}


def test_quiet_week_summary_and_secondary_fallbacks(raw):
    quiet = copy.deepcopy(raw)
    quiet["raw_radarr_history"] = {"records": []}
    quiet["raw_sonarr_history"] = {"records": []}
    data = Arr().transform(quiet)
    assert data["summary"] == "Nothing new this week"
    assert data["secondary"] == "Quiet Coast · S02E04 · Late Tide"  # first this-week title
    for key in ("raw_radarr_calendar", "raw_sonarr_calendar"):
        quiet[key] = []
    assert Arr().transform(quiet)["secondary"] == ""


def test_lists_are_capped_at_twenty(raw):
    big = copy.deepcopy(raw)
    template = big["raw_radarr_history"]["records"][0]
    big["raw_radarr_history"]["records"] = [
        {**template, "id": 1000 + i, "movieId": 1000 + i, "movie": {"title": f"Film {i}"}}
        for i in range(30)]
    data = Arr().transform(big)
    assert len(data["arrived"]) == ARR_LIMIT
    assert data["summary"].startswith("32 arrived")  # the headline counts the uncapped total
    jsonschema.validate(data, SCHEMA)


def test_fixture_mode_touches_no_network(snapshots, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used in fixture mode")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(requests, "get", boom)
    envelope = Arr().run()
    assert envelope["status"] == "ok" and envelope["updated_at"] == "2026-01-01T00:00:00+00:00"


def test_live_run_calls_all_eight_endpoints_with_key_and_timeout(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw)
    envelope = Arr().run()
    assert envelope["status"] == "ok" and "app_errors" not in envelope["data"]
    # 8 feed calls + 3 count calls (radarr movie, sonarr series + wanted/missing; WP-S3)
    assert len(calls) == 11 and all(c["timeout"] == 10 for c in calls)
    radarr = [c for c in calls if c["app"] == "radarr"]
    assert all(c["headers"] == {"X-Api-Key": RKEY} for c in radarr)
    assert all(c["headers"] == {"X-Api-Key": SKEY} for c in calls if c["app"] == "sonarr")
    history = next(c for c in radarr if c["url"].endswith("/history"))
    assert history["url"] == f"{RADARR}/api/v3/history"  # trailing slash on the env var stripped
    assert history["params"]["pageSize"] == 100 and history["params"]["sortDirection"] == "descending"
    assert history["params"]["since"].endswith("Z")
    sonarr_hist = next(c for c in calls if c["app"] == "sonarr" and c["url"].endswith("/history"))
    assert sonarr_hist["params"]["includeSeries"] == "true" and sonarr_hist["params"]["includeEpisode"] == "true"
    cal = next(c for c in radarr if c["url"].endswith("/calendar"))
    assert set(cal["params"]) == {"start", "end"}


def test_one_app_down_keeps_the_run_ok_with_an_app_error(live, monkeypatch, raw):
    fake_requests(monkeypatch, raw, lambda app: requests.ConnectTimeout("t") if app == "sonarr" else None)
    envelope = Arr().run()
    data = envelope["data"]
    assert envelope["status"] == "ok" and envelope["consecutive_failures"] == 0
    assert data["app_errors"] == {"sonarr": "timeout"}
    assert [r["title"] for r in data["arrived"]] == ["Harbour Lights", "Desert Crossing"]  # radarr only
    assert not any(" · S0" in r["title"] for r in data["this_week"])
    jsonschema.validate(data, SCHEMA)


def test_one_app_http_error_is_named_by_status(live, monkeypatch, raw):
    fake_requests(monkeypatch, raw, lambda app: 401 if app == "radarr" else None)
    assert Arr().run()["data"]["app_errors"] == {"radarr": "HTTP 401"}


def test_both_apps_down_is_an_error_and_keeps_the_previous_data(live, monkeypatch, raw):
    fake_requests(monkeypatch, raw)
    good = Arr().run()
    fake_requests(monkeypatch, raw, lambda app: requests.ConnectionError("refused"))
    bad = Arr().run()
    assert bad["status"] == "error" and bad["consecutive_failures"] == 1
    assert "radarr: connection refused" in bad["error"] and "sonarr: connection refused" in bad["error"]
    assert bad["data"] == good["data"] and bad["updated_at"] == good["updated_at"]


def test_errors_never_leak_urls_or_keys(live, monkeypatch, raw):
    leaky = requests.ConnectionError(f"pool host=radarr.example.invalid {RKEY} {SKEY}")
    fake_requests(monkeypatch, raw, lambda app: leaky if app == "radarr" else 500)
    envelope = Arr().run()
    blob = json.dumps(envelope)
    for secret in (RKEY, SKEY, "example.invalid", "http://"):
        assert secret not in blob
    assert "radarr: connection refused" in envelope["error"] and "sonarr: HTTP 500" in envelope["error"]


def test_live_mode_fails_fast_naming_the_missing_variable(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    for var in Arr.requires_env:
        monkeypatch.delenv(var, raising=False)
    envelope = Arr().run()
    assert envelope["status"] == "error" and "RADARR_URL" in envelope["error"]


def test_rows_carry_poster_refs(data):
    assert data["arrived"][0]["poster"] in ("radarr:1", "sonarr:1")  # movie id / series id
    assert all(r["poster"].split(":")[0] in ("radarr", "sonarr")
               for rows in (data["arrived"], data["updated"], data["this_week"], data["downloading"])
               for r in rows)
    assert {r["title"]: r["poster"] for r in data["downloading"]} == {
        "Midnight Harbour": "radarr:21", "Quiet Coast · S02E04 · Late Tide": "sonarr:1"}
    week = {r["title"]: r["poster"] for r in data["this_week"]}
    assert week["Glass Orchard"] == "radarr:22"
    assert week["Night Ferry · S02E01 · New Moorings"] == "sonarr:2"


def test_item_key_is_tmdb_for_radarr_and_tvdb_for_sonarr(data):
    keys = {r["poster"]: r["item_key"] for section in ("arrived", "updated", "this_week", "downloading")
            for r in data[section]}
    assert keys and all(k.startswith(("tmdb:", "tvdb:")) for k in keys.values())
    assert all(v == f"tmdb:{1000 + int(p.split(':')[1])}" for p, v in keys.items() if p.startswith("radarr:"))
    assert all(v == f"tvdb:{2000 + int(p.split(':')[1])}" for p, v in keys.items() if p.startswith("sonarr:"))


def test_this_week_drops_rows_already_in_just_arrived(data):
    assert "tvdb:2001" in {r["item_key"] for r in data["arrived"]}                     # Quiet Coast S02 arrived this week...
    titles = [r["title"] for r in data["this_week"]]
    assert "Quiet Coast · S02E04 · Late Tide" not in titles  # ...so its airing is not listed twice
    assert "Night Ferry · S02E01 · New Moorings" in titles  # same series, different episode: kept
    assert "Midnight Harbour" in titles                     # unrelated rows stay


def test_one_volume_under_three_mount_paths_is_listed_once(raw):
    raw = copy.deepcopy(raw)
    same = {"label": "", "freeSpace": 500_000_000_000, "totalSpace": 2_000_000_000_000}
    raw["raw_radarr_diskspace"] = [{"path": "/", **same}, {"path": "/config", **same}]
    raw["raw_sonarr_diskspace"] = [{"path": "/data", **same}]
    disk = Arr().transform(raw)["disk"]
    assert [d["path"] for d in disk] == ["/"]               # first path seen wins
    raw["raw_sonarr_diskspace"].append({"path": "/other", **{**same, "freeSpace": 100_000_000_000}})
    assert [d["path"] for d in Arr().transform(raw)["disk"]] == ["/", "/other"]


def test_queue_rows_carry_the_lower_cased_download_id(data, raw):
    movie, episode = data["downloading"]
    assert movie["download_id"] == "abcdefabcdefabcdefabcdefabcdefabcdefabcd"  # fixture is upper-case
    assert episode["download_id"] == "fedcbafedcbafedcbafedcbafedcbafedcbafedc"
    bare = copy.deepcopy(raw)
    for key in ("raw_radarr_queue", "raw_sonarr_queue"):
        for record in bare[key]["records"]:
            record.pop("downloadId")
    assert all(r["download_id"] is None for r in Arr().transform(bare)["downloading"])


def test_arrived_and_updated_rows_carry_an_iso_import_timestamp(data):
    for row in data["arrived"] + data["updated"]:
        assert datetime.fromisoformat(row["at"]).tzinfo is not None
    assert [r["at"] for r in data["arrived"]][0] > [r["at"] for r in data["arrived"]][-1]
