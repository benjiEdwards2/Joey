"""WP23 step 3 — the committed fixture sweep.

`config/sample_snapshots/` is what the hub develops against before a single
live credential exists, so it must be regenerable byte-for-byte by anyone
running the sweep in fixture mode.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from connectors import stubs  # noqa: F401  (import registers the stubs)
from connectors.run_all import HEARTBEAT_NAME, HISTORY_NAME, run_sweep

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "config" / "sample_snapshots"
DATA_SCHEMA_DIR = REPO_ROOT / "connectors" / "schema" / "data"

FEEDS = ["arr", "gcal", "home_assistant", "jellyfin", "jellyseerr", "macromates", "media_status", "nas_stats", "open_meteo", "qbittorrent", "system", "uptime_kuma", "wud"]


def test_fixture_sweep_produces_every_feed_plus_runner_evidence(snapshots, validate_envelope):
    run_sweep()

    written = sorted(p.stem for p in snapshots.glob("*.json") if not p.name.startswith("_"))
    assert written == FEEDS

    for connector_id in FEEDS:
        envelope = json.loads((snapshots / f"{connector_id}.json").read_text(encoding="utf-8"))
        validate_envelope(envelope)
        assert envelope["status"] == "ok", envelope["error"]

    heartbeat = json.loads((snapshots / HEARTBEAT_NAME).read_text(encoding="utf-8"))
    assert sorted(heartbeat["results"]) == FEEDS
    assert len((snapshots / HISTORY_NAME).read_text(encoding="utf-8").strip().splitlines()) == 1


@pytest.mark.parametrize("connector_id", FEEDS)
def test_committed_sample_is_byte_identical_to_a_fresh_sweep(connector_id, snapshots):
    run_sweep()
    fresh = (snapshots / f"{connector_id}.json").read_text(encoding="utf-8")
    committed = (SAMPLES / f"{connector_id}.json").read_text(encoding="utf-8")
    assert fresh == committed, (
        f"config/sample_snapshots/{connector_id}.json is stale — regenerate it "
        "(see config/sample_snapshots/README.md)"
    )


@pytest.mark.parametrize("connector_id", FEEDS)
def test_committed_sample_satisfies_both_contracts(connector_id, validate_envelope):
    envelope = json.loads((SAMPLES / f"{connector_id}.json").read_text(encoding="utf-8"))
    validate_envelope(envelope)
    schema = json.loads((DATA_SCHEMA_DIR / f"{connector_id}.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(envelope["data"], schema)
    assert envelope["fetched_at"] == envelope["updated_at"] == "2026-01-01T00:00:00+00:00"


def test_no_runtime_history_was_committed():
    """The heartbeat is a useful sample; the append-only history is runtime
    evidence and belongs on the box only (D13)."""
    assert (SAMPLES / HEARTBEAT_NAME).is_file()
    assert not (SAMPLES / HISTORY_NAME).exists()
