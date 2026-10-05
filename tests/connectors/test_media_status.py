"""Media Phase 1 — the app-health connector. Down is data, never a failed run."""

import json
from pathlib import Path

import jsonschema
import pytest
import requests

from connectors.stubs import MEDIA_APPS, MediaStatus

HOST = "10.9.9.9"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data" / "media_status.schema.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture()
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("MEDIA_STATUS_HOST", HOST)
    return snapshots


class Resp:
    def __init__(self, code):
        self.status_code = code


def run_with(monkeypatch, behaviour):
    """behaviour(port) -> status code, or an exception instance to raise."""
    def fake_get(url, timeout=None, **kw):
        assert timeout == 5 and url.startswith(f"http://{HOST}:")
        outcome = behaviour(int(url.split(":")[2].split("/")[0]))
        if isinstance(outcome, Exception):
            raise outcome
        return Resp(outcome)

    monkeypatch.setattr(requests, "get", fake_get)
    return MediaStatus().run()


def test_requires_only_the_host():
    assert MediaStatus.requires_env == ("MEDIA_STATUS_HOST",)


def test_all_up(live, monkeypatch):
    envelope = run_with(monkeypatch, lambda port: 200)
    data = envelope["data"]
    assert envelope["status"] == "ok"
    assert data["summary"] == "8 of 8 up" and data["secondary"] == "All apps up"
    assert all(a["status_text"] == "Up" and a["note"] is None for a in data["apps"])
    assert data["apps"][0]["href"] == f"http://{HOST}:8096"
    jsonschema.validate(data, SCHEMA)


def test_one_down_by_timeout_keeps_the_run_ok(live, monkeypatch):
    prowlarr = next(a["port"] for a in MEDIA_APPS if a["id"] == "prowlarr")
    envelope = run_with(
        monkeypatch,
        lambda port: requests.Timeout(f"timed out http://{HOST}:{port}") if port == prowlarr else 200,
    )
    data = envelope["data"]
    assert envelope["status"] == "ok" and envelope["consecutive_failures"] == 0
    assert data["summary"] == "7 of 8 up" and data["secondary"] == "Down: Prowlarr"
    down = [a for a in data["apps"] if not a["up"]]
    assert [(a["name"], a["status_text"], a["note"]) for a in down] == [("Prowlarr", "Down", "timeout")]
    jsonschema.validate(data, SCHEMA)


def test_connection_refused_and_5xx_notes(live, monkeypatch):
    def behaviour(port):
        if port == 7878:
            return requests.ConnectionError(f"refused {HOST}:{port}")
        if port == 8989:
            return 502
        return 200

    data = run_with(monkeypatch, behaviour)["data"]
    notes = {a["name"]: a["note"] for a in data["apps"] if not a["up"]}
    assert notes == {"Radarr": "connection refused", "Sonarr": "HTTP 502"}


def test_401_counts_as_up(live, monkeypatch):
    data = run_with(monkeypatch, lambda port: 401)["data"]
    assert data["summary"] == "8 of 8 up"


def test_notes_never_contain_a_url_or_host(live, monkeypatch):
    envelope = run_with(monkeypatch, lambda port: RuntimeError(f"boom http://{HOST}:{port}/x"))
    notes = [a["note"] for a in envelope["data"]["apps"]]
    assert notes == ["RuntimeError"] * 8


def test_fixture_mode_never_touches_the_network(snapshots, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("fixture mode must not probe the network")

    monkeypatch.setattr(requests, "get", boom)
    envelope = MediaStatus().run()
    assert envelope["status"] == "ok"
    assert envelope["data"]["summary"] == "7 of 8 up"
    assert envelope["data"]["apps"][4]["note"] == "timeout"


def test_live_mode_without_host_fails_naming_the_variable(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.delenv("MEDIA_STATUS_HOST", raising=False)
    envelope = MediaStatus().run()
    assert envelope["status"] == "error" and "MEDIA_STATUS_HOST" in envelope["error"]
