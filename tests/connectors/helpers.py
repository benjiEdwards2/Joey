"""Shared helpers for the connector tests (W3 tests, T-03, 2026-10-09): the Radarr/Sonarr (`arr`) constants, fake
response, `fake_requests` and the `raw` / `live` fixtures that test_arr and test_arr_counts both use. test_arr
re-exports them, so `from tests.connectors.test_arr import ...` keeps working."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from connectors.stubs import Arr

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
def live(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    monkeypatch.setenv("RADARR_URL", RADARR + "/")
    monkeypatch.setenv("RADARR_API_KEY", RKEY)
    monkeypatch.setenv("SONARR_URL", SONARR)
    monkeypatch.setenv("SONARR_API_KEY", SKEY)
    # live mode reads the real clock; pin it so the fixture dates stay in the window
    monkeypatch.setattr("connectors.feeds.arr._now", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
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
