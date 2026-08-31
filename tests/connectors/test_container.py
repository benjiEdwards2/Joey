"""WP22 step 6 — the blind-authored container assets.

Nothing here starts an engine (the dev machine has none); these tests pin the
shape a WP24 engine-verify will confirm.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "connectors" / "Dockerfile"


def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_parses_and_defines_both_services():
    assert set(compose()["services"]) == {"hub", "connectors"}


def test_compose_notes_that_no_engine_has_seen_it_yet():
    assert "first engine-verify: WP24 step 1" in COMPOSE.read_text(encoding="utf-8")


def test_hub_service_mounts_snapshots_read_only_and_publishes_no_port():
    hub = compose()["services"]["hub"]
    assert "/opt/life-dashboard-data/snapshots:/data/snapshots:ro" in hub["volumes"]
    assert "ports" not in hub, "the hub is reached through the tunnel only (WP11)"


def test_connectors_service_matches_the_D16_cadence_contract():
    svc = compose()["services"]["connectors"]
    assert svc["restart"] == "unless-stopped"
    assert svc["env_file"] == [".env"]
    assert "/opt/life-dashboard-data/snapshots:/data/snapshots" in svc["volumes"]
    entrypoint = " ".join(svc["entrypoint"])
    assert "python -m connectors.run_all" in entrypoint
    assert "sleep 3600" in entrypoint
    assert "cron" not in entrypoint  # D16: sleep loop, never crond


def test_connectors_dockerfile_follows_the_hub_pattern():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    assert "USER joey" in text                       # non-root
    assert "COPY tests/ tests/" in text                # suite ships in the image
    assert "connectors/requirements.txt" in text
