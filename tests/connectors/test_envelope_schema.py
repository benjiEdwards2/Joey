"""WP0 seed test: the FROZEN envelope schema (D13) is a valid 2020-12 JSON Schema
and carries the frozen connector id namespace. If this ever fails, the frozen
contract was touched — which requires a dated DECISIONS.md entry and a full
hub-suite re-run, per D13."""

import json
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "connectors" / "schema" / "envelope.schema.json"

FROZEN_IDS = [
    "open_meteo",
    "gcal",
    "clickup",
    "macromates",
    "home_assistant",
    "jellyfin",
    "nas_stats",
    "money",
    "media_status",  # added 2026-10-05 (authorised dated decision)
    "arr",  # added 2026-10-05 (authorised dated decision, Media Phase 2)
    "jellyseerr",  # added 2026-10-05 (authorised dated decision, Media Phase 3)
]

REQUIRED_FIELDS = [
    "connector",
    "schema_version",
    "fetched_at",
    "updated_at",
    "status",
    "consecutive_failures",
    "error",
    "data",
]


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_envelope_schema_is_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(load_schema())


def test_frozen_id_namespace_is_the_connector_enum():
    schema = load_schema()
    assert schema["properties"]["connector"]["enum"] == FROZEN_IDS


def test_required_fields_are_frozen():
    schema = load_schema()
    assert schema["required"] == REQUIRED_FIELDS
    assert schema["properties"]["schema_version"] == {"const": 1}
    assert schema["additionalProperties"] is False
