"""Shared helpers for the `scripts/joey.py` subcommands (JY-010; `close-out` JY-011 and `preview` JY-012 build on them).

- Runner: one per run. step(name, fn) records PASS / FAIL / SKIP / DRY, prints the row and appends it to
  <main clone>/.joey/logs/joey_<YYYY-MM-DD>.log. A step that raises Refused (or any error) is a FAIL and stops the
  run, so nothing after it changes anything. summary() prints the counts and returns the exit code (1 on any FAIL).
- --dry-run: read-only commands still run (so refusals still show); every state change goes through
  Runner.write_guard() / Runner.change(), which in a dry run records DRY with the command it would have run.
- run() wraps subprocess (UTF-8, captured), git() returns stdout, gh_json() runs `gh ... --json` (JOEY_GH points at a
  fake in tests), ssh_run() / ssh() run one command on the NAS, Runner.ssh_change() is the guarded NAS write.
- redact() masks tokens, Bearer / X-Api-Key values, URL credentials, e-mail addresses and the home folder in every
  line that is printed or logged.
Stdlib only, Python 3.12. Importing this module does no work.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATUSES = ("PASS", "FAIL", "SKIP", "DRY")


class Refused(Exception):
    """A check said no. The step is a FAIL and the run stops."""


class Skip(Exception):
    """The step did not apply. Recorded as SKIP; the run goes on."""


class DryRun(Exception):
    """Raised by write_guard in a dry run; carries the command that would have run."""


class Stop(Exception):
    """Raised by Runner.step after a FAIL, so the caller stops before any later change."""


def utf8_stdio():
    """JY-241: stdout and stderr to UTF-8 with errors="replace", so printing a PR title with a non-cp1252 character
    ("≤", an emoji) to a Windows pipe never raises UnicodeEncodeError mid-run. Called at the CLI entry points."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ---------- redaction ----------
_SUBS = [
    (re.compile(r"(?i)\b(gh[pousr]_|github_pat_)[A-Za-z0-9_]+"), "<token>"),
    (re.compile(r"(?i)(Bearer\s+)\S+"), r"\1<redacted>"),
    (re.compile(r"(?i)(X-Api-Key[\"']?\s*[:=]\s*[\"']?)[^\s\"',;]+"), r"\1<redacted>"),
    (re.compile(r'(?i)(Token=")[^"]*(")'), r"\1<redacted>\2"),
    (re.compile(r"(?i)\b((?:access_|api_?|auth_?)?(?:token|key|secret|password)\s*[=:]\s*)[^\s,;&]+"),
     r"\1<redacted>"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@"), r"\1<redacted>@"),  # https://user:pass@host
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
]


def _home_patterns():
    home = os.path.expanduser("~")
    if not home or home in ("~", "/", "\\"):
        return []
    forms = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    return [re.compile(re.escape(f) + r"(?=[\\/]|$|\W)", re.I) for f in sorted(forms, key=len, reverse=True)]


def redact(text):
    """Mask secrets and the user's home folder (it carries the user name) in one log or print line."""
    s = str(text)
    for pat in _home_patterns():
        s = pat.sub("~", s)
    for pat, rep in _SUBS:
        s = pat.sub(rep, s)
    return s


# ---------- subprocess wrappers ----------
def cmd_text(cmd):
    return " ".join(f'"{c}"' if (" " in str(c) or not str(c)) else str(c) for c in cmd)


def run(cmd, cwd=None, check=False, stdin=None, timeout=120):
    """subprocess.run with UTF-8 text in and out. check=True raises RuntimeError with the first output line.
    No stdin text -> stdin is DEVNULL; GIT_TERMINAL_PROMPT=0, so git never waits on a credential prompt."""
    extra = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"), **extra)
    if check and r.returncode != 0:
        msg = (r.stderr.strip() or r.stdout.strip() or "no output").splitlines()[0]
        raise RuntimeError(f"{cmd_text(cmd)} exited {r.returncode}: {msg}")
    return r


def git(*args, cwd=None):
    """Run git, return stdout stripped; raise on a non-zero exit."""
    return run(["git", *args], cwd=cwd, check=True).stdout.strip()


def gh_cmd():
    """The gh command. JOEY_GH overrides it (tests: a fake .py script, run with this Python)."""
    exe = os.environ.get("JOEY_GH")
    if not exe:
        return ["gh"]
    return [sys.executable, exe] if exe.endswith(".py") else [exe]


def gh_json(args, cwd=None, timeout=60):
    """Run `gh <args>` (args include --json) and return the parsed JSON. Raises RuntimeError on failure."""
    try:
        r = run([*gh_cmd(), *args], cwd=cwd, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("gh is not on PATH") from None
    if r.returncode != 0:
        msg = (r.stderr.strip() or r.stdout.strip() or "no output").splitlines()[0]
        raise RuntimeError(f"gh exited {r.returncode}: {msg}")
    return json.loads(r.stdout or "null")


def _utf8(b):
    """Process output as text: bytes decoded UTF-8 (errors replaced); str (test fakes) passes through."""
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")


def _scrub_nas(text, nas):
    """The ssh target's user and host out of an ssh error line (ssh names the host it could not reach)."""
    user, _, host = nas.rpartition("@")
    text = text.replace(nas, "<nas>")
    if host:
        text = text.replace(host, "<nas>")
    if user:
        text = text.replace(user + "@", "")
    return text


def ssh_run(cmd, stdin=None, timeout=60):
    """One command on the NAS (JOEY_NAS, default root@nas.local as deploy/push.sh; key JOEY_NAS_KEY, default
    ~/.ssh/joey_nas). BatchMode, 10 s connect timeout, stdin sent as UTF-8 BYTES (cp1252 once broke a NAS script, and
    Windows text-mode stdin turns every LF into CRLF, which breaks `sh -s`: JY-012 review, 2026-10-23).
    Returns the CompletedProcess (returncode, stdout, stderr as str) of the remote command. Raises RuntimeError when ssh
    itself fails (exit 255; the NAS user and host are scrubbed from the message) or the ssh binary is missing."""
    nas = os.environ.get("JOEY_NAS") or "root@nas.local"
    key = os.path.expanduser(os.environ.get("JOEY_NAS_KEY") or "~/.ssh/joey_nas")
    extra = {"input": stdin.encode("utf-8")} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        r = subprocess.run(["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", nas, cmd],
                           capture_output=True, timeout=timeout, **extra)
    except FileNotFoundError:
        raise RuntimeError("ssh is not on PATH (install the OpenSSH client)") from None
    r = subprocess.CompletedProcess(r.args, r.returncode, _utf8(r.stdout), _utf8(r.stderr))
    if r.returncode == 255:
        first = (r.stderr.strip() or "no output").splitlines()[0]
        raise RuntimeError("ssh to the NAS failed (NAS off 22:00-07:00, or off the home LAN?): "
                           + _scrub_nas(first, nas))
    return r


def ssh(cmd, stdin=None, timeout=60):
    """ssh_run(), returning stdout stripped (the remote exit code is not checked)."""
    return ssh_run(cmd, stdin=stdin, timeout=timeout).stdout.strip()


# ---------- repo facts ----------
def clone_root(cwd=None):
    """The main clone: parent of the common git dir, so it is the same from the clone or any worktree."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    return Path(os.path.realpath(common)).parent


def log_dir(clone):
    return Path(clone) / ".joey" / "logs"


_GH_URL = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/*$", re.I)


def repo_slug(clone):
    """owner/name from origin's URL (credentials stripped; the URL itself is never printed)."""
    url = run(["git", "config", "--get", "remote.origin.url"], cwd=clone).stdout.strip()
    url = re.sub(r"^([a-z][a-z0-9+.-]*://)[^/@]+@", r"\1", url, flags=re.I)
    m = _GH_URL.search(url)
    if not m:
        raise RuntimeError("origin is not a GitHub URL")
    return f"{m.group(1)}/{m.group(2)}"


# ---------- the runner ----------
class Runner:
    def __init__(self, name, dry_run=False, log_dir=None):
        self.name = name
        self.dry = dry_run
        self.rows = []  # (step, status, detail)
        self.log_path = None
        if log_dir is not None:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self.log_path = Path(log_dir) / f"joey_{dt.date.today():%Y-%m-%d}.log"

    def log(self, msg):
        line = redact(msg)
        print(line, flush=True)
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{dt.datetime.now():%H:%M:%S} [{self.name}] {line}\n")

    def step(self, name, fn, *a, **kw):
        """Run one step. fn returns None, a detail string, or (status, detail). Returns the status."""
        stop = False
        try:
            r = fn(*a, **kw)
            status, detail = r if isinstance(r, tuple) else ("PASS", r or "")
        except DryRun as e:
            status, detail = "DRY", f"would run: {e}"
        except Skip as e:
            status, detail = "SKIP", str(e)
        except Refused as e:
            status, detail, stop = "FAIL", str(e), True
        except Exception as e:  # noqa: BLE001 - reported as a FAIL row, never a traceback
            status, detail, stop = "FAIL", f"{type(e).__name__}: {e}", True
        assert status in STATUSES, status
        self.rows.append((name, status, detail))
        self.log(f"{status:<4}  {name}" + (f" - {detail}" if detail else ""))
        if stop:
            raise Stop(detail)
        return status

    def write_guard(self, what):
        """Call before any state change. In a dry run it raises DryRun(what), so the step is recorded as DRY."""
        if self.dry:
            raise DryRun(what)

    def change(self, cmd, cwd=None):
        """A state-changing command: guarded, then run; raises on a non-zero exit."""
        self.write_guard(cmd_text(cmd))
        return run(cmd, cwd=cwd, check=True)

    def ssh_change(self, cmd, stdin=None, timeout=60):
        """A state-changing NAS command: guarded (a dry run never reaches the NAS), then ssh_run(); returns the
        CompletedProcess. The remote exit code is the caller's to check."""
        self.write_guard(f"ssh NAS: {cmd}" + (" <stdin payload>" if stdin is not None else ""))
        return ssh_run(cmd, stdin=stdin, timeout=timeout)

    def summary(self, refused=None):
        counts = {s: sum(1 for r in self.rows if r[1] == s) for s in STATUSES}
        self.log("summary: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v)
                 + (" (DRY RUN: nothing changed)" if self.dry else ""))
        if refused is not None:
            self.log(f"REFUSED: {refused}")
        return 1 if counts["FAIL"] else 0

    def execute(self, title, body):
        """Run body(self) under a banner; a stopped step ends the run. Returns the exit code."""
        self.log(f"=== joey {title}{' (DRY RUN)' if self.dry else ''} ===")
        try:
            body(self)
        except Stop as e:
            return self.summary(refused=str(e))
        return self.summary()
