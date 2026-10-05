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
    assert set(raw) == {"raw_users", "raw_sessions", "raw_resume", "raw_nextup",
                        "raw_latest", "raw_counts"}


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
    assert up == [
        {"title": "Dust and Daylight", "kind": "movie", "remaining_text": "31 min left"},
        {"title": "Quiet Coast · S02E05 · Break of Dawn", "kind": "episode",
         "remaining_text": "30 min left"},
        {"title": "Northern Lines · S01E03 · The Understudy", "kind": "episode",
         "remaining_text": "Next episode"},
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
        key = {"/Users": "raw_users", "/Sessions": "raw_sessions",
               "/Shows/NextUp": "raw_nextup", "/Items/Counts": "raw_counts"}.get(path)
        if key is None:
            key = "raw_resume" if path.endswith("/Items/Resume") else "raw_latest"
        return FakeResponse(raw[key])

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Jellyfin().run()

    assert envelope["status"] == "ok", envelope["error"]
    paths = [c[0][len(URL):] for c in calls]
    assert paths == ["/Users", "/Sessions", "/Users/user-fixture-2/Items/Resume",
                     "/Shows/NextUp", "/Users/user-fixture-2/Items/Latest", "/Items/Counts"]
    assert all(c[3] == 10 for c in calls)
    assert all(c[1]["Authorization"] == f"MediaBrowser Token={KEY}" for c in calls)
    assert calls[3][2]["UserId"] == "user-fixture-2"
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
