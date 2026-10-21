"""Review D-04 (2026-10-09): on a 3.7 GB swapping NAS every service rotates its logs and has a
memory cap; the connectors container gets an init and a heartbeat healthcheck."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
LIMITS = {"hub": "384m", "connectors": "256m", "cloudflared": "128m", "macromates": "32m",
          "swag": "192m", "ddns": "32m",  # swag + ddns: Joey TV WP-A3 edge (2026-10-18)
          "joey-media": "384m"}  # Joey TV WP-B1 guest front (2026-10-21): a ceiling; re-cap after measuring (P4)


def test_every_service_rotates_its_json_file_log():
    rotated = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
    assert COMPOSE["x-logging"] == rotated
    for name, svc in SERVICES.items():
        assert svc.get("logging") == rotated, name


def test_every_service_has_a_memory_cap():
    assert set(SERVICES) == set(LIMITS)  # a new service must pick a cap here
    for name, svc in SERVICES.items():
        assert svc.get("mem_limit") == LIMITS[name], name


def test_connectors_run_under_init_with_a_heartbeat_healthcheck():
    svc = SERVICES["connectors"]
    assert svc["init"] is True
    check = svc["healthcheck"]
    assert check["test"][:3] == ["CMD", "python", "-c"]
    assert "/data/snapshots/_runner.json" in check["test"][3] and "> 300" in check["test"][3]
    assert (check["interval"], check["start_period"]) == ("60s", "180s")
