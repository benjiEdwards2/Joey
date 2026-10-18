"""WP22 step 6 — container assets, re-pinned at the NAS bring-up.

Authored blind at WP22; first engine-verified on the AS5304T NAS 2026-08-31
(DECISIONS D10 remap). These tests pin the deployed shape: host paths live
under /volume1/Docker/joey/ on the NAS.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "connectors" / "Dockerfile"


def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_parses_and_defines_the_stack_services():
    # grew from {hub, connectors} at WP11 (cloudflared tunnel added); swag + ddns: Joey TV WP-A3 edge (2026-10-18)
    assert set(compose()["services"]) == {"hub", "connectors", "cloudflared", "macromates", "swag", "ddns"}


def test_compose_records_the_nas_host_decision():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "D10 remap" in text  # dated decision the paths trace to
    assert "/volume1/Docker/joey/" in text


def test_hub_service_mounts_snapshots_read_only_and_publishes_no_port():
    hub = compose()["services"]["hub"]
    assert "/volume1/Docker/joey/data/snapshots:/data/snapshots:ro" in hub["volumes"]
    assert "ports" not in hub, "the hub is reached through the tunnel only (WP11)"


def test_connectors_service_matches_the_D16_cadence_contract():
    svc = compose()["services"]["connectors"]
    assert svc["restart"] == "unless-stopped"
    assert svc["env_file"] == [".env", {"path": "connectors.env", "required": False}]  # D-05 optional split
    assert "/volume1/Docker/joey/data/snapshots:/data/snapshots" in svc["volumes"]
    entrypoint = " ".join(svc["entrypoint"])
    fast = "jellyfin,media_status,qbittorrent,arr,system,uptime_kuma"
    # C-17 (2026-10-09): one full sweep at start (every envelope), then the fast loop, then the
    # hourly loop over everything EXCEPT the fast ids, so no connector runs in both loops at once
    assert entrypoint.startswith("sh -c python -m connectors.run_all; (while true;")
    # fast 2-minute loop for the live Media feeds (D16 amended 2026-10-05)
    assert f"python -m connectors.run_all --only {fast}; sleep 120" in entrypoint
    assert f"while true; do sleep 3600; python -m connectors.run_all --except {fast}; done" in entrypoint
    assert entrypoint.count("python -m connectors.run_all;") == 1  # the one full sweep
    assert "cron" not in entrypoint  # D16: sleep loop, never crond


def test_the_fast_ids_are_live_connectors():
    from connectors import registry

    fast = "jellyfin,media_status,qbittorrent,arr,system,uptime_kuma".split(",")
    assert set(fast) <= set(registry.all_ids()) and not set(fast) & set(registry.parked_ids())


def test_connectors_system_feed_uses_the_snapshots_mount_not_the_whole_volume():
    """C-19 (2026-10-09): statvfs on the snapshots dir reports /volume1's numbers, so the
    `/volume1:/host/volume1:ro` bind is gone; the label keeps the UI saying /volume1.
    The statvfs target + its env live in compose, never .env."""
    svc = compose()["services"]["connectors"]
    assert svc["volumes"] == ["/volume1/Docker/joey/data/snapshots:/data/snapshots"]
    assert not any(v.startswith("/volume1:") for v in svc["volumes"])
    assert svc["environment"]["SYSTEM_VOLUMES"] == "/data/snapshots"
    assert svc["environment"]["SYSTEM_VOLUME_LABELS"] == "/data/snapshots=/volume1"


def test_connectors_dockerfile_follows_the_hub_pattern():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    assert "USER joey" in text                       # non-root
    assert "COPY tests/ tests/" in text                # suite ships in the image
    assert "connectors/requirements.txt" in text


def test_hub_and_connectors_join_the_media_stack_network():
    """N-09 (2026-10-09): service-name URLs (jellyfin:8096, gluetun:8080, ...) need the media
    stack's network; `default` stays so cloudflared still reaches hub:8000."""
    doc = compose()
    assert doc["networks"] == {"media": {"external": True, "name": "media-server_default"},
                               # Joey TV WP-A3 (Q45): swag <-> jellyfin only; hub/connectors never join it
                               "joey-edge": {"external": True, "name": "joey-edge"}}
    for name in ("hub", "connectors"):
        assert doc["services"][name]["networks"] == ["default", "media"], name
    for name in ("cloudflared", "macromates"):
        assert "networks" not in doc["services"][name], name  # tunnel side only
