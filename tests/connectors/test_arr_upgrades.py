"""F4a (2026-10-12): "upgrade available" — the arr feed's `upgrades` block, the titles whose file
on disk is below the quality profile's cutoff (Radarr/Sonarr "cutoff unmet"). Transform off the
fixtures (Sonarr grouping, totals, quality names, profile-cutoff `want`), the partial-ok rule when
a cutoff or profile call fails, and the no-URL/key-leak guarantee."""

import copy
import json

import jsonschema
import requests

from connectors.stubs import Arr
from tests.connectors.helpers import RADARR, RKEY, SCHEMA, SKEY, SONARR, fake_requests
from tests.connectors.helpers import live, raw  # noqa: F401  (fixtures)


def failing(monkeypatch, raw, suffix, app=None, outcome=None):
    """fake_requests, but calls whose URL ends with `suffix` (for `app`, or both) fail."""
    calls = fake_requests(monkeypatch, raw)
    arr_get = requests.get
    base = {"radarr": RADARR, "sonarr": SONARR}.get(app, "")

    def get(url, **kw):
        if url.endswith(suffix) and url.startswith(base):
            raise outcome or requests.ConnectTimeout(f"{url} {RKEY} {SKEY}")
        return arr_get(url, **kw)
    monkeypatch.setattr(requests, "get", get)
    return calls


def test_radarr_rows_name_the_held_quality_and_the_profile_cutoff(raw):
    data = Arr().transform(raw)
    jsonschema.validate(data, SCHEMA)
    rows = data["upgrades"]["radarr"]
    assert [r["title"] for r in rows] == ["Copper Sky", "Desert Crossing", "Harbour Lights"]  # by title
    assert rows[2] == {"item_key": "tmdb:1001", "title": "Harbour Lights", "year": 2025, "arr_id": 1,
                       "have": "WEBDL-720p", "want": "Bluray-1080p", "poster": "radarr:1"}
    assert rows[1]["want"] == "Bluray + Remux 2160p"  # the cutoff is a quality group: its name
    assert rows[0]["want"] is None                    # profile 9 is not in the profile list
    assert rows[0]["have"] is None                    # Copper Sky is not in the movie list


def test_radarr_have_joins_the_movie_list_and_falls_back_to_the_records_own_file(raw):
    # live Radarr 6.4 cutoff records carry movieFileId, never movieFile
    assert not any("movieFile" in m for m in raw["raw_radarr_cutoff"]["records"])
    raw = copy.deepcopy(raw)
    raw["raw_radarr_cutoff"]["records"][0]["movieFile"] = {"quality": {"quality": {"name": "DVD"}}}
    rows = Arr().transform(raw)["upgrades"]["radarr"]
    assert [r["have"] for r in rows] == ["DVD", "Bluray-1080p", "WEBDL-720p"]
    del raw["raw_radarr_movie"]  # the count call failed: no join, the own file still counts
    assert [r["have"] for r in Arr().transform(raw)["upgrades"]["radarr"]] == ["DVD", None, None]


def test_sonarr_episodes_group_per_series_with_the_lowest_quality(raw):
    rows = Arr().transform(raw)["upgrades"]["sonarr"]
    assert [r["title"] for r in rows] == ["Iron Valley", "Quiet Coast"]
    assert rows[1] == {"item_key": "tvdb:2001", "title": "Quiet Coast", "arr_id": 1, "episodes": 3,
                       "have": "SDTV", "want": "WEB 1080p", "sample": "S01E02", "poster": "sonarr:1"}
    assert (rows[0]["episodes"], rows[0]["have"], rows[0]["want"]) == (1, "WEBDL-720p", "Bluray-1080p")


def test_totals_and_counts_use_total_records_not_the_page(raw):
    data = Arr().transform(raw)
    assert data["upgrades"]["totals"] == {"movies": 3, "episodes": 4, "series": 2}
    big = copy.deepcopy(raw)
    big["raw_radarr_cutoff"]["totalRecords"] = 250  # more than the one page fetched
    data = Arr().transform(big)
    assert data["upgrades"]["totals"]["movies"] == 250 and data["radarr"]["upgrades"] == 250
    assert len(data["upgrades"]["radarr"]) == 3


def test_missing_profiles_or_files_leave_want_and_have_null(raw):
    bare = copy.deepcopy(raw)
    del bare["raw_radarr_qualityprofile"], bare["raw_sonarr_qualityprofile"]
    bare["raw_radarr_movie"][0].pop("movieFile")
    data = Arr().transform(bare)
    jsonschema.validate(data, SCHEMA)
    assert all(r["want"] is None for app in ("radarr", "sonarr") for r in data["upgrades"][app])
    assert data["upgrades"]["radarr"][2]["have"] is None  # Harbour Lights: no file in the list


def test_no_cutoff_payload_means_null_lists_and_no_upgrades_count(raw):
    old = {k: v for k, v in raw.items() if "cutoff" not in k and "qualityprofile" not in k}
    data = Arr().transform(old)
    jsonschema.validate(data, SCHEMA)
    assert data["upgrades"] == {"radarr": None, "sonarr": None,
                                "totals": {"movies": 0, "episodes": 0, "series": 0}}
    assert "upgrades" not in data["radarr"] and "upgrades" not in data["sonarr"]


def test_old_envelopes_without_upgrades_stay_valid(raw):
    data = Arr().transform(raw)
    data.pop("upgrades")
    data["radarr"].pop("upgrades")
    data["sonarr"].pop("upgrades")
    jsonschema.validate(data, SCHEMA)


def test_live_cutoff_calls_are_one_cheap_page_sorted_by_title(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw)
    data = Arr().run()["data"]
    cut = {c["app"]: c for c in calls if c["url"].endswith("/api/v3/wanted/cutoff")}
    assert cut["radarr"]["url"] == f"{RADARR}/api/v3/wanted/cutoff"
    for c in cut.values():
        assert c["params"]["page"] == 1 and c["params"]["pageSize"] == 100
        assert c["params"]["monitored"] == "true" and c["params"]["sortDirection"] == "ascending"
        assert c["timeout"] == 10
    assert cut["radarr"]["params"]["sortKey"] == "movieMetadata.sortTitle"
    assert cut["sonarr"]["params"]["sortKey"] == "series.sortTitle"
    assert cut["sonarr"]["params"]["includeSeries"] == cut["sonarr"]["params"]["includeEpisodeFile"] == "true"
    assert cut["radarr"]["headers"] == {"X-Api-Key": RKEY} and cut["sonarr"]["headers"] == {"X-Api-Key": SKEY}
    assert sum(c["url"].endswith("/api/v3/qualityprofile") for c in calls) == 2
    assert data["upgrades"]["totals"] == {"movies": 3, "episodes": 4, "series": 2}


def test_a_failed_cutoff_call_nulls_only_that_app_and_is_noted(live, monkeypatch, raw):
    calls = failing(monkeypatch, raw, "/wanted/cutoff", app="sonarr")
    envelope = Arr().run()
    data = envelope["data"]
    assert envelope["status"] == "ok" and "app_errors" not in data
    assert data["partial_errors"] == {"sonarr_upgrades": "timeout"}
    assert data["upgrades"]["sonarr"] is None and len(data["upgrades"]["radarr"]) == 3
    assert data["upgrades"]["totals"] == {"movies": 3, "episodes": 0, "series": 0}
    assert "upgrades" not in data["sonarr"] and data["sonarr"]["series"] == 3  # counts otherwise intact
    assert not any(c["app"] == "sonarr" and c["url"].endswith("/qualityprofile") for c in calls)
    jsonschema.validate(data, SCHEMA)
    blob = json.dumps(envelope)
    for secret in (RKEY, SKEY, "example.invalid", "http://"):
        assert secret not in blob


def test_a_failed_profile_call_only_nulls_want(live, monkeypatch, raw):
    failing(monkeypatch, raw, "/qualityprofile", outcome=requests.ConnectionError("refused"))
    envelope = Arr().run()
    data = envelope["data"]
    assert envelope["status"] == "ok" and "partial_errors" not in data
    rows = data["upgrades"]["radarr"] + data["upgrades"]["sonarr"]
    assert len(rows) == 5 and all(r["want"] is None for r in rows) and sum(1 for r in rows if r["have"]) == 4
    jsonschema.validate(data, SCHEMA)


def test_an_app_down_fetches_no_upgrades_for_it(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw,
                          lambda app: requests.ConnectTimeout("t") if app == "radarr" else None)
    data = Arr().run()["data"]
    assert data["upgrades"]["radarr"] is None and data["upgrades"]["sonarr"]
    assert data["partial_errors"] == {"radarr": "timeout"}  # the app error only, no extra upgrades note
    assert not any(c["app"] == "radarr" and "cutoff" in c["url"] for c in calls)


def test_fixture_mode_upgrades_are_byte_stable(snapshots):
    first = json.dumps(Arr().run()["data"]["upgrades"], sort_keys=True)
    assert json.dumps(Arr().run()["data"]["upgrades"], sort_keys=True) == first
