"""JY-012: scripts/joey.py preview up / down / status against a fake NAS (no ssh, no network, no Docker).

The fake answers each NAS script by its `# joey-preview:<op>` first line and records the ops in order. The clock and
sleep are injected, so the window check and the /healthz poll run instantly. One test runs the real env-building
script under `sh` against a temp .env (skipped when no `sh`)."""
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import joey  # noqa: E402
import joey_preview as jp  # noqa: E402

UTC = dt.timezone.utc
SHA = "0123456789abcdef0123456789abcdef01234567"
OLD = "fedcba9876543210fedcba9876543210fedcba98"
INSIDE = dt.datetime(2026, 10, 23, 3, 0, tzinfo=UTC)    # 14:00 AEDT
OUTSIDE = dt.datetime(2026, 10, 23, 11, 0, tzinfo=UTC)  # 22:00 AEDT
CHANGE_OPS = {"compose-down", "image-rm", "files-rm", "checkout", "build", "restore", "env", "compose-write", "up"}
SECRET = "sk-preview-FAKE-VALUE-123"


class FakeNas:
    def __init__(self, **over):
        self.resp = {
            "lock": [(0, "free", "")],
            "inspect": [(0, "absent", "")],
            "mem": [(0, "1600", ""), (0, "1450", "")],
            "checkout": [(0, SHA, "")],
            "build": [(0, "sha256:abc", "")],
            "restore": [(0, "media-2026-10-22_2003.db.gz", "")],
            "env": [(0, "17 lines\nACCESS_AUD JELLYFIN_API_KEY JELLYFIN_URL TZ", "")],
            "compose-write": [(0, "written", "")],
            "up": [(0, "", "Container joey-preview Started")],
            "health": [(0, "", "")],
            "stats": [(0, "131.2MiB / 256MiB", "")],
            "logs": [(0, "boot line", "")],
            "compose-down": [(0, "", "")],
            "image-rm": [(0, "removed", "")],
            "files-rm": [(0, "removed", "")],
            "leftovers": [(0, "container=\nnetwork=\nimage=", "")],
        }
        self.resp.update(over)
        self.ops, self.scripts = [], []

    def __call__(self, script, timeout=60):
        assert script.startswith("# joey-preview:")
        op = script.splitlines()[0].split(":", 1)[1]
        self.ops.append(op)
        self.scripts.append(script)
        seq = self.resp[op]
        return seq.pop(0) if len(seq) > 1 else seq[0]


def run(argv, nas=None, now=INSIDE, capsys=None):
    nas = nas or FakeNas()
    sleeps = []
    deps = jp.Deps(nas=nas, now=lambda: now, sleep=sleeps.append,
                   resolve=lambda ref: (SHA, f"branch {ref}"), log_dir=None)
    rc = jp.main(argv, deps)
    out = capsys.readouterr().out if capsys else ""
    return rc, nas, out, sleeps


# ---------- dispatch ----------
def test_joey_py_has_the_preview_command():
    assert joey.COMMANDS["preview"] is jp


# ---------- env allow-list ----------
def example_keys():
    text = (REPO_ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^#?[ ]*([A-Z][A-Z0-9_]+)=", text, re.M)}


WRITE_CAPABLE = re.compile(r"^(RADARR|SONARR|JELLYSEERR|QBIT|PROWLARR|STACKCTL|WUD|TUNNEL|CLOUDFLARE)_|DISCORD|WEBHOOK")


def test_every_env_example_key_is_classified_once():
    keys = example_keys()
    assert len(keys) > 50  # the parser found the file's keys
    assert not set(jp.ENV_IN) & set(jp.ENV_OUT)
    assert keys - set(jp.ENV_IN) - set(jp.ENV_OUT) == set()


def test_no_write_capable_key_is_in():
    assert not [k for k in jp.ENV_IN if WRITE_CAPABLE.search(k)]
    for k in ("RADARR_API_KEY", "SONARR_API_KEY", "JELLYSEERR_API_KEY", "QBIT_PASS", "PROWLARR_API_KEY",
              "STACKCTL_TOKEN", "WUD_PASS", "SERVER_DISCORD_WEBHOOK", "MEDIA_DISCORD_WEBHOOK", "TUNNEL_TOKEN",
              "CLOUDFLARE_API_TOKEN", "AWARDS_CONTACT", "ICS_URL_YOU", "ICS_URL_HER"):
        assert k in jp.ENV_OUT, k


def test_read_keys_the_spec_names_are_in():
    for k in ("JELLYFIN_URL", "JELLYFIN_API_KEY", "OMDB_API_KEY", "WEATHER_LAT", "WEATHER_LON", "ACCESS_AUD", "TZ"):
        assert k in jp.ENV_IN, k


def test_forced_off_loops_are_out_and_pinned_off_in_compose():
    env = yaml.safe_load((REPO_ROOT / "deploy" / "preview" / "docker-compose.yml").read_text(encoding="utf-8"))
    env = env["services"]["joey-preview"]["environment"]
    for k in jp.FORCED_OFF:
        assert k in jp.ENV_OUT and env[k] == "off", k


def test_allow_regex_keeps_only_in_keys():
    pat = re.compile(jp.allow_regex())
    lines = [f"{k}={SECRET}" for k in sorted(set(jp.ENV_IN) | set(jp.ENV_OUT))] + [f"# JELLYFIN_URL=x", "XTZ=1"]
    kept = {line.split("=", 1)[0] for line in lines if pat.search(line)}
    assert kept == set(jp.ENV_IN)


def test_readme_table_matches_the_classification():
    text = (REPO_ROOT / "deploy" / "preview" / "README.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| `([A-Z0-9_]+)` \| (in|out) \|", text, re.M))
    assert rows == {**{k: "in" for k in jp.ENV_IN}, **{k: "out" for k in jp.ENV_OUT}}


@pytest.mark.skipif(shutil.which("sh") is None, reason="no sh")
def test_env_script_writes_only_allowed_keys_and_prints_no_value(tmp_path):
    root = tmp_path / "joey"
    deploy = root / "life-dashboard" / "deploy"
    deploy.mkdir(parents=True)
    keys = sorted(set(jp.ENV_IN) | set(jp.ENV_OUT))
    (deploy / ".env").write_bytes("".join(f"{k}={SECRET}\r\n" for k in keys).encode())  # CRLF on purpose
    script = jp.s_env().replace("/volume1/Docker/joey", root.as_posix())
    r = subprocess.run(["sh", "-s"], input=script.encode(), capture_output=True, timeout=60)
    out = r.stdout.decode() + r.stderr.decode()
    assert r.returncode == 0, out
    assert SECRET not in out
    env = (root / "preview" / "preview.env").read_text(encoding="utf-8")
    assert {line.split("=", 1)[0] for line in env.splitlines()} == set(jp.ENV_IN)
    assert "\r" not in env
    assert out.splitlines()[0] == f"{len(jp.ENV_IN)} lines"
    if os.name == "posix":
        assert (root / "preview" / "preview.env").stat().st_mode & 0o777 == 0o600


# ---------- Melbourne window ----------
@pytest.mark.parametrize("utc,ok", [
    (dt.datetime(2026, 10, 22, 19, 59, tzinfo=UTC), False),   # 06:59 AEDT
    (dt.datetime(2026, 10, 22, 20, 0, tzinfo=UTC), True),     # 07:00 AEDT
    (dt.datetime(2026, 10, 23, 10, 29, tzinfo=UTC), True),    # 21:29 AEDT
    (dt.datetime(2026, 10, 23, 10, 30, tzinfo=UTC), False),   # 21:30 AEDT
    (dt.datetime(2026, 6, 1, 20, 59, tzinfo=UTC), False),     # 06:59 AEST
    (dt.datetime(2026, 6, 1, 21, 0, tzinfo=UTC), True),       # 07:00 AEST
    (dt.datetime(2026, 6, 2, 11, 29, tzinfo=UTC), True),      # 21:29 AEST
])
def test_window(utc, ok):
    assert jp.in_window(utc) is ok


def test_fallback_rule_matches_zoneinfo_across_a_year():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        zoneinfo.ZoneInfo("Australia/Melbourne")
    except Exception:
        pytest.skip("no tz database")
    t = dt.datetime(2026, 1, 1, tzinfo=UTC)
    while t.year == 2026:
        assert jp.melbourne(t, use_zoneinfo=False).utcoffset() == jp.melbourne(t).utcoffset(), t
        t += dt.timedelta(hours=1)


# ---------- up: refusals ----------
def test_up_refuses_outside_the_window_before_touching_the_nas(capsys):
    rc, nas, out, _ = run(["up", "main"], now=OUTSIDE, capsys=capsys)
    assert rc == 1 and nas.ops == []
    assert "outside the NAS window: 22:00 Melbourne" in out


def test_up_refuses_while_a_deploy_holds_the_lock(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(lock=[(0, "held 4242", "")]), capsys=capsys)
    assert rc == 1 and nas.ops == ["lock"]
    assert "a deploy holds /tmp/joey-deploy.lock" in out


def test_a_stale_lock_does_not_refuse(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(lock=[(0, "stale", "")]), capsys=capsys)
    assert rc == 0 and "stale lock" in out


def test_up_refuses_under_1400_mb(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(mem=[(0, "1399", "")]), capsys=capsys)
    assert rc == 1
    assert not CHANGE_OPS & set(nas.ops)
    assert "1399 MB is under 1400 MB" in out


def test_up_refuses_a_bad_branch_name(capsys):
    deps = jp.Deps(nas=FakeNas(), now=lambda: INSIDE, sleep=lambda s: None, log_dir=None)
    assert jp.main(["up", "feat/x;rm -rf /"], deps) == 1
    assert "bad branch name" in capsys.readouterr().out


# ---------- up: the happy path, replace, teardowns ----------
def test_up_happy_path(capsys):
    rc, nas, out, sleeps = run(["up", "main"], capsys=capsys)
    assert rc == 0, out
    assert nas.ops == ["lock", "inspect", "mem", "checkout", "build", "restore", "env", "compose-write", "up",
                       "health", "mem", "stats"]
    assert f"commit  {SHA} (branch main)" in out
    assert "URL     https://preview.joeyhome.net" in out
    assert "1600 MB before, 1450 MB after" in out and "131.2MiB" in out
    assert sleeps == []
    assert SHA in nas.scripts[nas.ops.index("checkout")]
    assert "compose -p joey-preview" in nas.scripts[nas.ops.index("up")]
    compose = (REPO_ROOT / "deploy" / "preview" / "docker-compose.yml").read_text(encoding="utf-8").rstrip()
    assert compose in nas.scripts[nas.ops.index("compose-write")]


def test_up_with_a_running_slot_replaces_it(capsys):
    nas = FakeNas(inspect=[(0, f"running|2026-10-23T01:00:00.1Z|{OLD}", "")])
    rc, nas, out, _ = run(["up", "main"], nas=nas, capsys=capsys)
    assert rc == 0, out
    assert nas.ops[:7] == ["lock", "inspect", "compose-down", "image-rm", "files-rm", "leftovers", "mem"]
    assert nas.ops.index("compose-down") < nas.ops.index("checkout")
    assert f"replacing the running slot at {OLD[:7]} with {SHA[:7]}" in out
    assert f"replaced  {OLD[:7]}" in out


def test_memory_under_the_floor_after_start_tears_down(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(mem=[(0, "1600", ""), (0, "1150", "")]), capsys=capsys)
    assert rc == 1
    assert nas.ops[-5:] == ["mem", "compose-down", "image-rm", "files-rm", "leftovers"]
    assert "1150 MB available is under the 1200 MB floor" in out


def test_no_healthz_polls_then_tears_down(capsys):
    rc, nas, out, sleeps = run(["up", "main"], nas=FakeNas(health=[(1, "", "refused")]), capsys=capsys)
    assert rc == 1
    assert nas.ops.count("health") == jp.HEALTH_TRIES
    assert sleeps == [jp.HEALTH_EVERY_S] * (jp.HEALTH_TRIES - 1)
    assert nas.ops[-5:] == ["logs", "compose-down", "image-rm", "files-rm", "leftovers"]
    assert "log: boot line" in out


def test_healthz_after_a_few_polls():
    rc, nas, _, sleeps = run(["up", "main"], nas=FakeNas(health=[(1, "", ""), (1, "", ""), (0, "", "")]))
    assert rc == 0 and nas.ops.count("health") == 3 and sleeps == [5, 5]


def test_a_failed_build_stops_before_start(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(build=[(1, "", "ERROR: failed to solve")]), capsys=capsys)
    assert rc == 1 and "up" not in nas.ops
    assert "failed to solve" in out


# ---------- dry run ----------
def test_dry_run_prints_every_step_and_changes_nothing(capsys):
    nas = FakeNas(inspect=[(0, f"running|2026-10-23T01:00:00Z|{OLD}", "")])
    rc, nas, out, sleeps = run(["up", "main", "--dry-run"], nas=nas, capsys=capsys)
    assert rc == 0, out
    assert set(nas.ops) == {"lock", "inspect", "mem"}  # read-only checks only
    for op in ("compose-down", "image-rm", "files-rm", "checkout", "build", "restore", "env", "compose-write", "up"):
        assert f"# joey-preview:{op}" in out, op
    assert "DRY RUN: nothing changed" in out
    assert "docker build -q -f hub/Dockerfile" in out and "alpine/git" in out
    assert sleeps == []


def test_output_carries_no_secret_or_ssh_target(capsys, monkeypatch):
    monkeypatch.setenv("JOEY_NAS", "root@192.0.2.10")
    nas = FakeNas(build=[(1, "", f"token={SECRET}")])
    rc, _, out, _ = run(["up", "main"], nas=nas, capsys=capsys)
    assert rc == 1
    assert SECRET not in out and "192.0.2.10" not in out


# ---------- down / status ----------
def test_down_removes_everything_and_checks(capsys):
    nas = FakeNas(inspect=[(0, f"running|2026-10-23T01:00:00Z|{SHA}", "")])
    rc, nas, out, _ = run(["down"], nas=nas, capsys=capsys)
    assert rc == 0, out
    assert nas.ops == ["inspect", "compose-down", "image-rm", "files-rm", "leftovers"]
    assert "container none, network none, image none" in out
    assert "cd / && docker compose -p joey-preview down" in nas.scripts[1]


def test_down_fails_when_something_is_left(capsys):
    nas = FakeNas(leftovers=[(0, "container=joey-preview \nnetwork=\nimage=life-hub-preview ", "")])
    rc, _, out, _ = run(["down"], nas=nas, capsys=capsys)
    assert rc == 1 and "left behind: container joey-preview, image life-hub-preview" in out


def test_down_needs_no_window(capsys):
    rc, _, _, _ = run(["down"], now=OUTSIDE, capsys=capsys)
    assert rc == 0


def test_status_running(capsys):
    nas = FakeNas(inspect=[(0, f"running|2026-10-23T01:30:00.123456789Z|{SHA}", "")], mem=[(0, "1500", "")])
    rc, nas, out, _ = run(["status"], nas=nas, capsys=capsys)
    assert rc == 0
    assert f"running, commit {SHA}, up 1h 30m, memory 131.2MiB / 256MiB" in out
    assert "1500 MB (floor 1200)" in out


def test_status_absent(capsys):
    rc, nas, out, _ = run(["status"], capsys=capsys)
    assert rc == 0 and "not running" in out and "stats" not in nas.ops
