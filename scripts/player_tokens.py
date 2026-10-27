"""JY-257 (2026-10-27): make the player tokens JELLYFIN_PLAYER_TOKEN_YOU / _HER (JY-053 Q1 A, JY-054 Q1 A).

Run from Windows, at the repo root (B.'s phone in hand, the NAS on, 07:00-21:30 Melbourne):
    python scripts/player_tokens.py                 # you, then her (her is skipped when she has no Jellyfin user)
    python scripts/player_tokens.py --who you       # one member
    python scripts/player_tokens.py --rotate        # replace a token that is still valid

For each member it signs a "Joey player" device in to Jellyfin with Quick Connect: it prints only the six-digit code,
the member approves it in the Jellyfin app (Settings -> Quick Connect), and it polls until approved or --timeout.
Then it checks the token's own user (`/Users/Me`) is that member's Jellyfin user (hub.identity's rule: JELLYFIN_USER /
_ALIASES for `you`, JELLYFIN_USER_HER for `her`), writes it into the NAS deploy/.env (backup first, chmod 600, any old
line for the key replaced), recreates joey-hub (the one container that reads it: compose `hub` reads .env and only
hub/player_api.py uses the keys; joey-media reads media.env only, joey-connectors never reads them) and checks the
recreated hub holds a valid token for the right user.

Secrets never reach this computer. Every Jellyfin call runs inside joey-hub (`docker exec`, the hub's JELLYFIN_URL and
JELLYFIN_API_KEY); the Quick Connect secret and the new token sit in the container's /tmp (mode 600) and go from there
straight into the .env on the NAS, so this side only ever sees the code, a yes / no, a length and one letter of the
user name. Output and the log (<main clone>/.joey/logs/joey_<date>.log) carry PASS / FAIL / SKIP per step.

The same file is the in-container helper: `python /tmp/joey_player_tokens.py nas <action> <who>` prints one JSON line.
NAS: JOEY_NAS (default root@nas.local), key JOEY_NAS_KEY (default ~/.ssh/joey_nas), as scripts/joey_common.py.
Test seams: joey_common.ssh_run, sleep, clock (tests/scripts/test_player_tokens.py). Stdlib only, Python 3.12.
"""
import argparse
import json
import os
import shlex
import sys
import time

TOKEN_ENV = {"you": "JELLYFIN_PLAYER_TOKEN_YOU", "her": "JELLYFIN_PLAYER_TOKEN_HER"}
CONTAINER = "joey-hub"
SERVICE = "hub"
DEPLOY_DIR = "/volume1/Docker/joey/life-dashboard/deploy"
ENV_FILE = DEPLOY_DIR + "/.env"
INNER = "/tmp/joey_player_tokens.py"
STATE_DIR = "/tmp"
CLIENT, DEVICE, VERSION = "Joey", "Joey player", "0.1.0"


# ======================================================================= in joey-hub (nas mode)
def _norm(uid):
    return str(uid or "").replace("-", "").lower()


def _urllib_http(method, path, token=None, device_id=None, body=None, timeout=8):
    """One Jellyfin call to the hub's JELLYFIN_URL. Returns (status, parsed JSON or None). Never raises with a URL."""
    import urllib.error
    import urllib.request
    auth = f'MediaBrowser Client="{CLIENT}", Device="{DEVICE}", DeviceId="{device_id or "joey-player"}", Version="{VERSION}"'
    if token:
        auth += f', Token="{token}"'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(os.environ["JELLYFIN_URL"].rstrip("/") + path, data=data, method=method,
                                 headers={"Authorization": auth, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def _hub_household():
    """(ids that are `you`, id that is `her` or None), by the hub's own rule. Reads /Users with the admin key."""
    sys.path.insert(0, os.getcwd())   # docker exec -w /app: the hub package
    from hub import identity
    return identity._resolve(None)


class Inner:
    def __init__(self, http=None, household=None, state_dir=STATE_DIR, environ=None):
        self.http = http or _urllib_http
        self.household = household or _hub_household
        self.state = state_dir
        self.environ = os.environ if environ is None else environ

    def _path(self, kind, who):
        return os.path.join(self.state, f"joey_{kind}_{who}")

    def _put(self, kind, who, text):
        p = self._path(kind, who)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)

    def _get(self, kind, who):
        try:
            with open(self._path(kind, who)) as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""

    def _rm(self, *kinds, who):
        for k in kinds:
            try:
                os.remove(self._path(k, who))
            except FileNotFoundError:
                pass

    def _owner_ok(self, who, uid):
        you, her = self.household()
        return (_norm(uid) in {_norm(u) for u in you}) if who == "you" else (bool(her) and _norm(uid) == _norm(her))

    def _me(self, who, token):
        if not token:
            return {"set": False}
        status, me = self.http("GET", "/Users/Me", token=token, device_id=f"joey-player-{who}")
        if status != 200 or not isinstance(me, dict):
            return {"set": True, "valid": False, "status": status}
        name = str(me.get("Name") or "?")
        return {"set": True, "valid": True, "owner_ok": self._owner_ok(who, me.get("Id")),
                "initial": name[:1].upper(), "len": len(token)}

    def run(self, action, who, stdin_text=""):
        dev = f"joey-player-{who}"
        if action == "members":
            you, her = self.household()
            return {"you": bool(you), "her": bool(her)}
        if action == "initiate":
            status, on = self.http("GET", "/QuickConnect/Enabled")
            if status != 200 or on is not True:
                return {"error": "quick_connect_off"}
            status, qc = self.http("POST", "/QuickConnect/Initiate", device_id=dev)
            if status != 200 or not isinstance(qc, dict) or not qc.get("Secret") or not qc.get("Code"):
                return {"error": f"initiate_{status}"}
            self._put("qc", who, qc["Secret"])
            return {"code": str(qc["Code"])}
        if action == "poll":
            secret = self._get("qc", who)
            if not secret:
                return {"error": "no_secret"}
            status, st = self.http("GET", "/QuickConnect/Connect?secret=" + secret, device_id=dev)
            if status != 200 or not isinstance(st, dict):
                return {"error": f"connect_{status}"}
            return {"approved": st.get("Authenticated") is True}
        if action == "finish":
            secret = self._get("qc", who)
            self._rm("qc", who=who)
            if not secret:
                return {"error": "no_secret"}
            status, auth = self.http("POST", "/Users/AuthenticateWithQuickConnect", device_id=dev,
                                     body={"Secret": secret})
            token = auth.get("AccessToken") if isinstance(auth, dict) else None
            if status != 200 or not token:
                return {"error": f"authenticate_{status}"}
            me = self._me(who, token)
            if not me.get("valid"):
                return {"error": "me_failed"}
            if not me["owner_ok"]:
                self.http("POST", "/Sessions/Logout", token=token, device_id=dev)   # revoke the stray token
                return {"ok": False, "why": "wrong_user", "initial": me["initial"]}
            self._put("pt", who, token)
            return {"ok": True, "initial": me["initial"], "len": me["len"]}
        if action == "me":
            return self._me(who, stdin_text.strip())
        if action == "me-env":
            return self._me(who, self.environ.get(TOKEN_ENV[who], "").strip())
        if action == "drop":
            self._rm("qc", "pt", who=who)
            return {"dropped": True}
        return {"error": "unknown_action"}


def nas_main(argv, stdin_text=None, inner=None):
    """`nas <action> <who>`: one JSON line on stdout. Errors are reported by type only (never a URL or a value)."""
    action, who = argv[0], (argv[1] if len(argv) > 1 else "you")
    try:
        if who not in TOKEN_ENV:
            raise ValueError("who")
        if stdin_text is None:
            stdin_text = sys.stdin.read() if action == "me" else ""
        out = (inner or Inner()).run(action, who, stdin_text)
    except Exception as e:  # noqa: BLE001 - one word, never a traceback
        out = {"error": type(e).__name__}
    print(json.dumps(out))
    return 0


# ======================================================================= on Windows
sleep = time.sleep
clock = time.monotonic


def _jc():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import joey_common
    return joey_common


def inner_cmd(action, who, env_token=False):
    """The remote command for one in-container action. env_token: pipe the .env's current value in on stdin."""
    cmd = f"docker exec -i -w /app {CONTAINER} python {INNER} nas {action} {who}"
    if env_token:
        key = TOKEN_ENV[who]
        cmd = f"sed -n 's/^{key}=//p' {ENV_FILE} 2>/dev/null | tail -n 1 | tr -d '\\r' | " + cmd
    return cmd


def write_cmd(who):
    """Replace the key's line in the NAS .env with the token from the container's /tmp. Prints `WROTE <count> <len>`
    only; the value never leaves the NAS. Backup first (mode 600), trailing-newline guard, CRs stripped."""
    key, src = TOKEN_ENV[who], f"{STATE_DIR}/joey_pt_{who}"
    return "; ".join([
        "set -e", "umask 077", f"ENV={ENV_FILE}", f"KEY={key}",
        f"T=$(docker exec {CONTAINER} cat {src})",
        '[ -n "$T" ] || { echo NO_TOKEN; exit 3; }',
        '[ -e "$ENV" ] || : > "$ENV"', 'chmod 600 "$ENV"',
        'BAK="$ENV.bak-$(date +%F-%H%M%S)"', 'cp "$ENV" "$BAK"', 'chmod 600 "$BAK"',
        '{ grep -v "^$KEY=" "$ENV" || true; } | tr -d "\\r" > "$ENV.new"',
        '[ ! -s "$ENV.new" ] || [ "$(tail -c1 "$ENV.new" | od -An -c | tr -d " ")" = "\\n" ] || echo >> "$ENV.new"',
        "printf '%s=%s\\n' \"$KEY\" \"$T\" >> \"$ENV.new\"", 'chmod 600 "$ENV.new"', 'mv "$ENV.new" "$ENV"',
        f"docker exec {CONTAINER} rm -f {src}",
        'echo "WROTE $(grep -c "^$KEY=" "$ENV") $(printf %s "$T" | wc -c) $(basename "$BAK")"',
    ])


RECREATE_CMD = f"cd {DEPLOY_DIR} && docker compose up -d --no-deps --force-recreate {SERVICE} >/dev/null 2>&1 && echo RECREATED"
HEALTH_CMD = f"docker inspect -f '{{{{.State.Health.Status}}}}' {CONTAINER}"
STAGE_CMD = f"docker exec -i {CONTAINER} sh -c {shlex.quote(f'umask 077; cat > {INNER}')} && echo STAGED"


class Flow:
    def __init__(self, args, runner, jc):
        self.a, self.r, self.jc = args, runner, jc
        self.changed = []

    def ssh(self, cmd, stdin=None, timeout=60):
        return self.jc.ssh_run(cmd, stdin=stdin, timeout=timeout)

    def call(self, action, who, env_token=False):
        r = self.ssh(inner_cmd(action, who, env_token))
        lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("{")]
        if r.returncode != 0 or not lines:
            raise self.jc.Refused(f"in-container helper failed (exit {r.returncode})")
        return json.loads(lines[-1])

    def stage(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            src = f.read()
        r = self.ssh(STAGE_CMD, stdin=src)
        if "STAGED" not in r.stdout:
            raise self.jc.Refused(f"could not copy the helper into {CONTAINER} (is it running?)")
        return f"helper copied into {CONTAINER}"

    def members(self):
        m = self.call("members", "you")
        if "error" in m:
            raise self.jc.Refused(f"could not read the household's Jellyfin users ({m['error']})")
        if not m.get("you"):
            raise self.jc.Refused("no Jellyfin user for `you` (JELLYFIN_USER unset or not in Jellyfin)")
        self.who = [w for w in self.order if m.get(w)]
        self.missing = [w for w in self.order if not m.get(w)]
        return "Jellyfin users found: " + ", ".join(self.who)

    def existing(self, who):
        me = self.call("me", who, env_token=True)
        if not me.get("set"):
            return f"{TOKEN_ENV[who]} not set yet"
        if not me.get("valid"):
            return f"{TOKEN_ENV[who]} is set but Jellyfin refuses it: making a new one"
        if not me.get("owner_ok"):
            return f"{TOKEN_ENV[who]} is set but belongs to another user ({me['initial']}...): replacing it"
        if self.a.rotate:
            return f"{TOKEN_ENV[who]} valid (len {me['len']}, user {me['initial']}...): --rotate, replacing it"
        self.keep = True
        raise self.jc.Skip(f"{TOKEN_ENV[who]} already set and valid (len {me['len']}, user {me['initial']}...); "
                           "nothing to do (use --rotate to replace it)")

    def initiate(self, who):
        out = self.call("initiate", who)
        if "error" in out:
            hint = " (turn it on: Dashboard > General > Quick Connect)" if out["error"] == "quick_connect_off" else ""
            raise self.jc.Refused(f"Quick Connect did not start ({out['error']}){hint}")
        self.r.log("")
        self.r.log(f"  >>> Quick Connect code for {who}: {out['code']}")
        self.r.log(f"  >>> On {'your' if who == 'you' else 'her'} phone, signed in to Jellyfin as "
                   f"{'yourself' if who == 'you' else 'her'}: Jellyfin app > Settings > Quick Connect > enter the code > Authorize.")
        self.r.log(f"  >>> Waiting up to {self.a.timeout} s.")
        self.r.log("")
        return "code shown"

    def wait(self, who):
        end = clock() + self.a.timeout
        while True:
            out = self.call("poll", who)
            if "error" in out:
                self.call("drop", who)
                raise self.jc.Refused(f"Quick Connect stopped ({out['error']}); run it again")
            if out.get("approved"):
                return "approved"
            if clock() >= end:
                self.call("drop", who)
                raise self.jc.Refused(f"not approved within {self.a.timeout} s; nothing written, run it again")
            sleep(self.a.poll)

    def finish(self, who):
        out = self.call("finish", who)
        if out.get("ok"):
            return f"signed in as user {out['initial']}... (the right user), token len {out['len']}"
        self.call("drop", who)
        if out.get("why") == "wrong_user":
            raise self.jc.Refused(f"the code was approved by user {out['initial']}..., not {who}'s Jellyfin user; "
                                  "that token was signed out, nothing written")
        raise self.jc.Refused(f"sign-in failed ({out.get('error', 'unknown')}); nothing written")

    def write(self, who):
        self.r.write_guard(f"write {TOKEN_ENV[who]} into the NAS .env")
        r = self.ssh(write_cmd(who))
        parts = (r.stdout.strip().splitlines() or [""])[-1].split()
        if r.returncode != 0 or len(parts) != 4 or parts[0] != "WROTE" or parts[1] != "1":
            self.call("drop", who)
            raise self.jc.Refused(f"the .env write failed (exit {r.returncode}); the backup is beside it")
        self.changed.append(who)
        return f"token set (len {parts[2]}), {TOKEN_ENV[who]} in deploy/.env (mode 600), backup {parts[3]}"

    def recreate(self):
        self.r.write_guard(f"recreate {CONTAINER} (docker compose up -d --no-deps --force-recreate {SERVICE})")
        r = self.ssh(RECREATE_CMD, timeout=300)
        if "RECREATED" not in r.stdout:
            raise self.jc.Refused(f"compose could not recreate {CONTAINER} (exit {r.returncode})")
        end = clock() + self.a.health_timeout
        while True:
            state = self.ssh(HEALTH_CMD).stdout.strip()
            if state == "healthy":
                return f"{CONTAINER} recreated and healthy"
            if clock() >= end:
                raise self.jc.Refused(f"{CONTAINER} not healthy after {self.a.health_timeout} s (state {state or '?'})")
            sleep(5)

    def verify(self, who):
        me = self.call("me-env", who)
        if me.get("valid") and me.get("owner_ok"):
            return f"{CONTAINER} holds {TOKEN_ENV[who]}: valid, user {me['initial']}..., len {me['len']}"
        raise self.jc.Refused(f"{CONTAINER} does not hold a valid token for {who}")

    def skip(self, why):
        raise self.jc.Skip(why)

    def body(self, r):
        self.order = ["you", "her"] if self.a.who == "both" else [self.a.who]
        r.step("copy the helper into joey-hub", self.stage)
        r.step("find the household's Jellyfin users", self.members)
        for who in self.missing:
            r.step(f"{who}: skip", self.skip,
                   f"no Jellyfin user for {who} yet (JELLYFIN_USER_HER unset or not in Jellyfin); nothing to make")
        for who in self.who:
            self.keep = False
            r.step(f"{who}: current token", self.existing, who)
            if self.keep:
                continue
            r.step(f"{who}: start Quick Connect", self.initiate, who)
            r.step(f"{who}: wait for approval", self.wait, who)
            r.step(f"{who}: sign in and check the user", self.finish, who)
            r.step(f"{who}: write deploy/.env", self.write, who)
        if not self.changed:
            r.step("recreate joey-hub", self.skip, "no token changed; nothing to recreate")
            return
        r.step("recreate joey-hub", self.recreate)
        r.step("copy the helper into the new joey-hub", self.stage)
        for who in self.changed:
            r.step(f"{who}: check the hub's token", self.verify, who)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["nas"]:
        return nas_main(argv[1:])
    jc = _jc()
    jc.utf8_stdio()
    p = argparse.ArgumentParser(prog="player_tokens.py", description="Make Joey's player tokens (JY-257).")
    p.add_argument("--who", choices=["you", "her", "both"], default="both")
    p.add_argument("--rotate", action="store_true", help="replace a token that is still valid")
    p.add_argument("--timeout", type=int, default=300, help="seconds to wait for the Quick Connect approval")
    p.add_argument("--poll", type=float, default=3.0)
    p.add_argument("--health-timeout", type=int, default=120)
    a = p.parse_args(argv)
    try:
        logs = jc.log_dir(jc.clone_root(os.path.dirname(os.path.abspath(__file__))))
    except Exception:  # noqa: BLE001 - outside a clone: log beside the script
        logs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    runner = jc.Runner("player-tokens", log_dir=logs)
    rc = runner.execute("player-tokens", Flow(a, runner, jc).body)
    runner.log(f"log: {runner.log_path}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
