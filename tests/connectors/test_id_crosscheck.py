"""WP23 step 4 — areas.yaml <-> registry id cross-check.

Turns the silent "tile renders Not connected forever because the snapshot id
was typo'd" failure into a red test. LINK tiles are exempt (no snapshot at all).
"""

from pathlib import Path

import yaml

from connectors import registry, stubs  # noqa: F401  (import registers the stubs)

REPO_ROOT = Path(__file__).resolve().parents[2]
AREAS = REPO_ROOT / "config" / "areas.yaml"

# Ids are checked against registry.all_ids(): parked connectors (2026-10-09) are skipped by
# live sweeps but stay registered, and hidden areas still reference them.
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
    unresolved = snapshot_ids() - set(registry.all_ids()) - NON_CONNECTOR_IDS
    assert not unresolved, f"areas.yaml references ids nothing writes: {sorted(unresolved)}"


def test_every_registered_connector_is_used_by_at_least_one_tile():
    # Parked connectors (JY-221, 2026-10-27) have no area on purpose: the code stays for a revival.
    unused = set(registry.all_ids()) - snapshot_ids() - set(registry.parked_ids())
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
    unresolved = snapshot_ids(typo) - set(registry.all_ids()) - NON_CONNECTOR_IDS
    assert unresolved == {"open_metao"}


def test_retired_areas_leave_the_parked_connectors_unscheduled_but_registered(monkeypatch):
    """JY-221 (2026-10-27): no area shows them and a live sweep (no env set) does not run them; the code stays."""
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    for var in ("SUPABASE_URL", "SUPABASE_KEY", "HA_URL", "HA_TOKEN", "NAS_SHARES_ROOT"):
        monkeypatch.delenv(var, raising=False)
    parked = {"home_assistant", "macromates", "nas_stats"}
    assert parked <= set(registry.all_ids()) and set(registry.parked_ids()) == parked
    assert not parked & set(registry.connector_ids())
    assert not parked & snapshot_ids()
