"""WP-S3 (2026-10-06): Radarr/Sonarr library counts and Prowlarr indexer stats on
the `arr` feed. All three objects are partial-ok: a failed count call or missing
Prowlarr env nulls that object only — the rest of arr (and the run) stays ok."""

import json

import jsonschema
import pytest
import requests

from connectors.stubs import Arr
from tests.connectors.helpers import RADARR, SCHEMA, SKEY, SONARR, Resp, fake_requests
from tests.connectors.helpers import live, raw  # noqa: F401  (fixtures)

PROWLARR, PKEY = "http://prowlarr.example.invalid:9696", "PROWLARRSECRETkey"


def with_prowlarr(monkeypatch, fixtures, outcome=None):
    """fake_requests for radarr/sonarr, plus a Prowlarr answer (or exception/status)."""
    calls = fake_requests(monkeypatch, fixtures)
    arr_get = requests.get

    def get(url, headers=None, params=None, timeout=None, **kw):
        if url.startswith(PROWLARR):
            calls.append({"app": "prowlarr", "url": url, "headers": headers, "timeout": timeout})
            if isinstance(outcome, Exception):
                raise outcome
            return Resp(code=outcome) if outcome else Resp(fixtures["raw_prowlarr_indexerstats"])
        return arr_get(url, headers=headers, params=params, timeout=timeout, **kw)
    monkeypatch.setattr(requests, "get", get)
    return calls


def test_fixture_counts(raw):
    data = Arr().transform(raw)
    jsonschema.validate(data, SCHEMA)
    # 6 movies: 3 monitored without a file (missing), 2 of those released (wanted), 1 queued — Homepage semantics
    assert data["radarr"] == {"movies": 6, "wanted": 2, "missing": 3, "queued": 1, "upgrades": 3}
    assert data["sonarr"] == {"series": 3, "wanted": 7, "queued": 1, "upgrades": 4}  # F4a: cutoff unmet


def test_prowlarr_stats_are_summed_across_indexers(raw):
    assert Arr().transform(raw)["prowlarr"] == {
        "grabs": 40, "queries": 1325, "failed_grabs": 3, "failed_queries": 52, "indexers": 3}
    stats = {"indexers": [{"indexerId": 9, "numberOfGrabs": None}]}  # nulls count as 0
    assert Arr().transform({**raw, "raw_prowlarr_indexerstats": stats})["prowlarr"] == {
        "grabs": 0, "queries": 0, "failed_grabs": 0, "failed_queries": 0, "indexers": 1}


def test_live_count_calls_use_the_paged_wanted_endpoint(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw)
    data = Arr().run()["data"]
    movie = next(c for c in calls if c["url"] == f"{RADARR}/api/v3/movie")
    wanted = next(c for c in calls if c["url"] == f"{SONARR}/api/v3/wanted/missing")
    assert movie["timeout"] == wanted["timeout"] == 10
    assert wanted["params"]["pageSize"] == 1 and wanted["headers"] == {"X-Api-Key": SKEY}
    assert sum(c["url"].endswith("/queue") for c in calls) == 2  # queued reuses the feed's queue call
    assert data["radarr"]["queued"] == 1 and data["sonarr"] == {"series": 3, "wanted": 7, "queued": 1, "upgrades": 4}


def test_prowlarr_env_absent_is_null_and_the_run_stays_ok(live, monkeypatch, raw):
    monkeypatch.delenv("PROWLARR_URL", raising=False)
    monkeypatch.delenv("PROWLARR_API_KEY", raising=False)
    calls = fake_requests(monkeypatch, raw)
    envelope = Arr().run()
    assert envelope["status"] == "ok" and envelope["data"]["prowlarr"] is None
    assert envelope["data"]["radarr"] and envelope["data"]["sonarr"]
    assert not any("prowlarr" in c["url"] for c in calls)
    jsonschema.validate(envelope["data"], SCHEMA)


def test_prowlarr_live_call_is_keyed_and_summed(live, monkeypatch, raw):
    monkeypatch.setenv("PROWLARR_URL", PROWLARR + "/")
    monkeypatch.setenv("PROWLARR_API_KEY", PKEY)
    calls = with_prowlarr(monkeypatch, raw)
    data = Arr().run()["data"]
    call = next(c for c in calls if c["app"] == "prowlarr")
    assert call["url"] == f"{PROWLARR}/api/v1/indexerstats"
    assert call["headers"] == {"X-Api-Key": PKEY} and call["timeout"] == 10
    assert data["prowlarr"]["grabs"] == 40 and data["prowlarr"]["indexers"] == 3


@pytest.mark.parametrize("outcome", [500, requests.ConnectionError(f"{PROWLARR} {PKEY}")])
def test_prowlarr_failure_is_null_never_leaked(live, monkeypatch, raw, outcome):
    monkeypatch.setenv("PROWLARR_URL", PROWLARR)
    monkeypatch.setenv("PROWLARR_API_KEY", PKEY)
    with_prowlarr(monkeypatch, raw, outcome)
    envelope = Arr().run()
    assert envelope["status"] == "ok" and envelope["data"]["prowlarr"] is None
    assert envelope["data"]["radarr"] is not None and "app_errors" not in envelope["data"]
    blob = json.dumps(envelope)
    assert PKEY not in blob and "example.invalid" not in blob


def test_a_failed_count_call_nulls_only_that_app(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw)
    arr_get = requests.get

    def get(url, **kw):
        if url.endswith("/wanted/missing"):
            raise requests.ConnectTimeout(f"{SONARR} {SKEY}")
        return arr_get(url, **kw)
    monkeypatch.setattr(requests, "get", get)
    envelope = Arr().run()
    data = envelope["data"]
    assert envelope["status"] == "ok" and "app_errors" not in data
    assert data["sonarr"] is None and data["radarr"] == {"movies": 6, "wanted": 2, "missing": 3, "queued": 1, "upgrades": 3}
    assert data["downloading"] and data["arrived"]  # the feed itself is untouched
    jsonschema.validate(data, SCHEMA)
    assert len(calls) == 14 and SKEY not in json.dumps(envelope)


def test_an_app_down_means_its_counts_are_null_and_not_fetched(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw,
                          lambda app: requests.ConnectTimeout("t") if app == "sonarr" else None)
    data = Arr().run()["data"]
    assert data["sonarr"] is None and data["radarr"]["movies"] == 6
    assert sum(1 for c in calls if c["app"] == "sonarr") == 1  # stopped at the first failing call


def test_old_envelopes_without_counts_stay_valid(raw):
    data = Arr().transform(raw)
    for key in ("radarr", "sonarr", "prowlarr"):
        data.pop(key)
    jsonschema.validate(data, SCHEMA)
