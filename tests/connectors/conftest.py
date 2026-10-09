"""Shared helpers for the connector tests (WP22).

Every test here runs offline by construction: no connector under test performs
a real fetch, and `test_mode.py` proves the fixture path with sockets banned.
"""

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENVELOPE_SCHEMA_PATH = REPO_ROOT / "connectors" / "schema" / "envelope.schema.json"


@pytest.fixture(scope="session")
def envelope_schema() -> dict:
    return json.loads(ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def validate_envelope(envelope_schema):
    validator = jsonschema.Draft202012Validator(envelope_schema)

    def _validate(envelope: dict) -> None:
        validator.validate(envelope)

    return _validate


@pytest.fixture(autouse=True)
def _session_calls_reach_patched_requests(monkeypatch):
    """Feeds make their calls on one `requests.Session` per run (C-05). Most tests here
    intercept the module-level `requests.get` / `requests.post`; this stand-in Session routes
    to whatever those are at call time, so the interception keeps covering every call. A test
    that patches `requests.Session` itself (qBittorrent, test_http_session) overrides it."""
    import requests
    from requests.cookies import RequestsCookieJar

    class RoutedSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()

        def get(self, url, **kw):
            return requests.get(url, **kw)

        def post(self, url, **kw):
            return requests.post(url, **kw)

        def close(self):
            pass

    monkeypatch.setattr(requests, "Session", RoutedSession)


@pytest.fixture()
def snapshots(tmp_path, monkeypatch) -> Path:
    """Point SNAPSHOT_DIR at a tmp dir and default the mode to fixture."""
    directory = tmp_path / "snapshots"
    directory.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(directory))
    monkeypatch.setenv("CONNECTOR_MODE", "fixture")
    return directory
