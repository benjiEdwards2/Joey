"""JY-257: scripts/player_tokens.py with a fake Jellyfin and a fake ssh. No network, no NAS.

FakeNas stands in for joey_common.ssh_run. In-container helper calls run the script's own nas mode in-process against
FakeJellyfin, with the container's /tmp as a temp dir. The .env write runs the real shell from write_cmd() under `sh`
(docker exec swapped for plain cat / rm), so the backup, replace and newline guard are the shipped ones."""
import contextlib
import io
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import joey_common  # noqa: E402
import player_tokens as pt  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="sh is not on PATH")

ID_B = "a" * 32
ID_G = "b" * 32
ID_X = "c" * 32
CODE = "482913"


class FakeJellyfin:
    def __init__(self, approver="B", approve_after=2, quick_connect=True):
        self.users = {"B": ID_B, "G": ID_G, "X": ID_X}
        self.approver = approver            # name, a dict who -> name, or None (never approved)
        self.approve_after = approve_after
        self.quick_connect = quick_connect
        self.tokens = {}                    # token -> user name
        self.secrets = {}                   # secret -> [polls, device id]
        self.her = True
        self.calls = []
        self.issued = []                    # every token and secret handed out (the no-secret checks look for them)

    def household(self):
        return frozenset({ID_B}), (ID_G if self.her else None)

    def add_token(self, name):
        t = secrets.token_hex(16)
        self.tokens[t] = name
        self.issued.append(t)
        return t

    def http(self, method, path, token=None, device_id=None, body=None):
        self.calls.append((method, path.split("?")[0]))
        if path == "/QuickConnect/Enabled":
            return 200, self.quick_connect
        if path == "/QuickConnect/Initiate":
            s = "qcsecret" + secrets.token_hex(20)
            self.secrets[s] = [0, device_id]
            self.issued.append(s)
            return 200, {"Secret": s, "Code": CODE}
        if path.startswith("/QuickConnect/Connect?secret="):
            s = path.split("=", 1)[1]
            if s not in self.secrets:
                return 404, None
            self.secrets[s][0] += 1
            return 200, {"Authenticated": self._approver(s) is not None and self.secrets[s][0] >= self.approve_after}
        if path == "/Users/AuthenticateWithQuickConnect":
            s = body["Secret"]
            name = self._approver(s)
            if s not in self.secrets or name is None:
                return 401, None
            del self.secrets[s]
            t = self.add_token(name)
            return 200, {"AccessToken": t, "User": {"Name": name, "Id": self.users[name]}}
        if path == "/Users/Me":
            if token not in self.tokens:
                return 401, None
            name = self.tokens[token]
            return 200, {"Name": name, "Id": self.users[name]}
        if path == "/Sessions/Logout":
            self.tokens.pop(token, None)
            return 204, None
        return 404, None

    def _approver(self, secret):
        if isinstance(self.approver, dict):
            dev = self.secrets.get(secret, [0, ""])[1] or ""
            return self.approver.get(dev.rsplit("-", 1)[-1])
        return self.approver


class FakeNas:
    def __init__(self, tmp, jf, env_text=""):
        self.jf = jf
        self.env = tmp / "nas" / ".env"
        self.env.parent.mkdir()
        self.env.write_text(env_text, encoding="utf-8", newline="\n")
        self.ctr = tmp / "ctr-tmp"
        self.ctr.mkdir()
        self.ctr_env = {}
        self.staged = False
        self.recreated = 0
        self.cmds = []

    def _cp(self, out, rc=0, err=""):
        return subprocess.CompletedProcess(["ssh"], rc, out, err)

    def env_value(self, key):
        vals = [ln.split("=", 1)[1] for ln in self.env.read_text(encoding="utf-8").splitlines() if ln.startswith(key + "=")]
        return vals[-1] if vals else ""

    def ssh_run(self, cmd, stdin=None, timeout=60):
        self.cmds.append(cmd)
        if cmd == pt.STAGE_CMD:
            assert "def nas_main" in stdin
            self.staged = True
            return self._cp("STAGED\n")
        if f"python {pt.INNER} nas " in cmd:
            assert self.staged, "helper called before it was copied into the container"
            action, who = cmd.split(" nas ", 1)[1].split()
            text = self.env_value(pt.TOKEN_ENV[who]) if cmd.startswith("sed -n") else None
            inner = pt.Inner(http=self.jf.http, household=self.jf.household, state_dir=str(self.ctr),
                             environ=self.ctr_env)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pt.nas_main([action, who], stdin_text=text if text is not None else "", inner=inner)
            return self._cp(buf.getvalue())
        if cmd.startswith("set -e; umask 077; ENV="):
            real = (cmd.replace(f"docker exec {pt.CONTAINER} ", "")
                    .replace(pt.ENV_FILE, self.env.as_posix())
                    .replace(f"{pt.STATE_DIR}/joey_pt_", self.ctr.as_posix() + "/joey_pt_"))
            r = subprocess.run(["sh", "-c", real], capture_output=True, text=True)
            return self._cp(r.stdout, r.returncode, r.stderr)
        if cmd == pt.RECREATE_CMD:
            self.recreated += 1
            self.staged = False
            for f in self.ctr.iterdir():
                f.unlink()
            self.ctr_env = dict(ln.split("=", 1) for ln in self.env.read_text(encoding="utf-8").splitlines()
                                if "=" in ln and not ln.startswith("#"))
            return self._cp("RECREATED\n")
        if cmd == pt.HEALTH_CMD:
            return self._cp("healthy\n")
        raise AssertionError(f"unexpected NAS command: {cmd}")


@pytest.fixture
def world(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(pt, "clock", lambda: now[0])
    monkeypatch.setattr(pt, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    monkeypatch.setattr(joey_common, "clone_root", lambda cwd=None: tmp_path)

    def make(env_text="A=1\n", **jf_kw):
        jf = FakeJellyfin(**jf_kw)
        nas = FakeNas(tmp_path, jf, env_text)
        monkeypatch.setattr(joey_common, "ssh_run", nas.ssh_run)
        return jf, nas

    return make


def run(capsys, tmp_path, *argv):
    rc = pt.main(list(argv))
    out = capsys.readouterr().out
    logs = list((tmp_path / ".joey" / "logs").glob("joey_*.log"))
    return rc, out, (logs[0].read_text(encoding="utf-8") if logs else "")


def assert_no_secret(jf, nas, out, log):
    assert jf.issued, "the fake handed nothing out"
    for s in jf.issued:
        assert s not in out, "a token or Quick Connect secret reached the output"
        assert s not in log, "a token or Quick Connect secret reached the log"
        assert all(s not in c for c in nas.cmds), "a token or secret went into an ssh command line"
    # nothing that looks like a 32-hex token in either
    assert not re.search(r"\b[0-9a-f]{32}\b", out + log)


def test_happy_path_both_members(world, capsys, tmp_path):
    jf, nas = world(approver={"you": "B", "her": "G"})
    rc, out, log = run(capsys, tmp_path)
    assert rc == 0, out
    you, her = nas.env_value("JELLYFIN_PLAYER_TOKEN_YOU"), nas.env_value("JELLYFIN_PLAYER_TOKEN_HER")
    assert jf.tokens[you] == "B" and jf.tokens[her] == "G"
    text = nas.env.read_text(encoding="utf-8")
    assert text.startswith("A=1\n") and text.count("JELLYFIN_PLAYER_TOKEN_YOU=") == 1
    assert len(list(nas.env.parent.glob(".env.bak-*"))) >= 1
    assert nas.recreated == 1                      # one state change for both members
    assert f"Quick Connect code for you: {CODE}" in out
    assert "token set (len 32)" in out and "user B..." in out and "user G..." in out
    assert "joey-hub holds JELLYFIN_PLAYER_TOKEN_HER: valid" in out
    assert "FAIL" not in out and "summary: PASS=" in out
    assert not list(nas.ctr.iterdir())             # nothing left in the container's /tmp
    assert_no_secret(jf, nas, out, log)
    assert "token set (len 32)" in log


def test_env_without_trailing_newline_and_old_line_replaced(world, capsys, tmp_path):
    jf, nas = world(env_text="A=1\nJELLYFIN_PLAYER_TOKEN_YOU=stale\r\nB=2", approver="B")
    jf.her = False
    rc, out, log = run(capsys, tmp_path, "--who", "you")
    assert rc == 0, out
    lines = nas.env.read_text(encoding="utf-8").split("\n")
    assert lines[:2] == ["A=1", "B=2"] and lines[2].startswith("JELLYFIN_PLAYER_TOKEN_YOU=") and lines[3] == ""
    assert "\r" not in nas.env.read_text(encoding="utf-8")
    bak = list(nas.env.parent.glob(".env.bak-*"))
    assert len(bak) == 1 and "stale" in bak[0].read_text(encoding="utf-8")
    if os.name == "posix":
        assert (nas.env.stat().st_mode & 0o777) == 0o600 and (bak[0].stat().st_mode & 0o777) == 0o600


def test_timeout_writes_nothing(world, capsys, tmp_path):
    jf, nas = world(approver=None)
    rc, out, log = run(capsys, tmp_path, "--who", "you", "--timeout", "30")
    assert rc == 1
    assert "FAIL  you: wait for approval - not approved within 30 s" in out
    assert nas.env.read_text(encoding="utf-8") == "A=1\n"
    assert nas.recreated == 0 and not list(nas.env.parent.glob(".env.bak-*"))
    assert not list(nas.ctr.iterdir())             # the Quick Connect secret was dropped
    assert_no_secret(jf, nas, out, log)


def test_wrong_user_is_refused_and_signed_out(world, capsys, tmp_path):
    jf, nas = world(approver="G")                  # her phone approved the code for `you`
    rc, out, log = run(capsys, tmp_path, "--who", "you")
    assert rc == 1
    assert "approved by user G..., not you's Jellyfin user" in out
    assert jf.tokens == {}                         # the stray token was revoked
    assert nas.env.read_text(encoding="utf-8") == "A=1\n" and nas.recreated == 0
    assert_no_secret(jf, nas, out, log)


def test_existing_valid_token_stops_without_rotate(world, capsys, tmp_path):
    jf, nas = world()
    tok = FakeJellyfin.add_token(jf, "B")
    nas.env.write_text(f"A=1\nJELLYFIN_PLAYER_TOKEN_YOU={tok}\n", encoding="utf-8", newline="\n")
    rc, out, log = run(capsys, tmp_path, "--who", "you")
    assert rc == 0
    assert "SKIP  you: current token - JELLYFIN_PLAYER_TOKEN_YOU already set and valid (len 32, user B...)" in out
    assert ("POST", "/QuickConnect/Initiate") not in jf.calls
    assert nas.recreated == 0 and nas.env_value("JELLYFIN_PLAYER_TOKEN_YOU") == tok
    assert_no_secret(jf, nas, out, log)


def test_rotate_replaces_a_valid_token(world, capsys, tmp_path):
    jf, nas = world(approver="B")
    tok = FakeJellyfin.add_token(jf, "B")
    nas.env.write_text(f"JELLYFIN_PLAYER_TOKEN_YOU={tok}\n", encoding="utf-8", newline="\n")
    rc, out, log = run(capsys, tmp_path, "--who", "you", "--rotate")
    assert rc == 0, out
    new = nas.env_value("JELLYFIN_PLAYER_TOKEN_YOU")
    assert new != tok and jf.tokens[new] == "B"
    assert nas.env.read_text(encoding="utf-8").count("JELLYFIN_PLAYER_TOKEN_YOU=") == 1
    assert nas.recreated == 1
    assert_no_secret(jf, nas, out, log)


def test_invalid_existing_token_is_replaced(world, capsys, tmp_path):
    jf, nas = world(approver="B")
    nas.env.write_text("JELLYFIN_PLAYER_TOKEN_YOU=" + "d" * 32 + "\n", encoding="utf-8", newline="\n")
    rc, out, log = run(capsys, tmp_path, "--who", "you")
    assert rc == 0, out
    assert "is set but Jellyfin refuses it" in out
    assert jf.tokens[nas.env_value("JELLYFIN_PLAYER_TOKEN_YOU")] == "B"


def test_her_without_a_jellyfin_user_is_skipped(world, capsys, tmp_path):
    jf, nas = world(approver="B")
    jf.her = False
    rc, out, log = run(capsys, tmp_path)
    assert rc == 0, out
    assert "SKIP  her: skip - no Jellyfin user for her yet" in out
    assert nas.env_value("JELLYFIN_PLAYER_TOKEN_HER") == "" and nas.env_value("JELLYFIN_PLAYER_TOKEN_YOU")
    assert nas.recreated == 1


def test_quick_connect_off_says_where_to_turn_it_on(world, capsys, tmp_path):
    jf, nas = world(quick_connect=False)
    rc, out, log = run(capsys, tmp_path, "--who", "you")
    assert rc == 1 and "Quick Connect did not start (quick_connect_off)" in out and nas.recreated == 0


def test_in_container_errors_never_carry_a_url(tmp_path):
    def boom(*a, **k):
        raise OSError("http://jellyfin:8096/QuickConnect/Connect?secret=qcsecret123")
    inner = pt.Inner(http=boom, household=lambda: (frozenset({ID_B}), None), state_dir=str(tmp_path))
    (tmp_path / "joey_qc_you").write_text("qcsecret123")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pt.nas_main(["poll", "you"], stdin_text="", inner=inner)
    assert buf.getvalue().strip() == '{"error": "OSError"}'


def test_only_joey_hub_reads_the_player_tokens():
    """Why the script recreates only `hub`: joey-media reads media.env only; connectors and stackctl never use the keys."""
    for folder in ("connectors", "stackctl"):
        for f in (REPO_ROOT / folder).rglob("*.py"):
            assert "JELLYFIN_PLAYER_TOKEN" not in f.read_text(encoding="utf-8", errors="replace"), f
    compose = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    media = compose.split("\n  joey-media:", 1)[1].split("\n  connectors:", 1)[0]
    assert "- .env" not in media and "media.env" in media
    hub = compose.split("\n  hub:", 1)[1].split("\n  joey-media:", 1)[0]
    assert "- .env" in hub and "container_name: joey-hub" in hub
