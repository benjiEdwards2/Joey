"""JY-306: joey.py local up / down / status with a fake process runner (no real server, git or network)."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import joey  # noqa: E402
import joey_preview  # noqa: E402
import joey_preview_local as jl  # noqa: E402

SHA = {"main": "a" * 40, "feat/x": "b" * 40}


class FakeProc:
    def __init__(self):
        self.next_pid = 100
        self.live = set()
        self.ports = {}       # port -> pid (foreign or ours)
        self.spawned = []     # (cmd, cwd, env)
        self.killed = []
        self.healthy = True
        self.dirty = False
        self.t = 0.0

    def git(self, *args, cwd=None):
        if args[0] == "rev-parse":
            ref = args[2].split("^")[0]
            if ref not in SHA:
                raise RuntimeError("unknown")
            return SHA[ref]
        if args[:2] == ("worktree", "add"):
            Path(args[3]).mkdir(parents=True)
        if args[:2] == ("worktree", "remove"):
            import shutil
            shutil.rmtree(args[3])
        if args[0] == "status":
            return " M x" if self.dirty else ""
        return ""

    def spawn(self, cmd, cwd, env, log):
        self.next_pid += 1
        pid = self.next_pid
        self.live.add(pid)
        self.ports[int(cmd[cmd.index("--port") + 1])] = pid
        self.spawned.append((cmd, cwd, env))
        Path(log).write_text("booting\nboom\n")
        return pid

    def run(self, cmd, cwd, env):
        pass

    def alive(self, pid):
        return pid in self.live

    def kill(self, pid):
        self.killed.append(pid)
        self.live.discard(pid)
        self.ports = {p: o for p, o in self.ports.items() if o != pid}

    def port_owner(self, port):
        return self.ports.get(port)

    def health(self, port):
        return {"status": "ok"} if self.healthy else None

    def sleep(self, s):
        self.t += s

    def now(self):
        return self.t

    def lan_address(self):
        return "<pc-address>"


@pytest.fixture
def env(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    return clone, FakeProc()


def test_slot_table():
    assert jl.SLOTS == {1: 3001, 2: 3002, 3: 3003}
    assert jl.url(3, 3003, "127.0.0.1").endswith("/?tv=1")
    assert "tv=1" not in jl.url(1, 3001, "127.0.0.1")


def test_joey_dispatch_has_local():
    assert joey.COMMANDS["local"] is jl


@pytest.mark.parametrize("argv", [["up", "4", "main"], ["up", "1"], ["down", "9"], ["nope"]])
def test_local_bad_args(argv):
    with pytest.raises(SystemExit):
        jl.build_parser().parse_args(argv)


def test_local_args():
    a = jl.build_parser().parse_args(["up", "2", "feat/x", "--lan"])
    assert (a.slot, a.branch, a.lan) == (2, "feat/x", True)
    assert jl.build_parser().parse_args(["down", "all"]).slot == "all"


def test_local_two_slots_isolated(env):
    clone, proc = env
    jl.up(clone, 1, "main", False, proc, out=lambda *_: None)
    jl.up(clone, 2, "feat/x", False, proc, out=lambda *_: None)
    (c1, w1, e1), (c2, w2, e2) = proc.spawned
    assert c1[c1.index("--port") + 1] == "3001" and c2[c2.index("--port") + 1] == "3002"
    assert c1[c1.index("--host") + 1] == "127.0.0.1"
    assert w1 != w2
    for k in ("MEDIA_DB_PATH", "META_CACHE_DIR", "IMG_CACHE_DIR", "SNAPSHOT_DIR"):
        assert e1[k] != e2[k]
        assert Path(e1[k]).is_relative_to(jl.state_dir(clone, 1))
    for k in joey_preview.FORCED_OFF:
        assert e1[k] == "off"
    assert jl.read_state(clone, 2)["commit"] == SHA["feat/x"]


def test_local_env_drops_secrets():
    e = jl.slot_env({"JELLYFIN_API_KEY": "s", "TUNNEL_TOKEN": "t", "PATH": "p", "MEDIA_WARMUP": "on"}, "/x", 1)
    assert "JELLYFIN_API_KEY" not in e and "TUNNEL_TOKEN" not in e and e["PATH"] == "p"
    assert e["MEDIA_WARMUP"] == "off" and "JOEY_FRONT" not in e
    assert jl.slot_env({}, "/x", 3)["JOEY_FRONT"] == "media"


def test_local_replace_status_down(env, capsys):
    clone, proc = env
    jl.up(clone, 1, "main", False, proc)
    first = jl.read_state(clone, 1)["pid"]
    jl.up(clone, 1, "feat/x", False, proc)
    assert first in proc.killed
    jl.status(clone, proc)
    out = capsys.readouterr().out
    assert "slot 1  port 3001  feat/x" in out and "slot 2  port 3002  stopped" in out
    assert jl.main(["down", "all"], proc=proc, clone=clone) == 0
    assert not jl.state_dir(clone, 1).exists() and not jl.worktree_dir(clone, 1).exists()


def test_local_port_clash_never_kills(env, capsys):
    clone, proc = env
    proc.ports[3001] = 4242
    proc.live.add(4242)
    assert jl.main(["up", "1", "main"], proc=proc, clone=clone) == 1
    assert "pid 4242" in capsys.readouterr().out
    assert proc.killed == [] and proc.spawned == []


def test_local_health_timeout_tails_log(env, capsys):
    clone, proc = env
    proc.healthy = False
    assert jl.main(["up", "2", "main"], proc=proc, clone=clone) == 1
    out = capsys.readouterr().out
    assert "boom" in out and "within 30 s" in out
    assert not jl.state_dir(clone, 2).exists()


def test_local_refuses_dirty_worktree(env):
    clone, proc = env
    jl.up(clone, 1, "main", False, proc, out=lambda *_: None)
    proc.dirty = True
    with pytest.raises(joey_preview.jc.Refused):
        jl.up(clone, 1, "main", False, proc, out=lambda *_: None)


def test_local_state_is_gitignored():
    ignore = (REPO_ROOT / ".gitignore").read_text()
    assert "/data/" in ignore.splitlines()
