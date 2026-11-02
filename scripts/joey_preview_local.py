"""JY-306: scripts/joey.py local up|down|status - fixed-port previews on the PC (nothing runs on the NAS).

  python scripts/joey.py local up <1|2|3> <branch> [--lan]   slot N -> port 3000+N; slot 3 = media front (tv=1)
  python scripts/joey.py local down <1|2|3|all>
  python scripts/joey.py local status

Each slot owns a detached git worktree `../wt-preview-<slot>` (detached HEAD at the branch's commit, so the shared
clone is never switched and two slots may run the same branch) and a state dir `data/preview-slots/<slot>/` holding
its sqlite file, meta and image caches, demo snapshots, slot.json and hub.log. Data is the demo seed only. No .env is
read; write-capable keys are dropped and every FORCED_OFF loop (imported from joey_preview) is pinned off.
Binds 127.0.0.1 unless --lan. All process and network effects go through a Proc object, so tests inject a fake.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import joey_common as jc
from joey_preview import ENV_OUT, FORCED_OFF

SLOTS = {1: 3001, 2: 3002, 3: 3003}
TV_SLOT = 3
HEALTH_TIMEOUT = 30
# Inherited env keys never passed to a slot: the preview's OUT list plus anything that names a secret.
_SECRETISH = ("KEY", "TOKEN", "SECRET", "PASSWORD", "ICS_URL", "QBIT_", "JELLYFIN_", "JELLYSEERR_", "OWNER_")


def slot_port(slot):
    return SLOTS[int(slot)]


def state_dir(clone, slot):
    return Path(clone) / "data" / "preview-slots" / str(slot)


def worktree_dir(clone, slot):
    return Path(clone).parent / f"wt-preview-{slot}"


def slot_env(base, sdir, slot):
    """The slot process env: the inherited env minus anything secret, plus this slot's own paths."""
    env = {k: v for k, v in base.items()
           if k not in ENV_OUT and not any(s in k.upper() for s in _SECRETISH) and k not in FORCED_OFF}
    env.update({k: "off" for k in FORCED_OFF})
    sdir = Path(sdir)
    env.update({
        "MEDIA_DB_PATH": str(sdir / "media.db"),
        "META_CACHE_DIR": str(sdir / "meta-cache"),
        "IMG_CACHE_DIR": str(sdir / "img-cache"),
        "SNAPSHOT_DIR": str(sdir / "snapshots"),
        "MEDIA_BACKUP_DIR": str(sdir / "backups"),
        "POSTERS_DIR": str(sdir / "posters"),
        "JOEY_COOKIE_SECURE": "0",
    })
    if int(slot) == TV_SLOT:
        env["JOEY_FRONT"] = "media"
    else:
        env.pop("JOEY_FRONT", None)
    return env


class Proc:
    """Real process / network / git effects."""

    def git(self, *args, cwd=None):
        return jc.git(*args, cwd=cwd)

    def spawn(self, cmd, cwd, env, log):
        flags = {}
        if os.name == "nt":
            flags["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            flags["start_new_session"] = True
        with open(log, "ab") as fh:
            return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, **flags).pid

    def run(self, cmd, cwd, env):
        subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True)

    def alive(self, pid):
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
            return str(pid) in out
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def cmdline(self, pid):
        if os.name == "nt":
            return subprocess.run(["powershell", "-NoProfile", "-Command",
                                   f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                                  capture_output=True, text=True).stdout
        try:
            return Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        except OSError:
            return ""

    def kill(self, pid):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass

    def port_owner(self, port):
        """PID listening on the port, 0 if in use by an unknown owner, None if free."""
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return None
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                    return int(parts[4])
        return 0

    def health(self, port):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001 - not up yet
            return None

    def sleep(self, s):
        time.sleep(s)

    def now(self):
        return time.time()

    def lan_address(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("192.0.2.1", 9))  # TEST-NET, nothing is sent
                return s.getsockname()[0]
            except OSError:
                return "<pc-address>"


def read_state(clone, slot):
    f = state_dir(clone, slot) / "slot.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ours(st, proc):
    """The pid is our uvicorn on the slot's port, not a reused pid."""
    cmd = proc.cmdline(st["pid"]) or ""
    return "uvicorn" in cmd and f"--port {st['port']}" in cmd


def stop(clone, slot, proc, out=print):
    st = read_state(clone, slot)
    if st and proc.alive(st["pid"]) and not ours(st, proc):
        out(f"slot {slot}: pid {st['pid']} is not this slot's hub (stale slot.json); not killed")
    elif st and proc.alive(st["pid"]):
        proc.kill(st["pid"])
        out(f"slot {slot}: stopped pid {st['pid']} ({st['branch']} @ {st['commit'][:8]})")
    else:
        out(f"slot {slot}: not running")
    sdir = state_dir(clone, slot)
    if sdir.exists():
        shutil.rmtree(sdir, ignore_errors=True)
    wt = worktree_dir(clone, slot)
    if wt.exists():
        proc.git("worktree", "remove", "--force", str(wt), cwd=clone)


def up(clone, slot, branch, lan, proc, out=print):
    port = slot_port(slot)
    try:
        commit = proc.git("rev-parse", "--verify", f"{branch}^{{commit}}", cwd=clone)
    except RuntimeError:
        raise jc.Refused(f"unknown branch {branch!r}; fetch it first; slot {slot} left as it was") from None
    st = read_state(clone, slot)
    owner = proc.port_owner(port)
    mine = st and proc.alive(st["pid"]) and ours(st, proc)
    if owner is not None and not (mine and owner in (0, st["pid"])):
        raise jc.Refused(f"port {port} is in use by pid {owner or 'unknown'}, not slot {slot}; nothing was killed")
    if mine:
        out(f"slot {slot}: replacing {st['branch']} @ {st['commit'][:8]}")
    wt = worktree_dir(clone, slot)
    if wt.exists() and proc.git("status", "--porcelain", cwd=wt):
        raise jc.Refused(f"slot {slot}: worktree wt-preview-{slot} has local changes; commit or remove them first")
    stop(clone, slot, proc, out=lambda *_: None)
    proc.git("worktree", "add", "--detach", str(wt), commit, cwd=clone)
    sdir = state_dir(clone, slot)
    for d in ("meta-cache", "img-cache", "snapshots", "backups", "posters"):
        (sdir / d).mkdir(parents=True, exist_ok=True)
    env = slot_env(os.environ, sdir, slot)
    proc.run([sys.executable, "-m", "hub.seed_demo"], cwd=wt, env=env)
    demo = wt / "data" / "demo-snapshots"
    if demo.exists():
        shutil.copytree(demo, sdir / "snapshots", dirs_exist_ok=True)
    host = "0.0.0.0" if lan else "127.0.0.1"
    log = sdir / "hub.log"
    pid = proc.spawn([sys.executable, "-m", "uvicorn", "hub.main:app", "--host", host, "--port", str(port)],
                     cwd=wt, env=env, log=log)
    state = {"slot": int(slot), "port": port, "branch": branch, "commit": commit, "pid": pid, "lan": lan,
             "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    (sdir / "slot.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    deadline = proc.now() + HEALTH_TIMEOUT
    while proc.health(port) is None:
        if proc.now() >= deadline or not proc.alive(pid):
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:] if log.exists() else []
            for line in tail:
                out(jc.redact(line))
            stop(clone, slot, proc, out=lambda *_: None)
            raise jc.Refused(f"slot {slot}: no /healthz on port {port} within {HEALTH_TIMEOUT} s")
        proc.sleep(0.5)
    out(f"slot {slot}: {branch} @ {commit[:8]}  pid {pid}  {url(slot, port, '127.0.0.1')}")
    if lan:
        out(f"  LAN: {url(slot, port, proc.lan_address())}  (a Windows Firewall inbound allow may be needed)")
    return state


def url(slot, port, host):
    return f"http://{host}:{port}/" + ("?tv=1" if int(slot) == TV_SLOT else "")


def status(clone, proc, out=print):
    for slot, port in SLOTS.items():
        st = read_state(clone, slot)
        if not st or not proc.alive(st["pid"]):
            out(f"slot {slot}  port {port}  stopped")
            continue
        started = dt.datetime.fromisoformat(st["started"])
        up_s = int((dt.datetime.now(dt.timezone.utc) - started).total_seconds())
        out(f"slot {slot}  port {port}  {st['branch']} @ {st['commit'][:8]}  pid {st['pid']}  "
            f"up {up_s // 60}m{up_s % 60:02d}s  {url(slot, port, '127.0.0.1')}")


def build_parser():
    p = argparse.ArgumentParser(prog="joey.py local", description="Fixed-port hub previews on this PC (JY-306).")
    sub = p.add_subparsers(dest="action", required=True)
    u = sub.add_parser("up", help="start (or replace) a slot: 1 -> 3001, 2 -> 3002, 3 -> 3003 (TV / media front)")
    u.add_argument("slot", type=int, choices=sorted(SLOTS))
    u.add_argument("branch", help="branch (or any commit-ish) to check out in ../wt-preview-<slot>")
    u.add_argument("--lan", action="store_true", help="bind 0.0.0.0 so a phone or TV can reach it")
    d = sub.add_parser("down", help="stop a slot and remove its state and worktree")
    d.add_argument("slot", choices=[str(s) for s in sorted(SLOTS)] + ["all"])
    sub.add_parser("status", help="every slot: port, branch, commit, pid, uptime, url")
    return p


def main(argv, proc=None, clone=None):
    a = build_parser().parse_args(argv)
    proc = proc or Proc()
    try:
        clone = Path(clone or jc.clone_root())
        if a.action == "up":
            up(clone, a.slot, a.branch, a.lan, proc)
        elif a.action == "down":
            for s in (SLOTS if a.slot == "all" else [int(a.slot)]):
                stop(clone, s, proc)
        else:
            status(clone, proc)
    except jc.Refused as e:
        print(f"REFUSED: {e}")
        return 1
    return 0
