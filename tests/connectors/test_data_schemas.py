"""WP23 step 2 — per-feed data schemas: what the hub is allowed to rely on.

Every fixture, through its real transform(), must satisfy BOTH the frozen
envelope schema and its own data schema — and every data block must carry the
hub display convention (summary + optional secondary, D17/WP18).
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from connectors import registry, stubs  # noqa: F401  (import registers the stubs)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_SCHEMA_DIR = REPO_ROOT / "connectors" / "schema" / "data"

FEEDS = ["arr", "gcal", "home_assistant", "jellyfin", "jellyseerr", "macromates", "media_status", "nas_stats", "open_meteo", "qbittorrent", "system", "wud"]


def data_schema(connector_id: str) -> dict:
    return json.loads((DATA_SCHEMA_DIR / f"{connector_id}.schema.json").read_text(encoding="utf-8"))


def run_stub(connector_id: str) -> dict:
    connector = dict(zip([c.id for c in registry.build_all()], registry.build_all()))[connector_id]
    return connector.run()


def test_registry_holds_exactly_the_v1_connectors():
    assert registry.connector_ids() == FEEDS
    assert "clickup" not in registry.connector_ids()  # removed from v1 (2026-08-25)
    assert "money" not in registry.connector_ids()    # Track E importer, not a Connector (D14)


@pytest.mark.parametrize("connector_id", FEEDS)
def test_data_schema_is_valid_and_enforces_the_display_convention(connector_id):
    schema = data_schema(connector_id)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert "summary" in schema["required"], "the hub renders data.summary (D17)"
    assert schema["properties"]["secondary"]["type"] == "string"


@pytest.mark.parametrize("connector_id", FEEDS)
def test_fixture_transform_validates_against_both_contracts(
    connector_id, snapshots, validate_envelope
):
    envelope = run_stub(connector_id)
    assert envelope["status"] == "ok", envelope["error"]
    validate_envelope(envelope)
    jsonschema.validate(envelope["data"], data_schema(connector_id))
    assert envelope["data"]["summary"]
    assert envelope["data"]["secondary"]


@pytest.mark.parametrize(
    "connector_id, mutate",
    [
        ("gcal", lambda d: d["events"][0].__setitem__("owner", "both")),
        ("home_assistant", lambda d: d["areas"]["car"][0].__setitem__("owner", "both")),
        ("macromates", lambda d: d.__setitem__("owner", "both")),
    ],
)
def test_owner_both_is_rejected(connector_id, mutate, snapshots):
    """Owner is you|her|shared. 'both' is a VIEW (the switcher), never a record."""
    data = copy.deepcopy(run_stub(connector_id)["data"])
    mutate(data)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, data_schema(connector_id))


def test_home_assistant_is_keyed_by_area_so_tiles_can_slice(snapshots):
    """House/Car/Garden share one connector — per-area keying is what lets each
    tile show its own entities (the WP18 known limit closes here)."""
    areas = run_stub("home_assistant")["data"]["areas"]
    assert set(areas) == {"house", "car", "garden"}
    assert all(e["owner"] == "you" for e in areas["car"])
    assert {e["entity_id"] for e in areas["garden"]} == {
        "sensor.garden_soil_moisture", "switch.garden_irrigation"
    }


def test_gcal_merges_both_feeds_with_recurrence_allday_and_offset(snapshots):
    events = run_stub("gcal")["data"]["events"]
    assert {e["owner"] for e in events} == {"you", "her"}
    titles = [e["title"] for e in events]
    assert titles.count("Weekly standup") == 2   # RRULE expanded
    assert titles.count("Pilates class") == 2    # Outlook RRULE expanded
    assert any(e["all_day"] for e in events)
    # Written in UTC (23:30Z on the 7th), surfaced as the same instant in the
    # calendar's own zone — offset-aware, never naive, and lands on the 8th.
    offset_event = next(e for e in events if e["title"] == "Overseas supplier call")
    start = datetime.fromisoformat(offset_event["start"])
    assert start.utcoffset() is not None
    assert start.astimezone(timezone.utc).isoformat(timespec="minutes") == "2026-01-07T23:30+00:00"


def test_no_data_schema_exists_for_removed_or_foreign_ids():
    present = {p.name.replace(".schema.json", "") for p in DATA_SCHEMA_DIR.glob("*.schema.json")}
    assert present == set(FEEDS)
    assert "clickup" not in present
    assert "money" not in present  # WP32 authors it under connectors/money/ (§4 rule 9)
