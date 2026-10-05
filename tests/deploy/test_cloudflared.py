"""WP11 — cloudflared tunnel service shape.

The tunnel (`joey-nas` in Zero Trust) fronts the hub over the compose
network; the token lives ONLY in the NAS-side .env (rule 11). No public
hostnames exist until WP12 puts Access in front.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / "deploy" / ".env.example"


def cloudflared() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["cloudflared"]


def test_cloudflared_service_shape():
    svc = cloudflared()
    assert svc["image"] == "cloudflare/cloudflared:latest"
    assert svc["restart"] == "unless-stopped"
    assert svc["command"] == "tunnel --no-autoupdate run"
    assert svc["environment"] == {"TUNNEL_TOKEN": "${TUNNEL_TOKEN}"}


def test_cloudflared_publishes_no_port_and_joins_the_default_network():
    svc = cloudflared()
    assert "ports" not in svc and "expose" not in svc
    # no custom networks anywhere: every service shares the compose default,
    # so cloudflared reaches the hub as http://hub:8000
    full = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert "networks" not in full
    assert all("networks" not in s for s in full["services"].values())


def test_env_example_carries_a_blank_tunnel_token():
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert "TUNNEL_TOKEN=" in lines  # blank template line, real value NAS-only


def test_hub_reads_the_env_file_and_mounts_the_poster_cache_read_write():
    hub = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["hub"]
    assert hub["env_file"] == [".env"]
    assert hub["environment"]["IMG_CACHE_DIR"] == "/data/cache/img"
    assert "/volume1/Docker/joey/data/cache/img:/data/cache/img" in hub["volumes"]
    assert "/volume1/Docker/joey/data/snapshots:/data/snapshots:ro" in hub["volumes"]  # still read-only
    # first write path (2026-10-05): ratings + diary DB in its own read-write volume
    assert hub["environment"]["MEDIA_DB_PATH"] == "/data/sqlite/media.db"
    assert "/volume1/Docker/joey/data/sqlite:/data/sqlite" in hub["volumes"]
