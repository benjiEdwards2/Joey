"""JY-012: scripts/joey.py preview up / down / status against a fake NAS (no ssh, no network, no Docker).

The fake answers each NAS script by its `# joey-preview:<op>` first line and records the ops in order. The clock and
sleep are injected, so the window check and the /healthz poll run instantly. The fake also models the deploy lock
(JY-228): lock-take / lock-release set and clear its holder, `lock` reads it, and deploy_sh() answers as deploy.sh's
lock would. The real env-building and lock scripts also run under `sh` against temp paths (skipped when no `sh`)."""
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import time
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
CHANGE_OPS = {"compose-down", "image-rm", "files-rm", "checkout", "build", "restore", "env", "compose-write", "up",
              "lock-take", "lock-release"}
HOLDER = "5151"  # the fake NAS's lock holder pid
SECRET = "sk-preview-FAKE-VALUE-123"


class FakeNas:
    def __init__(self, **over):
        self.holder = None   # the deploy lock's holder pid while the preview holds it
        self.held_at = {}    # op -> was the lock held when it (last) ran
        self.on = {}         # op -> callback run when the op arrives
        self.resp = {
            "lock": None,          # None: answered from the modelled lock
            "lock-take": None,
            "lock-release": None,
            "inspect": [(0, "absent", "")],
            "mem": [(0, "1600", ""), (0, "1450", "")],
            "checkout": [(0, SHA, "")],
            "build": [(0, "sha256:abc", "")],
            "restore": [(0, "media-2026-10-22_2003.db.gz", "")],
            "env": [(0, "16 lines\nACCESS_AUD JELLYFIN_URL OMDB_API_KEY TZ", "")],
            "compose-write": [(0, "written", "")],
            "up": [(0, "", "Container joey-preview Started")],
            "health": [(0, "", "")],
            "stats": [(0, "131.2MiB / 256MiB", "")],
            "logs": [(0, "boot line", "")],
            "compose-down": [(0, "", "")],
            "image-rm": [(0, "removed", "")],
            "files-rm": [(0, "removed", "")],
            "leftovers": [(0, "container=\nnetwork=\nimage=\nfiles=", "")],
        }
        self.resp.update(over)
        self.ops, self.scripts, self.timeouts = [], [], []

    def deploy_sh(self):
        """What deploy.sh's lock does right now: 2 ("another deploy is running") while the preview holds it."""
        return 2 if self.holder else 0

    def __call__(self, script, timeout=60):
        assert script.startswith("# joey-preview:")
        op = script.splitlines()[0].split(":", 1)[1]
        self.ops.append(op)
        self.scripts.append(script)
        self.timeouts.append(timeout)
        self.held_at[op] = self.holder is not None
        if op in self.on:
            self.on[op]()
        seq = self.resp[op]
        if op == "lock-take":
            self.token = re.search(r'echo ([0-9a-f]{16}) > "\$L/owner"', script).group(1)
        if op == "lock-release":
            assert f"t={self.token}\n" in script  # the release names the token this run's take wrote
        if seq is None:
            if op == "lock-take":
                self.holder = HOLDER
                return 0, f"taken {HOLDER}", ""
            if op == "lock-release":
                if self.holder is None:
                    return 0, "not ours", ""
                self.holder = None
                return 0, "released", ""
            return 0, (f"held {self.holder}" if self.holder else "free"), ""
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, BaseException):
            raise item
        return item


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
              "CLOUDFLARE_API_TOKEN", "AWARDS_CONTACT", "ICS_URL_YOU", "ICS_URL_HER", "JELLYFIN_API_KEY"):
        assert k in jp.ENV_OUT, k


def test_read_keys_the_spec_names_are_in():
    for k in ("JELLYFIN_URL", "OMDB_API_KEY", "WEATHER_LAT", "WEATHER_LON", "ACCESS_AUD", "TZ"):
        assert k in jp.ENV_IN, k


def test_jellyfin_key_is_out():
    # 2026-10-23 JY-012 review (orchestrator, rule 7): the key reaches live writes in hub/media_resume.py act()
    assert "JELLYFIN_API_KEY" in jp.ENV_OUT


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
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(**{"lock-take": [(0, "held 4242", "")]}), capsys=capsys)
    assert rc == 1 and nas.ops == ["lock-take"]  # nothing else ran, and nothing to release
    assert "a deploy holds /tmp/joey-deploy.lock (pid 4242)" in out


def test_a_stale_lock_does_not_refuse(capsys):
    nas = FakeNas(**{"lock-take": [(0, f"taken {HOLDER} stale 4242", "")], "lock": [(0, f"held {HOLDER}", "")],
                     "lock-release": [(0, "released", "")]})
    rc, nas, out, _ = run(["up", "main"], nas=nas, capsys=capsys)
    assert rc == 0 and "cleared a stale lock (pid 4242 gone)" in out


def test_up_refuses_under_1400_mb(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(mem=[(0, "1399", "")]), capsys=capsys)
    assert rc == 1
    assert not (CHANGE_OPS - {"lock-take", "lock-release"}) & set(nas.ops)
    assert nas.ops == ["lock-take", "inspect", "mem", "lock-release"]  # only the lock changed, and it is released
    assert nas.holder is None
    assert "1399 MB is under 1400 MB" in out


def test_up_refuses_a_bad_branch_name(capsys):
    deps = jp.Deps(nas=FakeNas(), now=lambda: INSIDE, sleep=lambda s: None, log_dir=None)
    assert jp.main(["up", "feat/x;rm -rf /"], deps) == 1
    assert "bad branch name" in capsys.readouterr().out


# ---------- up: the happy path, replace, teardowns ----------
def test_up_happy_path(capsys):
    rc, nas, out, sleeps = run(["up", "main"], capsys=capsys)
    assert rc == 0, out
    assert nas.ops == ["lock-take", "inspect", "mem", "checkout", "build", "restore", "env", "compose-write", "lock",
                       "up", "health", "mem", "stats", "lock-release"]
    assert nas.holder is None
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
    assert nas.ops[:7] == ["lock-take", "inspect", "compose-down", "image-rm", "files-rm", "leftovers", "mem"]
    assert nas.ops.index("compose-down") < nas.ops.index("checkout")
    assert f"replacing the running slot at {OLD[:7]} with {SHA[:7]}" in out
    assert f"replaced  {OLD[:7]}" in out


def test_memory_under_the_floor_after_start_tears_down(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(mem=[(0, "1600", ""), (0, "1150", "")]), capsys=capsys)
    assert rc == 1
    assert nas.ops[-6:] == ["mem", "compose-down", "image-rm", "files-rm", "leftovers", "lock-release"]
    assert "1150 MB available is under the 1200 MB floor" in out


def test_no_healthz_polls_then_tears_down(capsys):
    rc, nas, out, sleeps = run(["up", "main"], nas=FakeNas(health=[(1, "", "refused")]), capsys=capsys)
    assert rc == 1
    assert nas.ops.count("health") == jp.HEALTH_TRIES
    assert sleeps == [jp.HEALTH_EVERY_S] * (jp.HEALTH_TRIES - 1)
    assert nas.ops[-6:] == ["logs", "compose-down", "image-rm", "files-rm", "leftovers", "lock-release"]
    assert "log: boot line" in out


def test_healthz_after_a_few_polls():
    rc, nas, _, sleeps = run(["up", "main"], nas=FakeNas(health=[(1, "", ""), (1, "", ""), (0, "", "")]))
    assert rc == 0 and nas.ops.count("health") == 3 and sleeps == [5, 5]


def test_a_failed_build_stops_before_start(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(build=[(1, "", "ERROR: failed to solve")]), capsys=capsys)
    assert rc == 1 and "up" not in nas.ops
    assert nas.ops[-2:] == ["build", "lock-release"]
    assert "failed to solve" in out


# ---------- dry run ----------
def test_dry_run_prints_every_step_and_changes_nothing(capsys):
    nas = FakeNas(inspect=[(0, f"running|2026-10-23T01:00:00Z|{OLD}", "")])
    rc, nas, out, sleeps = run(["up", "main", "--dry-run"], nas=nas, capsys=capsys)
    assert rc == 0, out
    assert set(nas.ops) == {"lock", "inspect", "mem"}  # read-only checks only
    for op in ("compose-down", "image-rm", "files-rm", "checkout", "build", "restore", "env", "compose-write", "up",
               "lock-take", "lock-release"):
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
    assert "container none, network none, image none, media.db copy and preview.env gone" in out
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


# ---------- review fixes (2026-10-23) ----------
@pytest.mark.skipif(shutil.which("sh") is None, reason="no sh")
def test_env_script_never_glues_a_hub_env_secret_onto_an_allowed_key(tmp_path):
    # must-fix 1: .env without a trailing newline used to glue its last line to hub.env's first line
    root = tmp_path / "joey"
    deploy = root / "life-dashboard" / "deploy"
    deploy.mkdir(parents=True)
    (deploy / ".env").write_bytes(b"JELLYFIN_URL=http://lan\nTZ=Australia/Melbourne")  # no trailing newline
    (deploy / "hub.env").write_bytes(f"RADARR_API_KEY={SECRET}\nOMDB_API_KEY=ok\n".encode())
    script = jp.s_env().replace("/volume1/Docker/joey", root.as_posix())
    r = subprocess.run(["sh", "-s"], input=script.encode(), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    env = (root / "preview" / "preview.env").read_text(encoding="utf-8")
    assert SECRET not in env
    assert sorted(env.splitlines()) == ["JELLYFIN_URL=http://lan", "OMDB_API_KEY=ok", "TZ=Australia/Melbourne"]


TEARDOWN = ["compose-down", "image-rm", "files-rm", "leftovers", "lock-release"]  # the lock goes last


def test_a_failed_compose_up_tears_down(capsys):
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(up=[(1, "", "Error response from daemon")]), capsys=capsys)
    assert rc == 1
    assert nas.ops[nas.ops.index("up") + 1:] == TEARDOWN
    assert "tearing the slot down" in out


def test_an_ssh_error_during_the_healthz_poll_tears_down(capsys):
    nas = FakeNas(health=[RuntimeError("ssh to the NAS failed")])
    rc, nas, out, _ = run(["up", "main"], nas=nas, capsys=capsys)
    assert rc == 1
    assert nas.ops[nas.ops.index("health") + 1:] == TEARDOWN


def test_a_timeout_during_the_healthz_poll_tears_down():
    nas = FakeNas(health=[subprocess.TimeoutExpired("ssh", 30)])
    rc, nas, _, _ = run(["up", "main"], nas=nas)
    assert rc == 1 and nas.ops[-5:] == TEARDOWN


def test_a_failed_env_build_tears_down_the_media_db_copy():
    rc, nas, _, _ = run(["up", "main"], nas=FakeNas(env=[(3, "", "no live .env")]))
    assert rc == 1
    assert nas.ops[nas.ops.index("env") + 1:] == TEARDOWN


def test_teardown_runs_every_step_even_when_one_fails():
    nas = FakeNas(up=[(1, "", "boom")], **{"compose-down": [RuntimeError("ssh to the NAS failed")]})
    rc, nas, _, _ = run(["up", "main"], nas=nas)
    assert rc == 1 and nas.ops[-5:] == TEARDOWN


def test_a_failed_build_leaves_nothing_to_tear_down():
    rc, nas, _, _ = run(["up", "main"], nas=FakeNas(build=[(1, "", "ERROR")]))
    assert rc == 1 and nas.ops[-2:] == ["build", "lock-release"]


def test_the_lock_is_checked_again_before_compose_up(capsys):
    # JY-228: the preview holds the lock itself, so the second check asks "still ours?" (say the holder expired and a
    # deploy took it): refuse and tear down
    nas = FakeNas(lock=[(0, "held 777", "")])
    rc, nas, out, _ = run(["up", "main"], nas=nas, capsys=capsys)
    assert rc == 1
    assert nas.ops.count("lock") == 1 and "up" not in nas.ops
    assert nas.ops.index("lock") > nas.ops.index("build")
    assert nas.ops[-5:] == TEARDOWN and "no longer this preview's" in out and "held 777" in out


def test_docker_commands_in_nas_scripts_read_dev_null():
    scripts = [jp.s_inspect(), jp.s_stats(), jp.s_checkout(SHA), jp.s_build(SHA), jp.s_up(SHA), jp.s_health(),
               jp.s_logs(), jp.s_down(), jp.s_image_rm(), jp.s_leftovers()]
    for text in scripts:
        for line in text.replace('\\\n', " ").splitlines():  # join continued lines
            if re.search(r"\bdocker (run|exec|build|compose|inspect|stats|logs|rm|image|ps|network)\b", line) \
                    and not line.strip().startswith("#"):
                assert "</dev/null" in line, line


def test_dry_run_goes_on_past_a_refusing_check(capsys):
    nas = FakeNas(lock=[(0, "held 9", "")], mem=[(0, "900", "")])
    rc, nas, out, _ = run(["up", "main", "--dry-run"], now=OUTSIDE, nas=nas, capsys=capsys)
    assert rc == 0, out
    assert "a real run would stop here: outside the NAS window" in out
    assert "a real run would stop here: a deploy holds" in out
    assert "a real run would stop here: NAS available memory 900 MB" in out
    for op in ("checkout", "build", "restore", "env", "compose-write", "up"):
        assert f"# joey-preview:{op}" in out, op


def test_dry_run_with_the_nas_unreachable_still_prints_every_step(capsys):
    class Off:
        def __call__(self, script, timeout=60):
            raise RuntimeError("ssh to the NAS failed (NAS off 22:00-07:00, or off the home LAN?): timed out")

    rc, _, out, _ = run(["up", "main", "--dry-run"], nas=Off(), capsys=capsys)
    assert rc == 0, out
    assert out.count("a real run would stop here: ssh to the NAS failed") == 4  # lock, slot, memory, lock again
    for op in ("checkout", "build", "restore", "env", "compose-write", "up"):
        assert f"# joey-preview:{op}" in out, op


def test_dry_run_with_an_unresolved_ref_still_prints_every_step(capsys):
    deps = jp.Deps(nas=FakeNas(), now=lambda: INSIDE, sleep=lambda s: None, log_dir=None)
    assert jp.main(["up", "feat/x;rm", "--dry-run"], deps) == 0
    out = capsys.readouterr().out
    assert "bad branch name" in out and "# joey-preview:up" in out


def test_down_fails_when_the_media_db_copy_or_env_is_left(capsys):
    nas = FakeNas(leftovers=[(0, f"container=\nnetwork=\nimage=\nfiles={jp.ENV_FILE} ", "")])
    rc, _, out, _ = run(["down"], nas=nas, capsys=capsys)
    assert rc == 1 and f"left behind: files {jp.ENV_FILE}" in out


# ---------- the ssh transport (joey_common.ssh_run) ----------
def test_nas_sh_runs_sh_on_the_shared_ssh_run(monkeypatch):
    calls = []
    monkeypatch.setattr(jp.jc, "ssh_run", lambda cmd, stdin=None, timeout=60: calls.append((cmd, stdin)) or
                        subprocess.CompletedProcess(cmd, 0, " ok \n", ""))
    assert jp.nas_sh(jp.s_mem()) == (0, "ok", "")
    assert calls == [("sh -s", jp.s_mem())]


def test_ssh_run_delivers_an_lf_payload_unchanged(monkeypatch, tmp_path):
    # must-fix 4: Windows text-mode stdin turned LF into CRLF. The fake ssh is a real child process reading its stdin.
    real_run = subprocess.run
    dump = tmp_path / "stdin.bin"
    child = f"import sys; open({str(dump)!r}, 'wb').write(sys.stdin.buffer.read()); print('h\\u00e9')"

    def fake_run(cmd, **kw):
        return real_run([sys.executable, "-c", child], env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **kw)

    monkeypatch.setattr(jp.jc.subprocess, "run", fake_run)
    payload = "set -eu\necho café\n"
    r = jp.jc.ssh_run("sh -s", stdin=payload)
    assert dump.read_bytes() == payload.encode("utf-8")
    assert r.returncode == 0 and r.stdout.strip() == "hé" and isinstance(r.stderr, str)


def test_ssh_run_error_hides_the_nas_user_and_host(monkeypatch):
    monkeypatch.setenv("JOEY_NAS", "admin@192.0.2.10")
    monkeypatch.setattr(jp.jc.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 255, b"", b"ssh: connect to host 192.0.2.10 port 22: timed out; admin@192.0.2.10 denied\n"))
    with pytest.raises(RuntimeError) as e:
        jp.jc.ssh_run("true")
    msg = str(e.value)
    assert "192.0.2.10" not in msg and "admin" not in msg and "<nas>" in msg


# ---------- JY-228: the preview holds the deploy lock while it checks out, builds and starts ----------
HELD_OPS = ("inspect", "mem", "checkout", "build", "restore", "env", "compose-write", "lock", "up", "health", "stats")


def test_the_lock_is_held_from_checkout_to_start_and_a_deploy_meanwhile_exits_2():
    nas = FakeNas()
    deploys = []
    for op in ("checkout", "build", "up"):
        nas.on[op] = lambda: deploys.append(nas.deploy_sh())  # a deploy.sh started during each step
    rc, nas, _, _ = run(["up", "main"], nas=nas)
    assert rc == 0
    assert deploys == [2, 2, 2]
    assert all(nas.held_at[op] for op in HELD_OPS), nas.held_at
    assert nas.ops[0] == "lock-take" and nas.ops[-1] == "lock-release"
    assert nas.holder is None and nas.deploy_sh() == 0  # released: the next deploy runs


@pytest.mark.parametrize("over", [
    {"build": [(1, "", "ERROR: failed to solve")]},                      # failure before the restore
    {"checkout": [RuntimeError("ssh to the NAS failed")]},              # ssh error
    {"health": [(1, "", "refused")]},                                   # teardown after the start
    {"up": [(1, "", "boom")], "compose-down": [RuntimeError("ssh")]},   # teardown with a failing step
    {"inspect": [(0, f"running|2026-10-23T01:00:00Z|{OLD}", "")],       # the replace fails
     "leftovers": [(0, "container=joey-preview \nnetwork=\nimage=\nfiles=", "")]},
])
def test_the_lock_is_released_on_every_failure(over):
    rc, nas, _, _ = run(["up", "main"], nas=FakeNas(**over))
    assert rc == 1
    assert nas.ops[-1] == "lock-release" and nas.ops.count("lock-release") == 1
    assert nas.holder is None


def test_the_lock_is_released_when_the_run_is_interrupted():
    nas = FakeNas(build=[KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        run(["up", "main"], nas=nas)
    assert nas.ops[-1] == "lock-release" and nas.holder is None


def test_a_failed_release_fails_the_run_and_keeps_the_first_error(capsys):
    nas = FakeNas(build=[(1, "", "ERROR: failed to solve")], **{"lock-release": [(1, "", "holder 5151 did not stop")]})
    rc, _, out, _ = run(["up", "main"], nas=nas, capsys=capsys)
    assert rc == 1
    assert "FAIL  release the deploy lock - RuntimeError: exit 1: holder 5151 did not stop" in out
    assert "REFUSED: RuntimeError: exit 1: ERROR: failed to solve" in out


def test_a_failed_release_after_a_good_start_is_a_fail(capsys):
    rc, _, out, _ = run(["up", "main"], nas=FakeNas(**{"lock-release": [(1, "", "holder 5151 did not stop")]}),
                        capsys=capsys)
    assert rc == 1 and "FAIL  release the deploy lock" in out


def test_an_odd_lock_answer_fails_and_releases_by_token():
    rc, nas, _, _ = run(["up", "main"], nas=FakeNas(**{"lock-take": [(0, "taken x;y", "")]}))
    assert rc == 1 and nas.ops == ["lock-take", "lock-release"]  # a holder may have started: released by token


@pytest.mark.parametrize("err", [subprocess.TimeoutExpired("ssh", 60), RuntimeError("ssh to the NAS failed")])
def test_a_take_that_errors_is_released_by_token(err, capsys):
    # reviewer A: the take's answer can be lost after the holder started; the release finds the lock by this run's token
    rc, nas, out, _ = run(["up", "main"], nas=FakeNas(**{"lock-take": [err]}), capsys=capsys)
    assert rc == 1 and nas.ops == ["lock-take", "lock-release"]
    assert "this run holds no lock (nothing to release)" in out


def test_each_run_has_its_own_token():
    assert run(["up", "main"])[1].token != run(["up", "main"])[1].token


TOKEN = "0123456789abcdef"
OTHER = "fedcba9876543210"


def test_lock_scripts_use_deploy_sh_format():
    take, release = jp.s_lock_take(SHA, TOKEN), jp.s_lock_release(TOKEN)
    deploy_sh = (REPO_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    assert f"LOCK={jp.LOCK}" in deploy_sh and 'echo "$$" > "$LOCK/pid"' in deploy_sh
    assert f"L={jp.LOCK}" in take and 'mkdir "$L"' in take
    # the holder writes its own pid, as deploy.sh does. JY-234, 2026-10-24: via a temp file and an atomic mv after
    # the owner check (was `echo $$ > LOCK/pid`), so it never lands in a lock someone else took meanwhile
    assert f"echo $$ > {jp.LOCK}/.pid.$$" in take and f"mv -f {jp.LOCK}/.pid.$$ {jp.LOCK}/pid" in take
    assert f'echo {jp.LOCK_NOTE} > "$L/log"' in take
    assert f'echo {TOKEN} > "$L/owner"' in take and f"t={TOKEN}\n" in release
    assert "-mmin +30" in take  # deploy.sh's stale rule for a pid-less lock
    assert jp.SH_ALIVE in take and jp.SH_ALIVE in release  # a zombie holder is dead
    holder = re.search(r"sh -c '([^']*)'", take).group(1)
    assert "'" not in holder and f"sleep {jp.LOCK_HOLD_S}" in holder and TOKEN in holder
    assert "docker" not in take.replace("/volume1/Docker", "") + release  # nothing can read the script's stdin


# ---------- the lock scripts under a real sh (deploy.sh's own lock block decides) ----------
def deploy_lock_block():
    """deploy.sh's lock-taking lines, cut from the real file: from `LOCK=` to just before it writes its pid."""
    text = (REPO_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    start = text.index(f"LOCK={jp.LOCK}\n")
    end = text.index('echo "$$" > "$LOCK/pid"', start)
    return text[start:end]


@pytest.fixture
def nas_tmp(tmp_path):
    """Runs a NAS script under sh with /tmp/joey-deploy.lock and /volume1/Docker/joey moved into tmp_path, and /proc
    optionally swapped for a fake one. Every holder or helper process a test starts is killed at teardown."""
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    lock = (tmp_path / "joey-deploy.lock").as_posix()
    root = (tmp_path / "joey").as_posix()
    started = []

    def sh(script, timeout=60, proc=None):
        script = script.replace(jp.LOCK, lock).replace("/volume1/Docker/joey", root)
        if proc:
            script = script.replace('"/proc/', f'"{proc}/')
        r = subprocess.run(["sh", "-s"], input=script.encode(), capture_output=True, timeout=timeout)
        out = r.stdout.decode().strip()
        if out.startswith("taken"):
            started.append(out.split()[1])
        return r.returncode, out, r.stderr.decode().strip()

    def deploy():
        block = deploy_lock_block().replace(jp.LOCK, lock)
        return sh(f"DEPLOY_DIR={root}/life-dashboard/deploy\n{block}echo got-the-lock\n")

    def background(cmd):
        """Start cmd detached; return its pid (killed at teardown)."""
        pid = sh(f"{cmd} </dev/null >/dev/null 2>&1 &\necho $!\n")[1]
        started.append(pid)
        return pid

    def alive(pid, proc=None):
        return sh(f"{jp.SH_ALIVE}\nalive {pid} && echo yes || echo no\n", proc=proc)[1] == "yes"

    sh.deploy, sh.background, sh.alive, sh.lock, sh.started = deploy, background, alive, Path(lock), started
    yield sh
    if started:
        sh(f"kill {' '.join(started)} 2>/dev/null; true")


def fake_lock(sh, pid, owner=None):
    sh.lock.mkdir()
    (sh.lock / "pid").write_text(f"{pid}\n")
    if owner:
        (sh.lock / "owner").write_text(f"{owner}\n")


def test_real_take_blocks_deploy_sh_and_release_frees_it(nas_tmp):
    sh = nas_tmp
    rc, out, err = sh(jp.s_lock_take(SHA, TOKEN))
    assert rc == 0 and re.fullmatch(r"taken [0-9]+", out), (out, err)
    pid = out.split()[1]
    assert (sh.lock / "pid").read_text().strip() == pid and sh.alive(pid)
    assert (sh.lock / "owner").read_text().strip() == TOKEN
    assert (sh.lock / "log").read_text().strip().endswith("/preview/lock.log")
    rc, out, _ = sh.deploy()
    assert rc == 2 and f"another deploy is running (pid {pid}" in out
    assert sh(jp.s_lock())[1] == f"held {pid}"  # what the second check reads
    closeout_wait = f'p=$(cat {jp.LOCK}/pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo $p || true'
    assert sh(closeout_wait)[1] == pid  # scripts/joey_closeout.py's idle() lock_cmd: close-out waits
    assert sh(jp.s_lock_take(SHA, OTHER))[1] == f"held {pid}"  # a second preview refuses too
    rc, out, err = sh(jp.s_lock_release(TOKEN))
    assert (rc, out) == (0, "released"), err
    assert not sh.lock.exists() and not sh.alive(pid)
    rc, out, _ = sh.deploy()
    assert rc == 0 and out.endswith("got-the-lock")


def test_real_take_refuses_a_live_deploy_and_leaves_its_lock(nas_tmp):
    sh = nas_tmp
    deploy_pid = sh.background("sleep 30")
    try:
        fake_lock(sh, deploy_pid)
        assert sh(jp.s_lock_take(SHA, TOKEN))[1] == f"held {deploy_pid}"
        assert sh(jp.s_lock_release(TOKEN))[1] == "not ours"  # a lock without our token is never touched
        assert (sh.lock / "pid").read_text().strip() == deploy_pid and sh.alive(deploy_pid)
    finally:
        sh(f"kill {deploy_pid} 2>/dev/null; true")


def test_real_release_never_touches_another_runs_lock(nas_tmp):
    sh = nas_tmp
    pid = sh(jp.s_lock_take(SHA, TOKEN))[1].split()[1]
    assert sh(jp.s_lock_release(OTHER))[1] == "not ours"
    assert (sh.lock / "pid").read_text().strip() == pid and sh.alive(pid)
    assert sh(jp.s_lock_release(TOKEN))[1] == "released" and not sh.lock.exists()


def test_real_release_after_a_lost_take_answer(nas_tmp):
    # reviewer A: the take ran (holder up) but its answer never reached the laptop; the token still finds it
    sh = nas_tmp
    sh(jp.s_lock_take(SHA, TOKEN))
    pid = (sh.lock / "pid").read_text().strip()
    assert sh(jp.s_lock_release(TOKEN))[1] == "released"
    assert not sh.lock.exists() and not sh.alive(pid)


def test_real_take_clears_a_stale_lock(nas_tmp):
    sh = nas_tmp
    dead = sh("sh -c 'exit 0' & p=$!; wait $p; echo $p\n")[1]  # a pid that has just died
    fake_lock(sh, dead)
    rc, out, err = sh(jp.s_lock_take(SHA, TOKEN))
    assert rc == 0 and re.fullmatch(rf"taken [0-9]+ stale {dead}", out), (out, err)
    assert sh(jp.s_lock_release(TOKEN))[1] == "released" and not sh.lock.exists()


def test_real_release_removes_the_lock_of_a_holder_killed_hard(nas_tmp):
    sh = nas_tmp
    pid = sh(jp.s_lock_take(SHA, TOKEN))[1].split()[1]
    sh(f"kill -9 {pid}")
    assert sh.lock.exists()  # the holder could not clean up
    assert sh(jp.s_lock_release(TOKEN))[1] == "released"
    assert not sh.lock.exists()  # never a dead-pid lock left


def test_real_holder_gives_the_lock_up_by_itself(nas_tmp, monkeypatch):
    # JY-239: the holder removes the lock in its EXIT trap and exits a moment later, so under CI load "lock gone" can
    # come before "holder gone". Poll for both (a generous deadline, never a fixed wait), then assert both.
    sh = nas_tmp
    monkeypatch.setattr(jp, "LOCK_HOLD_S", 1)
    pid = sh(jp.s_lock_take(SHA, TOKEN))[1].split()[1]
    deadline = time.monotonic() + 60
    while (sh.lock.exists() or sh.alive(pid)) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not sh.lock.exists() and not sh.alive(pid)


def test_real_zombie_holder_counts_as_dead_fake_proc(nas_tmp, tmp_path):
    # reviewer B: the gate container (no --init) never reaps the orphaned holder and kill -0 succeeds on a zombie.
    # A live process stands in for the zombie; a fake /proc says its state is Z. Like a zombie, it does not die on the
    # release's TERM (TERM ignored), so the release can only succeed by counting it dead: otherwise it ends "holder
    # did not stop", exit 1. JY-239, 2026-10-24: this replaces a wall-clock "< 4 s" check that failed under load.
    sh = nas_tmp
    ready = tmp_path / "ready"  # written once TERM is ignored: a TERM sent before that would kill it (JY-239)
    zombie = sh.background(f"""sh -c 'trap "" TERM; : > {ready.as_posix()}; exec sleep 60'""")
    try:
        deadline = time.monotonic() + 60
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        proc = tmp_path / "proc"
        (proc / zombie).mkdir(parents=True)
        (proc / zombie / "stat").write_text(f"{zombie} (sh) Z 1 {zombie} {zombie} 0 -1 4194560\n")
        fake = proc.as_posix()
        sh(f"kill {zombie}")
        assert sh.alive(zombie) and not sh.alive(zombie, proc=fake)  # TERM did not stop it
        fake_lock(sh, zombie, owner=TOKEN)
        rc, out, err = sh(jp.s_lock_release(TOKEN), proc=fake)
        assert (rc, out) == (0, "released"), err
        assert not sh.lock.exists() and sh.alive(zombie)
        fake_lock(sh, zombie)  # a zombie's lock is stale for the next take, too
        rc, out, err = sh(jp.s_lock_take(SHA, TOKEN), proc=fake)
        assert rc == 0 and out.endswith(f"stale {zombie}"), (out, err)
        assert sh(jp.s_lock_release(TOKEN))[1] == "released"
    finally:
        sh(f"kill -9 {zombie} 2>/dev/null; true")


LINUX_PROC = sys.platform.startswith("linux") and Path("/proc/self/stat").exists()


def proc_state(pid):
    """The state letter from /proc/<pid>/stat; "" once the pid is gone (reaped) or not readable."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1][:1]
    except (OSError, IndexError):
        return ""


@pytest.mark.skipif(not LINUX_PROC, reason="needs Linux /proc")
def test_real_zombie_holder_counts_as_dead(nas_tmp):
    # JY-239: the zombie is this test's own child, never waited for until the end, so nothing can reap it mid-test (the
    # old sh-made zombie could be reaped by its shell, then reading its /proc stat raised FileNotFoundError).
    sh = nas_tmp
    child = subprocess.Popen(["sleep", "0"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    try:
        zombie = str(child.pid)
        deadline = time.monotonic() + 60
        while proc_state(zombie) != "Z" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert proc_state(zombie) == "Z"
        assert sh(f"kill -0 {zombie} && echo yes")[1] == "yes" and not sh.alive(zombie)
        fake_lock(sh, zombie, owner=TOKEN)
        rc, out, err = sh(jp.s_lock_release(TOKEN))
        assert (rc, out) == (0, "released"), err
        assert not sh.lock.exists()
    finally:
        child.wait(timeout=60)


def test_a_pid_gone_from_proc_counts_as_dead(nas_tmp, tmp_path):
    # JY-239: kill -0 can pass just before the pid is reaped; with /proc mounted, a missing /proc/<pid> means dead.
    # A fake /proc holds only `self/stat`, so a live pid's directory is "gone" there.
    sh = nas_tmp
    live = sh.background("sleep 30")
    try:
        proc = tmp_path / "proc"
        (proc / "self").mkdir(parents=True)
        (proc / "self" / "stat").write_text("1 (sh) S 0\n")
        assert sh.alive(live) and not sh.alive(live, proc=proc.as_posix())
        assert sh.alive(live, proc=(tmp_path / "no-proc").as_posix())  # no /proc at all: kill -0 decides
    finally:
        sh(f"kill {live} 2>/dev/null; true")


@pytest.mark.parametrize("stat", ["", None], ids=["empty-stat", "no-stat-file"])
def test_a_pid_whose_stat_cannot_be_read_counts_as_alive(nas_tmp, tmp_path, stat):
    # JY-239 fix round (orchestrator must-fix): /proc/<pid> exists but its stat reads empty (a failed sed/cut fork
    # under load, an unreadable file): fail safe, ALIVE, so a live deploy's lock is never taken as stale.
    sh = nas_tmp
    live = sh.background("sleep 30")
    try:
        proc = tmp_path / "proc"
        (proc / "self").mkdir(parents=True)
        (proc / "self" / "stat").write_text("1 (sh) S 0\n")
        (proc / live).mkdir()
        if stat is not None:
            (proc / live / "stat").write_text(stat)
        fake = proc.as_posix()
        assert sh.alive(live, proc=fake)
        fake_lock(sh, live)
        assert sh(jp.s_lock_take(SHA, TOKEN), proc=fake)[1] == f"held {live}"  # the deploy's lock stands
        assert (sh.lock / "pid").read_text().strip() == live
    finally:
        sh(f"kill {live} 2>/dev/null; true")


def test_jellyfin_url_reason_is_accurate():
    reason = jp.ENV_IN["JELLYFIN_URL"]
    assert "every Jellyfin call is refused" not in reason
    assert "fail visibly" in reason and "guest sign-in is off" in reason and "private front" in reason


# ---------- JY-234: the JY-228 verifier's low-probability should-fixes ----------
import joey_closeout  # noqa: E402


def lock_window_s(nas, sleeps):
    """Worst-case seconds the lock is held for one run: every NAS call's timeout from the take to the release, as if
    each step ran right up to it, plus the laptop's own sleeps."""
    i, j = nas.ops.index("lock-take"), len(nas.ops) - 1 - nas.ops[::-1].index("lock-release")
    return sum(nas.timeouts[i:j + 1]) + sum(sleeps)


RUNNING = [(0, f"running|2026-10-23T01:00:00Z|{OLD}", "")]
LAST_POLL = [(1, "", "")] * (jp.HEALTH_TRIES - 1) + [(0, "", "")]


@pytest.mark.parametrize("over", [
    {"inspect": RUNNING, "health": [(1, "", "refused")]},                                # no /healthz: logs + teardown
    {"inspect": RUNNING, "health": list(LAST_POLL), "mem": [(0, "1600", ""), (0, "1150", "")]},  # last poll, floor
    {"inspect": RUNNING, "health": list(LAST_POLL)},                                     # good, on the last poll
], ids=["no-healthz", "under-floor", "last-poll"])
def test_the_hold_outlasts_every_step_timeout_and_close_out_waits_longer(over):
    # point 3: the holder must not give the lock up while the run can still be working (replace, build, health poll,
    # teardown); and close-out's wait for the lock must outlast the hold, so a dead laptop never fails a close-out.
    rc, nas, _, sleeps = run(["up", "main"], nas=FakeNas(**over))
    assert nas.ops[-1] == "lock-release" and "compose-down" in nas.ops
    worst = lock_window_s(nas, sleeps)
    assert worst > 60 * 60  # the measure saw the 30 min build and the 14 min health poll
    assert worst + 5 * 60 <= jp.LOCK_HOLD_S, (worst, jp.LOCK_HOLD_S)  # at least 5 min to spare
    assert jp.LOCK_HOLD_S < joey_closeout.build_parser().parse_args(["JY-001"]).timeout * 60
    assert f"sleep {jp.LOCK_HOLD_S} " in jp.s_lock_take(SHA, TOKEN)


def holder_of(take):
    return re.search(r"sh -c '([^']*)'", take).group(1)


def test_real_take_leaves_no_temp_pid_file(nas_tmp):
    # point 2: the pid goes in by rename; nothing else is left in the lock dir
    sh = nas_tmp
    pid = sh(jp.s_lock_take(SHA, TOKEN))[1].split()[1]
    assert sorted(p.name for p in sh.lock.iterdir()) == ["log", "owner", "pid"]
    assert (sh.lock / "pid").read_text().strip() == pid
    assert sh(jp.s_lock_release(TOKEN))[1] == "released" and not sh.lock.exists()


def test_holder_never_writes_its_pid_into_a_lock_replaced_before_the_rename(nas_tmp, monkeypatch):
    # point 2: a deploy clears the lock and takes its own between the holder's owner check and its rename (a stand-in
    # `mv` does that first, then the real mv). The temp file went with the old dir: the mv fails, the holder exits and
    # the deploy's pid stands.
    sh = nas_tmp
    monkeypatch.setattr(jp, "LOCK_HOLD_S", 1)  # a holder that wrongly carried on gives up at once
    fake_lock(sh, "1", owner=TOKEN)
    (sh.lock / "pid").unlink()
    deploy_takes = f'mv() {{ rm -rf {jp.LOCK}; mkdir {jp.LOCK}; echo 4242 > {jp.LOCK}/pid; command mv "$@"; }}'
    rc, out, err = sh(f"{deploy_takes}\n{holder_of(jp.s_lock_take(SHA, TOKEN))}\n")
    assert rc == 0, (out, err)
    assert sorted(p.name for p in sh.lock.iterdir()) == ["pid"]
    assert (sh.lock / "pid").read_text().strip() == "4242"


def test_holder_whose_lock_changed_owner_after_the_temp_write_leaves_nothing(nas_tmp, monkeypatch):
    # point 2: the owner changes between the temp write and the second check (a stand-in `echo` changes it right
    # after writing): no pid written, the temp file removed
    sh = nas_tmp
    monkeypatch.setattr(jp, "LOCK_HOLD_S", 1)
    fake_lock(sh, "1", owner=TOKEN)
    (sh.lock / "pid").unlink()
    swap = f"echo() {{ printf '%s\\n' \"$*\"; printf '%s\\n' {OTHER} > {jp.LOCK}/owner; }}"
    rc, out, err = sh(f"{swap}\n{holder_of(jp.s_lock_take(SHA, TOKEN))}\n")
    assert rc == 0, (out, err)
    assert sorted(p.name for p in sh.lock.iterdir()) == ["owner"]
    assert (sh.lock / "owner").read_text().strip() == OTHER


FAKE_PID = "4242"


def fake_proc(tmp_path, cmdline, state="S"):
    """A fake /proc where FAKE_PID is alive (state S) with the given command line (NUL-separated, as the kernel)."""
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "stat").write_text("1 (sh) S 0\n")
    (proc / FAKE_PID).mkdir()
    (proc / FAKE_PID / "stat").write_text(f"{FAKE_PID} (sh) {state} 1 {FAKE_PID} {FAKE_PID} 0 -1 4194560\n")
    (proc / FAKE_PID / "cmdline").write_bytes(cmdline)
    return proc.as_posix()


def stand_ins(tmp_path, fractional=True):
    """Shell functions that replace kill (every pid exists, nothing ever dies, each call is logged) and sleep (returns
    at once, logs its argument; rejects a fractional one unless `fractional`, as a whole-seconds-only sleep does)."""
    kills, naps = (tmp_path / "kills.log").as_posix(), (tmp_path / "naps.log").as_posix()
    frac = "" if fractional else 'case "$1" in *.*) return 1;; esac; '
    text = (f'kill() {{ printf "%s\\n" "$*" >> {kills}; return 0; }}\n'
            f'sleep() {{ {frac}printf "%s\\n" "$1" >> {naps}; return 0; }}\n')
    return text, Path(kills), Path(naps)


def log_lines(path):
    return path.read_text().splitlines() if path.exists() else []


@pytest.mark.parametrize("cmdline", [b"sleep\x0030\x00", None], ids=["reused-pid", "no-proc"])
def test_release_never_signals_a_pid_that_is_not_its_holder(nas_tmp, tmp_path, cmdline):
    # point 1: the pid in LOCK/pid now belongs to another process (its command line lacks this run's token), or there
    # is no /proc to prove it: never signalled; the holder counts as gone and the lock is removed
    sh = nas_tmp
    proc = fake_proc(tmp_path, cmdline) if cmdline else (tmp_path / "no-proc").as_posix()
    fns, kills, _ = stand_ins(tmp_path)
    fake_lock(sh, FAKE_PID, owner=TOKEN)
    rc, out, err = sh(fns + jp.s_lock_release(TOKEN), proc=proc)
    assert (rc, out) == (0, "released"), err
    assert not sh.lock.exists()
    assert log_lines(kills) and set(log_lines(kills)) == {f"-0 {FAKE_PID}"}  # kill -0 probes only, never a TERM


@pytest.mark.parametrize("fractional,naps", [(True, ["0.1"] * 51), (False, ["1"] * 10)], ids=["sleep-0.1", "whole-s"])
def test_release_signals_its_holder_and_gives_up_well_inside_the_ssh_timeout(nas_tmp, tmp_path, fractional, naps):
    # points 1 and 4: the holder's command line carries the token, so it is signalled; it never stops (stand-in kill),
    # so the wait loop runs out. With sleep 0.1 that is the probe + 50 naps of 0.1 s; where sleep takes whole seconds
    # only it is 10 naps of 1 s (was 50 x 1 s, close to the 60 s ssh timeout). Counted, not timed.
    sh = nas_tmp
    cmdline = b"sh\x00-c\x00[ \"$(cat /tmp/joey-deploy.lock/owner)\" = \"" + TOKEN.encode() + b"\" ] || exit 0\x00"
    proc = fake_proc(tmp_path, cmdline)
    fns, kills, nap_log = stand_ins(tmp_path, fractional)
    fake_lock(sh, FAKE_PID, owner=TOKEN)
    rc, out, err = sh(fns + jp.s_lock_release(TOKEN), proc=proc)
    assert rc == 1 and f"holder {FAKE_PID} did not stop" in err, (out, err)
    assert FAKE_PID in log_lines(kills)  # the TERM went to our own holder
    assert log_lines(nap_log) == naps and sum(float(x) for x in naps) <= 10.5
    assert sh.lock.exists()  # a holder that did not stop keeps its lock


def test_release_counts_a_zombie_holder_as_gone_without_signalling_it(nas_tmp, tmp_path):
    # point 1 with JY-228's zombie rule: a zombie has an empty command line and state Z: gone, not signalled
    sh = nas_tmp
    proc = fake_proc(tmp_path, b"", state="Z")
    fns, kills, _ = stand_ins(tmp_path)
    fake_lock(sh, FAKE_PID, owner=TOKEN)
    rc, out, err = sh(fns + jp.s_lock_release(TOKEN), proc=proc)
    assert (rc, out) == (0, "released"), err
    assert FAKE_PID not in log_lines(kills)


def test_real_release_leaves_a_process_that_reused_the_pid_alone(nas_tmp):
    # point 1 with real processes: LOCK/pid names a live process that is not the holder (no token on its command line)
    sh = nas_tmp
    if sh("[ -r /proc/self/cmdline ] && echo y")[1] != "y":
        pytest.skip("no /proc cmdline")
    other = sh.background("sleep 30")
    try:
        fake_lock(sh, other, owner=TOKEN)
        assert sh(jp.s_lock_release(TOKEN))[1] == "released"
        assert not sh.lock.exists() and sh.alive(other)
    finally:
        sh(f"kill {other} 2>/dev/null; true")


def test_wait_loops_use_the_nap_budget():
    # point 4: both wait loops count to $naps, which SH_NAP sets from whether sleep takes a fraction
    take, release = jp.s_lock_take(SHA, TOKEN), jp.s_lock_release(TOKEN)
    assert '[ "$i" -le "$naps" ] || break' in take and '[ "$i" -lt "$naps" ]' in release
    assert jp.SH_NAP in take and jp.SH_NAP in release and jp.SH_OURS in release
    assert not re.search(r"-l[te] 50\b", take + release)
