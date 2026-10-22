"""Joey TV WP-B1 (2026-10-21): the guest container `joey-media` - the same life-hub image with JOEY_FRONT=media,
dark behind `profiles: [media]` (D-P18) until WP-B5 step 1 adds `media` to COMPOSE_PROFILES. Reached only by
cloudflared on the compose default network (media.joeyhome.net); no host port (which also keeps it clear of the ADM
Defender DNAT race, WP-A4). Its env file holds the Q23 guest keys only."""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_TEXT = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
EXAMPLE = REPO_ROOT / "deploy" / "media.env.example"
SCRIPT = (REPO_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
SMOKE = (REPO_ROOT / "tests" / "deploy" / "smoke.py").read_text(encoding="utf-8")
LOOPS_OFF = {"MEDIA_BACKUP": "off", "PLAY_RECORDER": "off", "MEDIA_WARMUP": "off", "MEDIA_FOLLOW": "off",
             "MEDIA_AWARDS": "off"}
Q23_KEYS = {"JELLYFIN_URL", "JELLYFIN_API_KEY", "JELLYFIN_USER", "JELLYFIN_USER_ALIASES", "JELLYFIN_USER_HER",
            "JELLYSEERR_URL", "JELLYSEERR_API_KEY", "OMDB_API_KEY", "JELLYFIN_PUBLIC_URL"}
FORBIDDEN_PREFIXES = ("TUNNEL_TOKEN", "RADARR_", "SONARR_", "QBIT_", "WUD_", "UPTIME_KUMA_", "PROWLARR_",
                      "SERVER_DISCORD", "MEDIA_DISCORD", "DISCORD", "OWNER_EMAIL", "ICS_URL_", "MONEY_", "HUB_DEV",
                      "GUEST_DEV_OWNER", "ACCESS_", "STACKCTL_", "CLOUDFLARE_", "AWARDS_CONTACT")


def svc() -> dict:
    return COMPOSE["services"]["joey-media"]


def test_joey_media_service():
    s = svc()
    assert s["profiles"] == ["media"]
    assert s["image"] == "life-hub" and "build" not in s
    assert s["pull_policy"] == "never"
    assert s["container_name"] == "joey-media"
    assert s["restart"] == "unless-stopped"
    assert s["depends_on"] == {"hub": {"condition": "service_healthy"}}   # hub migrates media.db first
    env = s["environment"]
    assert env["JOEY_FRONT"] == "media"
    assert {k: v for k, v in env.items() if k in LOOPS_OFF} == LOOPS_OFF
    assert env["SNAPSHOT_DIR"] == "/data/snapshots" and env["MEDIA_DB_PATH"] == "/data/sqlite/media.db"
    assert "/volume1/Docker/joey/data/snapshots:/data/snapshots:ro" in s["volumes"]   # Q22: read-only
    assert "/volume1/Docker/joey/data/cache/img:/data/cache/img" in s["volumes"]
    assert "/volume1/Docker/joey/data/sqlite:/data/sqlite" in s["volumes"]
    assert not [v for v in s["volumes"] if "backups" in v]   # joey-hub stays the one backup writer
    assert "MEDIA_BACKUP_DIR" not in env
    assert "ports" not in s and s["expose"] == ["8000"]
    assert s["networks"] == ["default", "media"]
    assert s["env_file"] == [{"path": "media.env", "required": False}]   # never .env / hub.env (Q23)
    assert s["mem_limit"] == "384m"


def test_no_dev_seams_anywhere_in_compose():
    for name, service in COMPOSE["services"].items():
        env = service.get("environment") or {}
        names = env if isinstance(env, dict) else [e.split("=", 1)[0] for e in env]
        assert not {"HUB_DEV", "GUEST_DEV_OWNER"} & set(names), name
        if isinstance(env, dict):
            assert str(env.get("JOEY_COOKIE_SECURE", "1")) != "0", name
    for word in ("HUB_DEV", "GUEST_DEV_OWNER", "JOEY_COOKIE_SECURE=0", "JOEY_COOKIE_SECURE: \"0\""):
        assert word not in COMPOSE_TEXT, word


def test_media_env_example_holds_the_guest_keys_only():
    keys = {m.group(1) for m in re.finditer(r"^#?\s*([A-Z][A-Z0-9_]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M)}
    assert keys == Q23_KEYS
    assert not [k for k in keys if k.startswith(FORBIDDEN_PREFIXES)]
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert value in ("", "https://jellyfin.joeyhome.net:8443"), name   # no secret values in git


def test_joey_media_is_the_only_front_setting_in_compose():
    fronts = {n: (s.get("environment") or {}).get("JOEY_FRONT") for n, s in COMPOSE["services"].items()
              if isinstance(s.get("environment"), dict)}
    assert {n: f for n, f in fronts.items() if f} == {"joey-media": "media"}


# ---- deploy.sh + smoke.py (step 10) ----

def _body(name: str) -> str:
    start = SCRIPT.index("\n" + name + "() {") + 1   # at a line start: "smoke" is not "media_smoke"
    return SCRIPT[start:SCRIPT.index("\n}\n", start)]


def test_media_smoke_runs_after_the_hub_smoke_only_when_the_profile_is_active():
    active = _body("media_active")
    assert "docker compose config --services 2>/dev/null | grep -qx joey-media" in active   # edge_active()'s twin
    media = _body("media_smoke")
    guard = media.index("if ! media_active; then")
    assert "return 0" in media[guard:guard + 60]
    wait = media.index("wait_for joey-media")
    run = media.index("docker compose exec -T joey-media python tests/deploy/smoke.py --front media")
    assert guard < wait < run
    smoke = _body("smoke")
    assert smoke.index("docker compose exec -T hub python tests/deploy/smoke.py") < smoke.index("&& media_smoke")
    assert (SCRIPT.index("\nmedia_active() {") < SCRIPT.index("\nmedia_smoke() {")
            < SCRIPT.index("\nsmoke() {\n    wait_for_hub"))
    assert 'smoke || rollback "smoke failed"' in SCRIPT   # one build, one rollback path
    assert "&& smoke; then" in _body("rollback")


def test_wait_for_takes_a_service():
    wait = _body("wait_for")
    assert 'docker compose exec -T "$1" python -c' in wait and "[ $i -lt 18 ]" in wait
    assert _body("wait_for_hub").strip().endswith("wait_for hub")


def test_media_additions_stay_busybox_safe():
    added = _body("media_active") + _body("media_smoke") + _body("wait_for")
    for bashism in ("[[", "function ", "local ", "${!", "<(", "pipefail;"):
        assert bashism not in added, bashism


def test_smoke_has_a_front_and_a_base():
    assert '"--front"' in SMOKE and '"--base"' in SMOKE
    assert 'choices=("private", "media")' in SMOKE
    for path in ("/server", "/whoami", "/a/calendar", "/media/downloads", "/money", "/openapi.json"):
        assert f'"{path}"' in SMOKE, path


def _smoke_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("joey_smoke", REPO_ROOT / "tests" / "deploy" / "smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_front(front: str, statuses: dict, seen: list):
    def fetch(url, headers=None):
        seen.append((url, dict(headers or {})))
        path = url.split("://", 1)[1].partition("/")[2]
        path = "/" + path
        if path == "/healthz":
            return 200, ('{"front": "%s"}' % front).encode()
        return statuses.get(path, 404), b""
    return fetch


def test_smoke_front_media_passes_on_the_media_front_with_a_forged_header():
    smoke, seen = _smoke_module(), []
    smoke.fetch = _fake_front("media", {"/": 303}, seen)
    assert smoke.main(["--front", "media", "--base", "http://127.0.0.1:8850"]) == 0
    assert all(h.get("Cf-Access-Authenticated-User-Email") for _, h in seen)   # forged on every media request
    assert [u for u, _ in seen][-1] == "http://127.0.0.1:8850/"


def test_smoke_front_media_fails_on_a_401_or_a_served_private_page():
    smoke = _smoke_module()
    smoke.fetch = _fake_front("media", {"/": 303, "/server": 401}, [])
    assert smoke.main(["--front", "media"]) == 1
    smoke.fetch = _fake_front("media", {"/": 303, "/money": 200}, [])
    assert smoke.main(["--front", "media"]) == 1


def test_smoke_front_private_fails_against_the_media_front():
    smoke = _smoke_module()
    smoke.fetch = _fake_front("media", {"/": 303}, [])
    assert smoke.main(["--front", "private", "--base", "http://127.0.0.1:8850"]) == 1
    smoke.fetch = _fake_front("private", {"/": 303}, [])   # the private hub never passes the media smoke
    assert smoke.main(["--front", "media"]) == 1


# ---- Joey TV WP-B8 step 6: joey-media serves the published TV release read-only, and its smoke checks it ----

def test_joey_media_mounts_the_tv_app_dir_read_only():
    s = svc()
    assert "/volume1/Docker/joey/data/tv-app:/data/tv-app:ro" in s["volumes"]
    assert s["environment"]["TV_APP_DIR"] == "/data/tv-app"
    hub = COMPOSE["services"]["hub"]
    assert not [v for v in hub.get("volumes", []) if "tv-app" in v]   # the private hub never serves /app
    assert "TV_APP_DIR=/volume1/Docker/joey/data/tv-app" in SCRIPT     # the same host dir deploy.sh publishes to


def test_smoke_front_media_accepts_version_json_or_404_only():
    smoke, seen = _smoke_module(), []
    smoke.fetch = _fake_front("media", {"/": 303}, seen)       # /app/version.json -> 404: nothing published yet
    assert smoke.main(["--front", "media"]) == 0
    assert "http://127.0.0.1:8000/app/version.json" in [u for u, _ in seen]

    def published(body: bytes, status: int = 200):
        base = _fake_front("media", {"/": 303}, [])
        return lambda url, headers=None: (status, body) if url.endswith("/app/version.json") else base(url, headers)

    smoke.fetch = published(b'{"versionCode": 2026110302, "url": "joey-media-1.4.0-2026110302.apk"}')
    assert smoke.main(["--front", "media"]) == 0
    smoke.fetch = published(b"<html>not json</html>")
    assert smoke.main(["--front", "media"]) == 1
    smoke.fetch = published(b'{"versionCode": "2026110302"}')   # the code must be an integer
    assert smoke.main(["--front", "media"]) == 1
    smoke.fetch = published(b"", 500)
    assert smoke.main(["--front", "media"]) == 1
