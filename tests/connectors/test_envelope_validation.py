"""WP22 step 2 — validation cases against the FROZEN envelope schema (D13).

If any of these ever needs the schema changed, that is a dated DECISIONS.md
entry plus a full hub-suite re-run — never a silent edit.
"""

import pytest
from jsonschema import ValidationError

GOOD = {
    "connector": "open_meteo",
    "schema_version": 1,
    "fetched_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
    "status": "ok",
    "consecutive_failures": 0,
    "error": None,
    "data": {"summary": "18 °C · light rain"},
}


def test_good_envelope_validates(validate_envelope):
    validate_envelope(GOOD)


def test_missing_updated_at_rejected(validate_envelope):
    bad = {k: v for k, v in GOOD.items() if k != "updated_at"}
    with pytest.raises(ValidationError):
        validate_envelope(bad)


def test_status_stale_rejected(validate_envelope):
    """Staleness is COMPUTED by the hub from updated_at — never a stored status."""
    with pytest.raises(ValidationError):
        validate_envelope({**GOOD, "status": "stale"})


def test_negative_consecutive_failures_rejected(validate_envelope):
    with pytest.raises(ValidationError):
        validate_envelope({**GOOD, "consecutive_failures": -1})


def test_unknown_connector_id_rejected(validate_envelope):
    with pytest.raises(ValidationError):
        validate_envelope({**GOOD, "connector": "notion"})
