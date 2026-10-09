"""MacroMates static-server service shape (Gate 1, 2026-10-05).

The built PWA bundle (benjiEdwards2/macromates-app) is served by nginx inside
the Joey stack, reachable only through the joey-nas tunnel at
macromates.joeyhome.net behind the family-allowlist Access policy.
"""

from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
COMPOSE = DEPLOY / "docker-compose.yml"


def macromates() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["macromates"]


def test_macromates_service_shape():
    svc = macromates()
    assert svc["image"] == "nginx:1.31.6-alpine"  # pinned, D-06
    assert svc["container_name"] == "joey-macromates"
    assert svc["restart"] == "unless-stopped"


def test_macromates_publishes_no_port():
    svc = macromates()
    assert "ports" not in svc  # tunnel-only, like the hub
    assert svc["expose"] == ["80"]


def test_macromates_mounts_bundle_readonly_and_conf():
    vols = macromates()["volumes"]
    assert "/volume1/Docker/joey/macromates-app:/usr/share/nginx/html:ro" in vols
    assert "./macromates.nginx.conf:/etc/nginx/conf.d/default.conf:ro" in vols


def test_nginx_conf_has_spa_fallback_and_sw_no_cache():
    conf = (DEPLOY / "macromates.nginx.conf").read_text(encoding="utf-8")
    assert "try_files $uri $uri/ /index.html;" in conf
    assert "location = /sw.js" in conf
    assert 'Cache-Control "no-cache"' in conf


def test_smoke_probes_macromates():
    smoke = (Path(__file__).resolve().parent / "smoke.py").read_text(encoding="utf-8")
    assert "http://macromates/" in smoke
