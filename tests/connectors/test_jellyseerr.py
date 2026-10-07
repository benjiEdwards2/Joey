"""Media Phase 3 — the Jellyseerr connector: transform off the fixtures (status words,
ordering), the TMDB title cache, the one-failed-lookup rule, and the no-URL/key-leak
guarantee. Live HTTP is always intercepted, so the suite stays offline by construction.
"""

import copy
import json
import socket
from pathlib import Path

import jsonschema
import pytest
import requests

from connectors.stubs import Jellyseerr

URL = "http://seerr.example.invalid:5055"
KEY = "SEERRSECRETkey"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data" / "jellyseerr.schema.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture()
def raw(snapshots):
    return Jellyseerr().fetch_fixture()


@pytest.fixture()
def data(raw):
    out = Jellyseerr().transform(raw)
    jsonschema.validate(out, SCHEMA)
    return out


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("JELLYSEERR_URL", URL + "/")
    monkeypatch.setenv("JELLYSEERR_API_KEY", KEY)
    return snapshots


class Resp:
    def __init__(self, payload=None, code=200):
        self.payload, self.status_code = payload, code

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} for url: {URL}/x")
            err.response = self
            raise err

    def json(self):
        return self.payload


def fake_requests(monkeypatch, raw, fail=None):
    """Answer from the fixture; `fail(path)` may return an exception to raise or a status."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None, **kw):
        path = url[len(URL):]
        calls.append({"path": path, "headers": headers, "params": params, "timeout": timeout})
        outcome = fail(path) if fail else None
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            return Resp(code=outcome)
        if path == "/api/v1/request/count":
            return Resp(raw["raw_count"])
        if path == "/api/v1/request":
            return Resp(raw["raw_requests"])
        kind, tmdb = path.split("/")[-2:]
        return Resp(raw["raw_titles"][f"{kind}:{tmdb}"])

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


def test_requires_env_names_the_url_and_key():
    assert Jellyseerr.requires_env == ("JELLYSEERR_URL", "JELLYSEERR_API_KEY")


def test_fixture_dir_is_count_requests_titles(raw):
    assert set(raw) == {"raw_count", "raw_requests", "raw_titles"}


def test_rows_are_pending_first_then_newest_with_a_status_word(data):
    rows = data["requests"]
    assert [(r["status_text"], r["title"]) for r in rows] == [
        ("Pending", "Midnight Harbour"), ("Approved", "Night Ferry"),
        ("Available", "Desert Crossing"), ("Declined", "Harbour Watch")]
    assert rows[0] == {"id": 13, "kind": "movie", "tmdb_id": 1001, "title": "Midnight Harbour",
                       "year": 2025, "requested_by": "Sample Person", "status_text": "Pending",
                       "when": "1 hour ago", "href": "http://nas.local:5055/movie/1001",
                       "poster": "tmdb:/fixture1001.jpg", "item_key": "tmdb:1001"}
    assert rows[1]["kind"] == "tv" and rows[1]["year"] == 2023
    assert rows[1]["href"] == "http://nas.local:5055/tv/2002"
    assert data["counts"] == {"pending": 1, "approved": 2, "available": 1, "declined": 1, "total": 4}
    assert data["summary"] == "1 pending · 2 approved" and data["secondary"] == "Midnight Harbour"


def test_a_pending_request_sorts_ahead_of_a_newer_approved_one(raw):
    newer = copy.deepcopy(raw)
    newer["raw_requests"]["results"][1]["createdAt"] = "2025-12-01T00:00:00.000Z"  # pending, now oldest
    rows = Jellyseerr().transform(newer)["requests"]
    assert rows[0]["status_text"] == "Pending" and rows[1]["status_text"] == "Approved"


def test_media_status_refines_an_approved_request(raw):
    raw = copy.deepcopy(raw)
    tv = raw["raw_requests"]["results"][0]
    for media_status, word in ((3, "Processing"), (4, "Partly available"), (5, "Available")):
        tv["media"]["status"] = media_status
        rows = Jellyseerr().transform(raw)["requests"]
        assert next(r for r in rows if r["id"] == 14)["status_text"] == word


def test_no_open_requests_summary(raw):
    raw = copy.deepcopy(raw)
    raw["raw_count"] = {"total": 0}
    raw["raw_requests"]["results"] = []
    data = Jellyseerr().transform(raw)
    assert data["summary"] == "No open requests" and data["secondary"] == "" and data["requests"] == []
    jsonschema.validate(data, SCHEMA)


def test_rows_are_capped_at_thirty(raw):
    raw = copy.deepcopy(raw)
    template = raw["raw_requests"]["results"][0]
    raw["raw_requests"]["results"] = [{**template, "id": 100 + i} for i in range(40)]
    assert len(Jellyseerr().transform(raw)["requests"]) == 30


def test_fixture_mode_touches_no_network(snapshots, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used in fixture mode")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(requests, "get", boom)
    envelope = Jellyseerr().run()
    assert envelope["status"] == "ok" and envelope["updated_at"] == "2026-01-01T00:00:00+00:00"


def test_live_run_calls_count_list_and_one_lookup_per_title(live, monkeypatch, raw):
    calls = fake_requests(monkeypatch, raw)
    envelope = Jellyseerr().run()
    assert envelope["status"] == "ok", envelope["error"]
    assert [c["path"] for c in calls] == [
        "/api/v1/request/count", "/api/v1/request", "/api/v1/tv/2002", "/api/v1/movie/1001",
        "/api/v1/movie/1003", "/api/v1/tv/2004"]
    assert all(c["timeout"] == 10 and c["headers"] == {"X-Api-Key": KEY} for c in calls)
    assert calls[1]["params"] == {"take": 50, "skip": 0, "sort": "added", "filter": "all"}
    rows = envelope["data"]["requests"]
    assert rows[0]["href"] == f"{URL}/movie/1001"  # trailing slash on the env var stripped
    jsonschema.validate(envelope["data"], SCHEMA)


def test_titles_from_the_previous_envelope_are_not_looked_up_again(live, monkeypatch, raw):
    fake_requests(monkeypatch, raw)
    Jellyseerr().run()
    calls = fake_requests(monkeypatch, raw)
    envelope = Jellyseerr().run()
    assert [c["path"] for c in calls] == ["/api/v1/request/count", "/api/v1/request"]
    first = envelope["data"]["requests"][0]
    assert (first["title"], first["year"]) == ("Midnight Harbour", 2025)


def test_a_new_request_costs_exactly_one_lookup(live, monkeypatch, raw):
    fake_requests(monkeypatch, raw)
    Jellyseerr().run()
    more = copy.deepcopy(raw)
    more["raw_requests"]["results"].append({
        "id": 15, "status": 1, "type": "movie", "createdAt": "2025-12-31T23:00:00.000Z",
        "media": {"tmdbId": 1005, "mediaType": "movie", "status": 1},
        "requestedBy": {"displayName": "Sample Person"}})
    more["raw_titles"]["movie:1005"] = {"title": "Glass Harbour", "releaseDate": "2013-04-05"}
    calls = fake_requests(monkeypatch, more)
    Jellyseerr().run()
    assert [c["path"] for c in calls][2:] == ["/api/v1/movie/1005"]


def test_one_failed_lookup_leaves_a_tmdb_row_and_the_run_ok(live, monkeypatch, raw):
    fake_requests(monkeypatch, raw, lambda p: 404 if p.endswith("/tv/2002") else None)
    envelope = Jellyseerr().run()
    assert envelope["status"] == "ok" and envelope["consecutive_failures"] == 0
    row = next(r for r in envelope["data"]["requests"] if r["tmdb_id"] == 2002)
    assert row["title"] == "TMDB #2002" and row["year"] is None
    assert any(r["title"] == "Midnight Harbour" for r in envelope["data"]["requests"])
    jsonschema.validate(envelope["data"], SCHEMA)
    # the unresolved row is retried next sweep rather than cached as a title
    calls = fake_requests(monkeypatch, raw)
    Jellyseerr().run()
    assert "/api/v1/tv/2002" in [c["path"] for c in calls]


def test_lookups_are_capped_per_sweep(live, monkeypatch, raw):
    big = copy.deepcopy(raw)
    template = big["raw_requests"]["results"][0]
    big["raw_requests"]["results"] = [
        {**template, "id": 200 + i, "media": {"tmdbId": 5000 + i, "mediaType": "tv", "status": 2}}
        for i in range(25)]
    big["raw_titles"] = {f"tv:{5000 + i}": {"name": f"Show {i}", "firstAirDate": "2020-01-01"}
                         for i in range(25)}
    calls = fake_requests(monkeypatch, big)
    envelope = Jellyseerr().run()
    assert len([c for c in calls if "/tv/" in c["path"]]) == 20
    assert sum(r["title"].startswith("TMDB #") for r in envelope["data"]["requests"]) == 5


def test_count_failure_is_an_error_that_keeps_previous_data(live, monkeypatch, raw):
    fake_requests(monkeypatch, raw)
    good = Jellyseerr().run()
    fake_requests(monkeypatch, raw, lambda p: 500 if p.endswith("/count") else None)
    bad = Jellyseerr().run()
    assert bad["status"] == "error" and "HTTP 500" in bad["error"]
    assert bad["data"] == good["data"] and bad["updated_at"] == good["updated_at"]


def test_errors_never_leak_the_url_or_key(live, monkeypatch, raw):
    leaky = requests.ConnectionError(f"Max retries exceeded for url: {URL} key={KEY}")
    fake_requests(monkeypatch, raw, lambda p: leaky)
    envelope = Jellyseerr().run()
    blob = json.dumps(envelope)
    assert envelope["status"] == "error" and "ConnectionError" in envelope["error"]
    for secret in (KEY, "example.invalid", "http://"):
        assert secret not in blob


def test_a_leaky_lookup_failure_never_reaches_the_snapshot(live, monkeypatch, raw):
    leaky = requests.ConnectionError(f"boom {URL} {KEY}")
    fake_requests(monkeypatch, raw, lambda p: leaky if "/movie/" in p else None)
    blob = json.dumps(Jellyseerr().run())
    assert KEY not in blob and "boom" not in blob  # (row hrefs legitimately carry the base URL)


def test_live_mode_fails_fast_naming_the_missing_variable(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("JELLYSEERR_URL", URL)
    monkeypatch.delenv("JELLYSEERR_API_KEY", raising=False)
    envelope = Jellyseerr().run()
    assert envelope["status"] == "error" and "JELLYSEERR_API_KEY" in envelope["error"]


def test_poster_is_the_lookup_poster_path_or_null(data):
    posters = {r["title"]: r["poster"] for r in data["requests"]}
    assert posters["Night Ferry"] == "tmdb:/fixture2002.jpg"
    assert posters["Harbour Watch"] is None  # the lookup carried no posterPath


def test_item_key_is_the_tmdb_id(data):
    assert all(r["item_key"] == f"tmdb:{r['tmdb_id']}" for r in data["requests"])


def test_tv_rows_carry_the_tvdb_id_for_the_hub_remove(data):
    """Remove (2026-10-08): the hub stops a Sonarr search by TVDB id; films carry no tvdb_id key at all."""
    by_title = {r["title"]: r for r in data["requests"]}
    assert by_title["Night Ferry"]["tvdb_id"] == 82002 and by_title["Harbour Watch"]["tvdb_id"] == 82004
    assert "tvdb_id" not in by_title["Midnight Harbour"] and "tvdb_id" not in by_title["Desert Crossing"]


def test_tv_row_without_a_tvdb_id_is_null(raw):
    raw = copy.deepcopy(raw)
    for r in raw["raw_requests"]["results"]:
        r["media"].pop("tvdbId", None)
    out = Jellyseerr().transform(raw)
    jsonschema.validate(out, SCHEMA)
    assert all(r["tvdb_id"] is None for r in out["requests"] if r["kind"] == "tv")
