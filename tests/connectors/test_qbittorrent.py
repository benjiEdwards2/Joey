"""Media downloads — the qBittorrent connector: transform off the fixtures (counts,
kinds, pct, state words, the finished-24 h boundary, seeding, totals), the 5.x login
(204 + cookie), and the no-URL/password-leak guarantee. Live HTTP is always
intercepted, so the suite stays offline by construction.
"""

import copy
import json
import socket
from pathlib import Path

import jsonschema
import pytest
import requests
from requests.cookies import RequestsCookieJar

from connectors.stubs import QBittorrent, _bytes_text, _eta_text

URL = "http://qbit.example.invalid:8080"
USER = "joeyreader"
PASSWORD = "QBITSECRETpass"
NOW = 1767225600  # the pinned fixture clock, 2026-01-01T00:00:00+00:00
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data" / "qbittorrent.schema.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture()
def raw(snapshots):
    return QBittorrent().fetch_fixture()


@pytest.fixture()
def data(raw):
    out = QBittorrent().transform(raw)
    jsonschema.validate(out, SCHEMA)
    return out


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("QBIT_URL", URL + "/")
    monkeypatch.setenv("QBIT_USER", USER)
    monkeypatch.setenv("QBIT_PASS", PASSWORD)
    return snapshots


class Resp:
    def __init__(self, payload=None, code=200, text=""):
        self.payload, self.status_code, self.text = payload, code, text

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} for url: {URL}/x")
            err.response = self
            raise err

    def json(self):
        return self.payload


def fake_session(monkeypatch, raw, login=(204, "QBT_SID"), fail=None):
    """A requests.Session stand-in. `login` = (status, cookie name or None);
    `fail(path)` may return an exception to raise or an HTTP status."""
    calls = []

    class FakeSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()

        def post(self, url, data=None, headers=None, timeout=None, **kw):
            path = url[len(URL):]
            calls.append({"method": "POST", "path": path, "data": data, "headers": headers, "timeout": timeout})
            outcome = fail(path) if fail else None
            if isinstance(outcome, Exception):
                raise outcome
            status, cookie = login
            if cookie:
                self.cookies.set(cookie, "fakesid")
            return Resp(code=status, text="" if status == 204 else "Fails.")

        def get(self, url, timeout=None, **kw):
            path = url[len(URL):]
            calls.append({"method": "GET", "path": path, "timeout": timeout})
            outcome = fail(path) if fail else None
            if isinstance(outcome, Exception):
                raise outcome
            if outcome:
                return Resp(code=outcome)
            return Resp(raw["raw_torrents"] if path.endswith("/torrents/info") else raw["raw_transfer"])

        def close(self):
            pass

    monkeypatch.setattr(requests, "Session", FakeSession)
    return calls


# ---- transform -------------------------------------------------------------

def test_requires_env_names_url_user_and_password():
    assert QBittorrent.requires_env == ("QBIT_URL", "QBIT_USER", "QBIT_PASS")


def test_fixture_dir_is_torrents_and_transfer(raw):
    assert set(raw) == {"raw_torrents", "raw_transfer"}


def test_active_rows_are_speed_first_then_progress(data):
    rows = data["active"]
    assert [(r["name"], r["state_text"]) for r in rows] == [
        ("Example.Show.S02E03.1080p", "Downloading"),
        ("Example.Movie.2024.2160p.WEB-DL", "Downloading"),
        ("Fixture.Distro.Image.x64", "Paused"),
        ("Sample.Series.S01E07.720p", "Stalled"),
    ]
    assert rows[1] == {
        "hash": "abcdefabcdefabcdefabcdefabcdefabcdefabcd", "name": "Example.Movie.2024.2160p.WEB-DL",
        "kind": "movie", "category": "radarr", "pct": 42, "state_text": "Downloading",
        "speed_text": "1.4 MB/s", "eta_text": "12 min", "size_text": "4.2 GB",
        "added": "2025-12-31T23:00:00+00:00"}


def test_kinds_categories_pct_and_blank_texts(data):
    by_name = {r["name"]: r for r in data["active"]}
    show = by_name["Example.Show.S02E03.1080p"]
    assert (show["kind"], show["pct"], show["speed_text"], show["eta_text"]) == ("tv", 81, "230 kB/s", "2 h 05 min")
    paused = by_name["Fixture.Distro.Image.x64"]
    assert (paused["kind"], paused["category"], paused["speed_text"], paused["eta_text"]) == ("other", "", "", "")
    stalled = by_name["Sample.Series.S01E07.720p"]
    assert (stalled["eta_text"], stalled["size_text"]) == ("", "900 MB")  # 8640000 = infinite


def test_hashes_are_lower_case(data):
    assert all(r["hash"] == r["hash"].lower() for r in data["active"] + data["finished"])
    assert "acebdfacebdfacebdfacebdfacebdfacebdfaceb" in {r["hash"] for r in data["active"]}


def test_finished_is_the_last_24_hours_only(data):
    assert data["finished"] == [{
        "hash": "0987654321098765432109876543210987654321", "name": "Placeholder.Film.2023.1080p.BluRay",
        "kind": "movie", "size_text": "9.8 GB", "when": "2025-12-31T22:00:00+00:00"}]


def test_finished_boundary_and_newest_first(raw):
    raw = copy.deepcopy(raw)
    old = raw["raw_torrents"][5]
    old["completion_on"] = NOW - 86400          # exactly 24 h ago -> still today
    finished = QBittorrent().transform(raw)["finished"]
    assert [f["name"] for f in finished] == ["Placeholder.Film.2023.1080p.BluRay", "Example.Show.S02E01.1080p"]
    old["completion_on"] = NOW - 86401          # one second older -> gone
    assert len(QBittorrent().transform(raw)["finished"]) == 1


def test_seeding_count_and_totals(data):
    assert data["seeding"] == 2
    assert data["totals"] == {"dl_bps": 1630000, "up_bps": 230000, "dl_text": "1.6 MB/s", "up_text": "230 kB/s"}


def test_summary_and_secondary(data):
    assert data["summary"] == "4 downloading · 1.6 MB/s"
    assert data["secondary"] == "2 seeding · 1 finished today"


def test_idle_client_wording(raw):
    raw = copy.deepcopy(raw)
    raw["raw_torrents"] = [t for t in raw["raw_torrents"] if t["state"] == "stalledUP"]
    raw["raw_transfer"]["dl_info_speed"] = 0
    data = QBittorrent().transform(raw)
    assert data["summary"] == "Nothing downloading" and data["active"] == []
    assert data["secondary"] == "1 seeding · Nothing finished today"
    raw["raw_torrents"] = []
    assert QBittorrent().transform(raw)["secondary"] == "Nothing finished today"
    jsonschema.validate(data, SCHEMA)


def test_summary_drops_the_speed_when_zero(raw):
    raw = copy.deepcopy(raw)
    raw["raw_transfer"]["dl_info_speed"] = 0
    assert QBittorrent().transform(raw)["summary"] == "4 downloading"


def test_every_download_state_has_a_word(raw):
    raw = copy.deepcopy(raw)
    template = raw["raw_torrents"][0]
    states = {"downloading": "Downloading", "stalledDL": "Stalled", "metaDL": "Fetching metadata",
              "pausedDL": "Paused", "stoppedDL": "Paused", "queuedDL": "Queued", "forcedDL": "Downloading",
              "checkingDL": "Checking", "allocating": "Allocating"}
    raw["raw_torrents"] = [{**template, "state": s, "name": s} for s in states]
    rows = QBittorrent().transform(raw)["active"]
    assert {r["name"]: r["state_text"] for r in rows} == states
    assert all(r["eta_text"] == "" for r in rows if r["state_text"] == "Paused")


def test_kind_rules():
    from connectors.stubs import _qbit_kind
    assert [_qbit_kind(c) for c in ("radarr", "Movies", "tv-sonarr", "TV", "", None, "music")] == \
        ["movie", "movie", "tv", "tv", "other", "other", "other"]


def test_rows_are_capped_at_twenty(raw):
    raw = copy.deepcopy(raw)
    template = raw["raw_torrents"][0]
    raw["raw_torrents"] = [{**template, "completion_on": NOW - 60} for _ in range(30)]
    data = QBittorrent().transform(raw)
    assert len(data["active"]) == 20 and len(data["finished"]) == 20
    assert data["summary"].startswith("30 downloading")
    jsonschema.validate(data, SCHEMA)


def test_bytes_and_eta_helpers():
    assert [_bytes_text(n) for n in (0, 999, 230000, 1400000, 900000000, 4200000000, 123400000000)] == \
        ["0 B", "999 B", "230 kB", "1.4 MB", "900 MB", "4.2 GB", "123 GB"]
    assert [_eta_text(s) for s in (720, 7500, 30, 0, -1, 8640000, None)] == \
        ["12 min", "2 h 05 min", "1 min", "", "", "", ""]


# ---- fetch -----------------------------------------------------------------

def test_fixture_mode_touches_no_network(snapshots, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used in fixture mode")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(requests, "Session", boom)
    envelope = QBittorrent().run()
    assert envelope["status"] == "ok" and envelope["updated_at"] == "2026-01-01T00:00:00+00:00"


def test_live_login_204_with_cookie_then_two_reads(live, monkeypatch, raw):
    calls = fake_session(monkeypatch, raw)
    envelope = QBittorrent().run()
    assert envelope["status"] == "ok", envelope["error"]
    assert [(c["method"], c["path"]) for c in calls] == [
        ("POST", "/api/v2/auth/login"), ("GET", "/api/v2/torrents/info"), ("GET", "/api/v2/transfer/info")]
    login = calls[0]
    assert login["data"] == {"username": USER, "password": PASSWORD}
    assert login["headers"] == {"Referer": URL}  # trailing slash on the env var stripped
    assert all(c["timeout"] == 10 for c in calls)
    jsonschema.validate(envelope["data"], SCHEMA)
    assert envelope["data"]["summary"] == "4 downloading · 1.6 MB/s"


def test_older_sid_cookie_name_is_accepted(live, monkeypatch, raw):
    fake_session(monkeypatch, raw, login=(200, "SID"))
    assert QBittorrent().run()["status"] == "ok"


def test_login_403_is_refused_without_leaking(live, monkeypatch, raw):
    calls = fake_session(monkeypatch, raw, login=(403, None))
    envelope = QBittorrent().run()
    assert envelope["status"] == "error" and "login refused" in envelope["error"]
    assert [c["method"] for c in calls] == ["POST"]  # never reads after a refusal
    blob = json.dumps(envelope)
    for secret in (PASSWORD, USER, "example.invalid", "http://"):
        assert secret not in blob


def test_login_200_without_a_cookie_is_refused(live, monkeypatch, raw):
    fake_session(monkeypatch, raw, login=(200, None))  # the "Fails." answer
    envelope = QBittorrent().run()
    assert envelope["status"] == "error" and "login refused" in envelope["error"]


def test_connection_error_is_sanitised(live, monkeypatch, raw):
    leaky = requests.ConnectionError(f"Max retries exceeded for url: {URL} password={PASSWORD}")
    fake_session(monkeypatch, raw, fail=lambda p: leaky)
    envelope = QBittorrent().run()
    assert envelope["status"] == "error"
    assert "connection refused" in envelope["error"] and "login" in envelope["error"]
    blob = json.dumps(envelope)
    for secret in (PASSWORD, "example.invalid", "http://", "Max retries"):
        assert secret not in blob


def test_read_failure_keeps_previous_data(live, monkeypatch, raw):
    fake_session(monkeypatch, raw)
    good = QBittorrent().run()
    fake_session(monkeypatch, raw, fail=lambda p: 500 if p.endswith("/transfer/info") else None)
    bad = QBittorrent().run()
    assert bad["status"] == "error" and "transfer" in bad["error"] and "HTTP 500" in bad["error"]
    assert bad["data"] == good["data"] and bad["updated_at"] == good["updated_at"]


def test_live_mode_fails_fast_naming_the_missing_variable(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("QBIT_URL", URL)
    monkeypatch.setenv("QBIT_USER", USER)
    monkeypatch.delenv("QBIT_PASS", raising=False)
    envelope = QBittorrent().run()
    assert envelope["status"] == "error" and "QBIT_PASS" in envelope["error"]
