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
def _no_real_ftp(monkeypatch):
    """The open_meteo radar step speaks FTP (2026-10-06). A live-mode test that doesn't
    mock it gets a refused connection here — the radar step then fails in isolation,
    exactly as when BOM is unreachable — so the suite never touches ftp.bom.gov.au."""
    import ftplib

    class _Refused:
        def __init__(self, *a, **k):
            raise OSError("network disabled in tests")

    monkeypatch.setattr(ftplib, "FTP", _Refused)


@pytest.fixture()
def snapshots(tmp_path, monkeypatch) -> Path:
    """Point SNAPSHOT_DIR at a tmp dir and default the mode to fixture."""
    directory = tmp_path / "snapshots"
    directory.mkdir()
    monkeypatch.setenv("SNAPSHOT_DIR", str(directory))
    monkeypatch.setenv("CONNECTOR_MODE", "fixture")
    return directory
