"""WP22 step 4 — the fixture/live mode switch.

Fixture mode must complete with sockets banned outright and both timestamps
pinned to FIXTURE_TIMESTAMP; live mode must fail fast naming the exact missing
environment variable.
"""

import json
import socket

import pytest

from connectors.base import FIXTURE_TIMESTAMP, Connector


class FileFed(Connector):
    """A connector whose fixture dir the test controls."""

    id = "jellyfin"
    requires_env = ("JELLYFIN_URL", "JELLYFIN_TOKEN")

    def __init__(self, fixtures):
        self._fixtures = fixtures

    @property
    def fixture_dir(self):
        return self._fixtures

    def fetch(self):  # pragma: no cover - live path is never taken here
        raise AssertionError("live fetch must not be attempted")

    def transform(self, raw):
        return {"summary": raw["summary"]}


@pytest.fixture()
def fixture_dir(tmp_path):
    d = tmp_path / "jellyfin"
    d.mkdir()
    (d / "raw.json").write_text(json.dumps({"summary": "2 streaming"}), encoding="utf-8")
    return d


def test_fixture_mode_pins_timestamps_and_opens_no_socket(snapshots, fixture_dir, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("fixture mode opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.delenv("JELLYFIN_URL", raising=False)
    monkeypatch.delenv("JELLYFIN_TOKEN", raising=False)

    envelope = FileFed(fixture_dir).run()

    assert envelope["status"] == "ok"
    assert envelope["fetched_at"] == FIXTURE_TIMESTAMP
    assert envelope["updated_at"] == FIXTURE_TIMESTAMP
    assert envelope["data"] == {"summary": "2 streaming"}


def test_fixture_mode_output_is_byte_reproducible(snapshots, fixture_dir):
    path = snapshots / "jellyfin.json"
    FileFed(fixture_dir).run()
    first = path.read_bytes()
    FileFed(fixture_dir).run()
    assert path.read_bytes() == first


def test_live_mode_missing_credential_names_the_variable(snapshots, fixture_dir, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.delenv("JELLYFIN_URL", raising=False)
    monkeypatch.setenv("JELLYFIN_TOKEN", "not-a-real-value")

    envelope = FileFed(fixture_dir).run()

    assert envelope["status"] == "error"
    assert "JELLYFIN_URL" in envelope["error"]
    assert envelope["consecutive_failures"] == 1


def test_live_is_the_default_mode(snapshots, monkeypatch):
    """The box must never fall into fixture mode by forgetting a variable."""
    from connectors import base

    monkeypatch.delenv("CONNECTOR_MODE", raising=False)
    assert base.mode() == "live"
