"""WP25 — the real calendar connector: live fetch shape, partial tolerance,
and the no-URL-leak guarantee.

The live HTTP calls are proven on the NAS (WP25 step 3); here every fetch is
intercepted so the suite stays offline by construction. The clock is pinned to
the fixture timestamp so recurrence expansion is deterministic.
"""

import json
from pathlib import Path

import jsonschema
import pytest
import requests

import connectors.feeds._common
from connectors.base import FIXTURE_TIMESTAMP
from connectors.stubs import Gcal

# Fake secrets — if either string ever appears in an envelope, we leaked.
URL_YOU = "https://calendar.example.invalid/secret-you/basic.ics"
URL_HER = "https://outlook.example.invalid/secret-her/calendar.ics"

GCAL_DATA_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data" / "gcal.schema.json")
    .read_text(encoding="utf-8")
)


@pytest.fixture()
def live(snapshots, monkeypatch):
    """Live mode with fake ICS URLs and the stub clock pinned for determinism."""
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("ICS_URL_YOU", URL_YOU)
    monkeypatch.setenv("ICS_URL_HER", URL_HER)
    monkeypatch.setattr(connectors.feeds._common, "_now_iso", lambda: FIXTURE_TIMESTAMP)
    return snapshots


def _fixture_text(name: str) -> str:
    return (Gcal().fixture_dir / name).read_text(encoding="utf-8")


class FakeOk:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class Fake404:
    status_code = 404

    def raise_for_status(self):
        raise requests.HTTPError("404 for url: SECRET", response=self)


def test_live_fetch_gets_both_feeds_with_timeouts(live, monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append((url, timeout))
        return FakeOk(_fixture_text("raw_you.ics" if url == URL_YOU else "raw_her.ics"))

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Gcal().run()

    assert calls == [(URL_YOU, 10), (URL_HER, 10)]
    assert envelope["status"] == "ok"
    owners = {e["owner"] for e in envelope["data"]["events"]}
    assert owners == {"you", "her"}
    assert "feed_errors" not in envelope["data"]


def test_one_feed_down_keeps_the_other_owner(live, monkeypatch):
    def fake_get(url, timeout=None):
        if url == URL_HER:
            raise requests.Timeout(f"timed out for url: {URL_HER}")
        return FakeOk(_fixture_text("raw_you.ics"))

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Gcal().run()

    assert envelope["status"] == "ok"  # partial result, per the WP25 plan
    events = envelope["data"]["events"]
    assert events and {e["owner"] for e in events} == {"you"}
    assert envelope["data"]["feed_errors"] == {"her": "timeout"}  # one sanitiser for every feed (C-05)
    assert envelope["data"]["partial_errors"] == {"her": "timeout"}  # C-10, alongside feed_errors
    assert "her feed down" in envelope["data"]["secondary"]
    jsonschema.Draft202012Validator(GCAL_DATA_SCHEMA).validate(envelope["data"])


def test_http_failure_reason_is_the_status_code(live, monkeypatch):
    def fake_get(url, timeout=None):
        if url == URL_HER:
            return Fake404()
        return FakeOk(_fixture_text("raw_you.ics"))

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Gcal().run()
    assert envelope["data"]["feed_errors"] == {"her": "HTTP 404"}


def test_both_feeds_down_is_an_error_that_never_leaks_a_url(live, monkeypatch):
    def fake_get(url, timeout=None):
        raise requests.ConnectionError(f"Max retries exceeded for url: {url}")

    monkeypatch.setattr(requests, "get", fake_get)
    envelope = Gcal().run()

    assert envelope["status"] == "error"
    assert "you" in envelope["error"] and "her" in envelope["error"]
    dumped = json.dumps(envelope)
    assert "example.invalid" not in dumped
    assert "SECRET" not in dumped


def test_live_mode_without_urls_fails_naming_the_variable(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.delenv("ICS_URL_YOU", raising=False)
    monkeypatch.delenv("ICS_URL_HER", raising=False)
    envelope = Gcal().run()
    assert envelope["status"] == "error"
    assert "ICS_URL_YOU" in envelope["error"]
