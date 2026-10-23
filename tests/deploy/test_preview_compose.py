"""JY-012: the preview slot's compose file (deploy/preview/docker-compose.yml) against the main stack's.

The main deploy's `up -d --remove-orphans` must never see the preview (spec 8): compose removes only orphans that carry
its own project label, so the two project names must differ. deploy.sh runs compose in deploy/ with no -p and the main
file has no top-level `name:`, so the main project is the directory name, `deploy`. Read from both files, no Docker."""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"
MAIN = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
PREVIEW = yaml.safe_load((DEPLOY / "preview" / "docker-compose.yml").read_text(encoding="utf-8"))
SVC = PREVIEW["services"]["joey-preview"]
LIVE_ROOT = "/volume1/Docker/joey"
PREVIEW_ROOT = "/volume1/Docker/joey/preview/"


def main_project():
    deploy_sh = (DEPLOY / "deploy.sh").read_text(encoding="utf-8")
    assert "name" not in MAIN  # no top-level project name in the main file
    assert not re.search(r"compose\s+(-p|--project-name)\b", deploy_sh)
    assert "COMPOSE_PROJECT_NAME" not in deploy_sh
    assert "COMPOSE_PROJECT_NAME" not in (DEPLOY / ".env.example").read_text(encoding="utf-8")
    assert 'cd "$DEPLOY_DIR"' in deploy_sh and "DEPLOY_DIR=$REPO/deploy" in deploy_sh
    return "deploy"


def test_projects_differ_so_remove_orphans_never_sees_the_preview():
    assert PREVIEW["name"] == "joey-preview"
    assert main_project() != PREVIEW["name"]


def test_one_service_no_connectors():
    assert list(PREVIEW["services"]) == ["joey-preview"]


def test_names_never_clash_with_the_main_stack():
    # a service name is a DNS alias on the shared network: `hub` would split cloudflared's hub:8000
    assert not set(PREVIEW["services"]) & set(MAIN["services"])
    main_containers = {s.get("container_name") for s in MAIN["services"].values()}
    assert SVC["container_name"] == "joey-preview" and SVC["container_name"] not in main_containers


def test_image_built_by_the_script_not_pulled():
    assert SVC["image"] == "life-hub-preview" and SVC["pull_policy"] == "never"
    assert "build" not in SVC
    assert SVC["image"] not in {s.get("image") for s in MAIN["services"].values()}


def test_mem_limit_logging_and_restart():
    assert SVC["mem_limit"] == "256m"
    assert SVC["logging"] == MAIN["x-logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
    assert SVC["restart"] == "no"  # the NAS powers off overnight: no unasked morning restart


def test_no_ports_no_host_network():
    assert "ports" not in SVC and "network_mode" not in SVC
    assert SVC["expose"] == ["8000"]


def test_joins_the_main_default_network_as_external():
    assert SVC["networks"] == ["joey"]
    net = PREVIEW["networks"]["joey"]
    assert net["external"] is True
    assert net["name"] == f"{main_project()}_default"


def test_mounts_live_snapshots_read_only_and_never_the_live_sqlite_or_backups():
    vols = SVC["volumes"]
    assert f"{LIVE_ROOT}/data/snapshots:/data/snapshots:ro" in vols
    for v in vols:
        host, _, rest = v.partition(":")
        assert host.startswith(PREVIEW_ROOT) or rest.endswith(":ro"), v  # writable mounts only under preview/
        assert "/data/sqlite" not in host and "/backups" not in host, v
    assert f"{PREVIEW_ROOT}sqlite:/data/sqlite" in vols
    # posters from the live img cache, read only (JY-012 review: no Jellyfin key, so the cache is the poster source)
    assert f"{LIVE_ROOT}/data/cache/img:/data/cache/img:ro" in vols


def test_meta_cache_is_preview_only():
    env = SVC["environment"]
    assert env["IMG_CACHE_DIR"] == "/data/cache/img"
    mounts = {v.split(":")[1]: v.split(":")[0] for v in SVC["volumes"]}
    assert mounts[env["META_CACHE_DIR"]].startswith(PREVIEW_ROOT)


def test_env_file_is_the_preview_env_only():
    assert SVC["env_file"] == ["preview.env"]


def test_every_background_loop_is_pinned_off():
    env = SVC["environment"]
    for key in ("MEDIA_BACKUP", "PLAY_RECORDER", "MEDIA_WARMUP", "MEDIA_FOLLOW", "MEDIA_AWARDS", "DIGEST"):
        assert env[key] == "off", key
    assert env["MEDIA_DB_PATH"] == "/data/sqlite/media.db"
    assert env["SNAPSHOT_DIR"] == "/data/snapshots"


def test_main_stack_compose_is_untouched_by_the_preview():
    assert "joey-preview" not in (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    assert "preview" not in (DEPLOY / "deploy.sh").read_text(encoding="utf-8")
