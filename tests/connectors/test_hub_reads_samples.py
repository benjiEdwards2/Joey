"""WP23 step 5 — cross-track freeze confirmation.

The hub (Track C) and the connectors (Track D) were built in separate sessions
against the same frozen envelope. This points the real hub at the committed
sample snapshots and proves every tile resolves off them — no "Not connected",
and the summary/secondary the hub renders is the one the transforms produce.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import registry as hub_registry
from hub import store
from hub.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "config" / "sample_snapshots"


@pytest.fixture()
def sample_snapshots():
    return store.get_snapshots(SAMPLES)


def test_hub_parses_every_committed_sample(sample_snapshots):
    assert set(sample_snapshots) == {
        "arr", "gcal", "home_assistant", "jellyfin", "jellyseerr", "macromates", "media_status", "nas_stats",
        "open_meteo",
    }
    assert all(s.status == "ok" for s in sample_snapshots.values())


def test_every_connector_backed_tile_resolves_to_real_content(sample_snapshots):
    areas = hub_registry.load_registry(REPO_ROOT / "config" / "areas.yaml").areas
    checked = 0
    for area in areas:
        for tile in area.tiles:
            if tile.tier.value == "link" or tile.snapshot == "money":
                continue  # LINK tiles have no snapshot; money is Track E's (D14)
            resolved = store.tile_state(tile, sample_snapshots)
            assert resolved["state"] != "off", f"{area.id}/{tile.id} reads Not connected"
            assert resolved["value"] and resolved["value"] != "—"
            assert resolved["secondary"], "D17's secondary line is missing"
            checked += 1
    # meals, files, next-event, weather, watching, media status, library, requests, watched, diary, by year, discover, climate, car-status (garden removed 2026-09-11)
    assert checked == 14


def test_weather_tile_shows_the_composed_summary(sample_snapshots):
    assert sample_snapshots["open_meteo"].data["summary"] == "18.3 °C · light rain"


def test_hub_renders_the_sample_snapshots_end_to_end(monkeypatch):
    monkeypatch.setenv("SNAPSHOT_DIR", str(SAMPLES))
    with TestClient(app) as client:
        hub_page = client.get("/")
        assert hub_page.status_code == 200
        # Each area's summary tile, straight off the WP23 transforms
        assert "Weekly standup" in hub_page.text          # calendar
        assert "Tonight: Salmon and greens" in hub_page.text  # kitchen
        assert "playing now" in hub_page.text             # media

        calendar_page = client.get("/a/calendar")
        assert calendar_page.status_code == 200
        assert "light rain" in calendar_page.text         # the weather EMBED tile
        # Only money is unconnected here — Track E's importer writes it (D14)
        assert calendar_page.text.count("Not connected") == 0
