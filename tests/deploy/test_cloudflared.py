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
    assert svc["image"] == "cloudflare/cloudflared:2026.9.3"  # pinned, D-06
    assert svc["restart"] == "unless-stopped"
    assert svc["command"] == "tunnel --no-autoupdate run"
    assert svc["environment"] == {"TUNNEL_TOKEN": "${TUNNEL_TOKEN}"}


def test_cloudflared_publishes_no_port_and_joins_the_default_network():
    svc = cloudflared()
    assert "ports" not in svc and "expose" not in svc
    # cloudflared sits on the compose default only, and the hub stays on it, so cloudflared
    # reaches the hub as http://hub:8000. The one extra network is the media stack's (N-09),
    # joined by hub + connectors only.
    full = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert set(full["networks"]) == {"media", "joey-edge"}
    assert "networks" not in svc
    assert "default" in full["services"]["hub"]["networks"]


def test_only_cloudflared_is_handed_the_tunnel_token_explicitly():
    """D-05: the split env files are per service; cloudflared gets no env_file at all."""
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    assert "env_file" not in services["cloudflared"] and "env_file" not in services["macromates"]
    assert services["connectors"]["env_file"] == [".env", {"path": "connectors.env", "required": False}]
    assert all("TUNNEL_TOKEN" not in (s.get("environment") or {})
               for name, s in services.items() if name != "cloudflared")


def test_env_example_carries_a_blank_tunnel_token():
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert "TUNNEL_TOKEN=" in lines  # blank template line, real value NAS-only


def test_hub_reads_the_env_file_and_mounts_the_poster_cache_read_write():
    hub = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["hub"]
    # D-05 (2026-10-09): .env stays (backward compatible); hub.env is the optional least-privilege split
    assert hub["env_file"] == [".env", {"path": "hub.env", "required": False}]
    assert hub["environment"]["IMG_CACHE_DIR"] == "/data/cache/img"
    assert "/volume1/Docker/joey/data/cache/img:/data/cache/img" in hub["volumes"]
    assert "/volume1/Docker/joey/data/snapshots:/data/snapshots:ro" in hub["volumes"]  # still read-only
    # first write path (2026-10-05): ratings + diary DB in its own read-write volume
    assert hub["environment"]["MEDIA_DB_PATH"] == "/data/sqlite/media.db"
    assert "/volume1/Docker/joey/data/sqlite:/data/sqlite" in hub["volumes"]
