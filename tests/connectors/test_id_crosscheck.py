"""WP23 step 4 — areas.yaml <-> registry id cross-check.

Turns the silent "tile renders Not connected forever because the snapshot id
was typo'd" failure into a red test. LINK tiles are exempt (no snapshot at all).
"""

from pathlib import Path

import yaml

from connectors import registry, stubs  # noqa: F401  (import registers the stubs)

REPO_ROOT = Path(__file__).resolve().parents[2]
AREAS = REPO_ROOT / "config" / "areas.yaml"

# money is written by Track E's importer, a runner-registered task rather than a
# Connector subclass (D14) — so it is a legitimate areas.yaml id with no registry row.
NON_CONNECTOR_IDS = {"money"}


def snapshot_ids(text: str | None = None) -> set[str]:
    config = yaml.safe_load(text if text is not None else AREAS.read_text(encoding="utf-8"))
    return {
        tile["snapshot"]
        for area in config["areas"]
        for tile in area["tiles"]
        if tile["tier"] in ("embed", "ingest")
    }


def test_every_areas_yaml_snapshot_id_has_a_connector():
    unresolved = snapshot_ids() - set(registry.connector_ids()) - NON_CONNECTOR_IDS
    assert not unresolved, f"areas.yaml references ids nothing writes: {sorted(unresolved)}"


def test_every_registered_connector_is_used_by_at_least_one_tile():
    unused = set(registry.connector_ids()) - snapshot_ids()
    assert not unused, f"connectors nothing displays: {sorted(unused)}"


def test_link_tiles_are_exempt_and_carry_no_snapshot():
    config = yaml.safe_load(AREAS.read_text(encoding="utf-8"))
    link_tiles = [t for a in config["areas"] for t in a["tiles"] if t["tier"] == "link"]
    assert link_tiles, "the Notion/NAS/Jellyfin LINK tiles vanished"
    assert all("snapshot" not in t for t in link_tiles)


def test_a_typo_would_be_caught():
    """Proof the guard bites: the same check over a typo'd copy must fail."""
    typo = AREAS.read_text(encoding="utf-8").replace(
        "snapshot: open_meteo", "snapshot: open_metao", 1
    )
    unresolved = snapshot_ids(typo) - set(registry.connector_ids()) - NON_CONNECTOR_IDS
    assert unresolved == {"open_metao"}
