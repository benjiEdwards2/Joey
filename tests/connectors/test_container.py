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
    # grew from {hub, connectors} at WP11 (cloudflared tunnel added)
    assert set(compose()["services"]) == {"hub", "connectors", "cloudflared", "macromates"}


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
    assert "python -m connectors.run_all" in entrypoint
    assert "sleep 3600" in entrypoint
    # fast 2-minute loop for the live Media feeds (D16 amended 2026-10-05)
    assert "python -m connectors.run_all --only jellyfin,media_status,qbittorrent,arr,system,uptime_kuma; sleep 120" in entrypoint
    assert "cron" not in entrypoint  # D16: sleep loop, never crond


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
