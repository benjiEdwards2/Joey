"""joey.py preview up / down / status (JY-012): one preview slot, compose project `joey-preview`, on the NAS.

  python scripts/joey.py preview up <branch | PR number>   build that exact commit and start the slot (replaces a running one)
  python scripts/joey.py preview down                      stop the slot, remove its image, media.db copy and env file
  python scripts/joey.py preview status                    running or not, commit, uptime, memory use, NAS available memory
  Every subcommand takes --dry-run: read-only checks still run, every change prints the NAS script it would run.

up refuses outside 07:00-21:30 Melbourne time, while a deploy holds /tmp/joey-deploy.lock, or when NAS available memory
is under 1,400 MB. It checks the commit out into /volume1/Docker/joey/preview/src (alpine/git + the read-only deploy key,
as deploy.sh), builds `life-hub-preview`, restores the newest daily media.db backup into the preview data dir, builds the
preview env from an allow-list of the live .env keys (ENV_IN; never a copy, chmod 600, never printed), writes this repo's
deploy/preview/docker-compose.yml next to it, starts the slot and polls /healthz inside the container. Available memory
under 1,200 MB after the start tears the slot down again (FAIL).

NAS scripts go over ssh as `sh -s` on stdin, sent as UTF-8 bytes with LF line ends (Windows text-mode stdin sends CRLF,
which breaks sh). Each script starts with `# joey-preview:<op>`, which the tests' fake NAS dispatches on.
Stdlib only, Python 3.12. Importing this module does no work.
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import time
from pathlib import Path

import joey_common as jc

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_SRC = REPO_ROOT / "deploy" / "preview" / "docker-compose.yml"

PROJECT = "joey-preview"
CONTAINER = "joey-preview"
IMAGE = "life-hub-preview"
URL = "https://preview.joeyhome.net"
BASE = "/volume1/Docker/joey/preview"
SRC = f"{BASE}/src"
SQLITE = f"{BASE}/sqlite"
CACHE = f"{BASE}/cache"
ENV_FILE = f"{BASE}/preview.env"
COMPOSE_NAS = f"{BASE}/docker-compose.yml"
LIVE_REPO = "/volume1/Docker/joey/life-dashboard"
LIVE_ENVS = (f"{LIVE_REPO}/deploy/.env", f"{LIVE_REPO}/deploy/hub.env")  # hub.env (optional) overrides .env, as compose
MAIN_NETWORK = "deploy_default"  # deploy.sh runs compose in deploy/ with no -p: project "deploy"
BACKUPS = "/volume1/Docker/joey/backups/media"
BACKUP_RE = r"^media-[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.db\.gz$"  # hub/media_backup.py NAME_RE
LOCK = "/tmp/joey-deploy.lock"

WINDOW = (dt.time(7, 0), dt.time(21, 30))
MEM_START_MB = 1400   # 1,200 floor + preview headroom
MEM_FLOOR_MB = 1200
HEALTH_TRIES = 24     # x HEALTH_EVERY_S = 120 s
HEALTH_EVERY_S = 5

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

# ---------- the env allow-list (deploy/preview/README.md lists the same keys with the same words) ----------
# IN: copied from the live .env into the preview env. Read-only use only.
ENV_IN = {
    "TZ": "container timezone",
    "OWNER_EMAIL_YOU": "maps B.'s Access login to 'you'; read only",
    "OWNER_NAME_YOU": "display name",
    "OWNER_NAME_HER": "display name",
    "ACCESS_JWT_VERIFY": "the preview checks the Access JWT like joey-hub",
    "ACCESS_AUD": "the Access audience the hub checks",
    "ACCESS_TEAM": "the Access team domain for the JWT keys",
    "WEATHER_LAT": "Open-Meteo, keyless read",
    "WEATHER_LON": "Open-Meteo, keyless read",
    "WEATHER_PLACE": "place name in the weather labels",
    "JELLYFIN_URL": "posters, lists, up next (reads)",
    "JELLYFIN_API_KEY": "posters, lists, up next (reads); see the Continue watching note",
    "JELLYFIN_USER": "whose up next to show",
    "JELLYFIN_USER_HER": "her Jellyfin display name",
    "JELLYFIN_USER_ALIASES": "extra Jellyfin names (not in .env.example; read only)",
    "OMDB_API_KEY": "Metacritic pill, read-only lookups",
    "QUIET_MBPS": "a number on the Quiet mode row; nothing is sent without QBIT_*",
    "NAS_SLEEP_WINDOW": "words on the Quiet mode row",
}
# OUT: never copied. FORCED_OFF keys are also pinned "off" in the compose file's environment (which wins over env_file).
FORCED_OFF = ("MEDIA_BACKUP", "PLAY_RECORDER", "MEDIA_WARMUP", "MEDIA_FOLLOW", "MEDIA_AWARDS", "DIGEST")
ENV_OUT = {
    "TUNNEL_TOKEN": "routes the domain; cloudflared only",
    "COMPOSE_PROFILES": "the main stack's profiles; nothing for the preview",
    "CLOUDFLARE_API_TOKEN": "DNS write (edge.env, swag and ddns only)",
    "STAGING": "certificate flag (edge.env, swag only)",
    "ICS_URL_YOU": "connectors only; the URL is the credential",
    "ICS_URL_HER": "connectors only; the URL is the credential",
    "MEDIA_STATUS_HOST": "connectors only",
    "RADARR_URL": "write: search, quality, unmonitor, grab",
    "RADARR_API_KEY": "write: search, quality, unmonitor, grab",
    "SONARR_URL": "write: search, quality, unmonitor, grab",
    "SONARR_API_KEY": "write: search, quality, unmonitor, grab",
    "JELLYSEERR_URL": "write: requests, Follow, remove request",
    "JELLYSEERR_API_KEY": "write: requests, Follow, remove request",
    "QBIT_URL": "write: Quiet mode sets the download cap",
    "QBIT_USER": "write: Quiet mode sets the download cap",
    "QBIT_PASS": "write: Quiet mode sets the download cap",
    "WUD_URL": "write: update triggers",
    "WUD_USER": "write: update triggers",
    "WUD_PASS": "write: update triggers",
    "STACKCTL_URL": "write: restarts the media stack",
    "STACKCTL_TOKEN": "write: restarts the media stack (root-equivalent)",
    "PROWLARR_URL": "connectors only; admin key",
    "PROWLARR_API_KEY": "connectors only; admin key",
    "UPTIME_KUMA_URL": "connectors only",
    "UPTIME_KUMA_API_KEY": "connectors only",
    "SERVER_DISCORD_WEBHOOK": "write: posts to Discord",
    "MEDIA_DISCORD_WEBHOOK": "write: posts to Discord",
    "DIGEST_AT": "the digest is off in the preview",
    "DIGEST": "forced off in compose (Discord digest)",
    "MEDIA_FOLLOW": "forced off in compose (Follow requests through Seerr)",
    "MEDIA_AWARDS": "forced off in compose (Awards loop)",
    "AWARDS_CONTACT": "B.'s e-mail; the Awards loop is off",
    "MEDIA_BACKUP": "forced off in compose (joey-hub stays the one backup writer)",
    "MEDIA_WARMUP": "forced off in compose (warm-up loop)",
    "PLAY_RECORDER": "forced off in compose (play-history poller)",
    "PLAY_POLL_SECONDS": "the play recorder is off",
    "META_CACHE_DIR": "the preview keeps its own cache under its data dir",
    "JELLYFIN_LIBRARY_EVERY_S": "connectors only",
    "MEDIA_STATUS_HOSTS": "connectors only",
    "AREAS_PATH": "the image default; a host path would not exist in the preview",
    "HUB_DEV": "local dev only",
    "SUPABASE_URL": "parked connector",
    "SUPABASE_KEY": "parked connector",
    "HA_URL": "parked connector",
    "HA_TOKEN": "parked connector",
    "NAS_SHARES_ROOT": "parked connector",
}


def allow_regex():
    return "^(" + "|".join(sorted(ENV_IN)) + ")="


# ---------- Melbourne time ----------
def _dst_edge_utc(year, month):
    """Australian DST changes on the first Sunday of April (end) and October (start); both at 16:00 UTC the
    Saturday before (03:00 AEDT / 02:00 AEST)."""
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=8)


def melbourne(now_utc, use_zoneinfo=True):
    """An aware UTC datetime as Melbourne wall time. zoneinfo when the box has a tz database, else the AEST/AEDT rule."""
    if use_zoneinfo:
        try:
            from zoneinfo import ZoneInfo
            return now_utc.astimezone(ZoneInfo("Australia/Melbourne"))
        except Exception:  # noqa: BLE001 - no tz database (slim image): the fixed rule below
            pass
    y = now_utc.year
    dst = now_utc < _dst_edge_utc(y, 4) or now_utc >= _dst_edge_utc(y, 10)
    return now_utc.astimezone(dt.timezone(dt.timedelta(hours=11 if dst else 10)))


def in_window(now_utc):
    t = melbourne(now_utc).time()
    return WINDOW[0] <= t < WINDOW[1]


# ---------- ssh ----------
def ssh_run(cmd, stdin=None, timeout=60):
    """Local stand-in for JY-010's joey_common.ssh_run (switch after the rebase): one command on the NAS, stdin sent as
    UTF-8 bytes with LF line ends. Returns CompletedProcess (text stdout/stderr); RuntimeError when ssh itself fails."""
    nas = os.environ.get("JOEY_NAS") or "root@nas.local"
    key = os.path.expanduser(os.environ.get("JOEY_NAS_KEY") or "~/.ssh/joey_nas")
    data = None if stdin is None else stdin.replace("\r\n", "\n").encode("utf-8")
    try:
        r = subprocess.run(["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", nas, cmd],
                           input=data, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("ssh is not on PATH") from None
    out = subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode("utf-8", "replace"),
                                      r.stderr.decode("utf-8", "replace"))
    if out.returncode == 255:
        first = (out.stderr.strip() or "no output").splitlines()[0]
        raise RuntimeError("ssh to the NAS failed (NAS off 22:00-07:00, or off the home LAN?): " + first)
    return out


def nas_sh(script, timeout=60):
    """Run one sh script on the NAS -> (rc, stdout, stderr), stripped."""
    r = ssh_run("sh -s", stdin=script, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def script(op, body):
    return f"# joey-preview:{op}\n{body.strip()}\n"


def first_err(rc, out, err):
    lines = (err or out or "no output").splitlines()
    return f"exit {rc}: {lines[-1] if lines else 'no output'}"


# ---------- the NAS scripts ----------
def s_lock():
    return script("lock", f"""
if [ -d {LOCK} ]; then
    p=$(cat {LOCK}/pid 2>/dev/null || true)
    if [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null; then echo stale; else echo "held ${{p:-?}}"; fi
else
    echo free
fi""")


def s_mem():
    return script("mem", "awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo")


def s_inspect():
    fmt = '{{.State.Status}}|{{.State.StartedAt}}|{{index .Config.Labels "joey.preview.commit"}}'
    return script("inspect", f"docker inspect {CONTAINER} --format '{fmt}' 2>/dev/null || echo absent")


def s_stats():
    return script("stats", f"docker stats --no-stream --format '{{{{.MemUsage}}}}' {CONTAINER}")


def s_checkout(sha):
    return script("checkout", f"""
set -eu
mkdir -p {SRC}
GIT() {{
    docker run --rm --dns-opt attempts:3 --dns-opt timeout:2 -v {SRC}:/work -v /root/.ssh:/root/.ssh:ro -w /work \\
        -e GIT_SSH_COMMAND='ssh -i /root/.ssh/joey_deploy' alpine/git "$@"
}}
if [ ! -d {SRC}/.git ]; then
    URL=$(docker run --rm -v {LIVE_REPO}:/work:ro -w /work alpine/git config --get remote.origin.url)
    GIT init -q
    GIT remote add origin "$URL"
fi
ok=0
for attempt in 1 2 3; do
    if GIT fetch -q --depth 1 origin {sha}; then ok=1; break; fi
    echo "git fetch failed (attempt $attempt/3)" >&2
    [ "$attempt" -eq 3 ] || sleep 5
done
[ "$ok" -eq 1 ] || exit 1
GIT checkout -q --force --detach FETCH_HEAD
GIT clean -q -fdx
HEAD=$(GIT rev-parse HEAD)
[ "$HEAD" = "{sha}" ] || {{ echo "checked out $HEAD, wanted {sha}" >&2; exit 1; }}
echo "$HEAD"
""")


def s_build(sha):
    return script("build", f"cd {SRC} && docker build -q -f hub/Dockerfile --label joey.preview.commit={sha} -t {IMAGE} .")


def s_restore():
    return script("restore", f"""
set -eu
B=$(ls {BACKUPS} | grep -E '{BACKUP_RE}' | tail -n 1 || true)
[ -n "$B" ] || {{ echo "no daily backup in {BACKUPS}" >&2; exit 3; }}
mkdir -p {SQLITE} {CACHE}/img
rm -f {SQLITE}/media.db {SQLITE}/media.db-wal {SQLITE}/media.db-shm
gunzip -c "{BACKUPS}/$B" > {SQLITE}/.media.db.tmp
mv {SQLITE}/.media.db.tmp {SQLITE}/media.db
chown -R 1000:1000 {SQLITE} {CACHE}
echo "$B"
""")


def s_env():
    live, hub = LIVE_ENVS
    return script("env", f"""
set -eu
[ -f {live} ] || {{ echo "no live .env" >&2; exit 3; }}
umask 077
mkdir -p {BASE}
cat {live} {hub} 2>/dev/null | tr -d '\\r' | grep -E '{allow_regex()}' > {BASE}/.preview.env.tmp || true
chmod 600 {BASE}/.preview.env.tmp
mv {BASE}/.preview.env.tmp {ENV_FILE}
echo "$(grep -c . {ENV_FILE} || true) lines"
cut -d= -f1 {ENV_FILE} | sort -u | tr '\\n' ' '
""")


def s_compose_write(text):
    return script("compose-write", f"""
set -eu
mkdir -p {BASE}
cat > {BASE}/.docker-compose.yml.tmp <<'JOEY_PREVIEW_EOF'
{text.rstrip()}
JOEY_PREVIEW_EOF
mv {BASE}/.docker-compose.yml.tmp {COMPOSE_NAS}
echo written
""")


def s_up(sha):
    return script("up", f"""
set -eu
docker network inspect {MAIN_NETWORK} >/dev/null 2>&1 || {{ echo "network {MAIN_NETWORK} missing: is the main stack up?" >&2; exit 3; }}
cd {BASE}
PREVIEW_COMMIT={sha} docker compose -p {PROJECT} -f {COMPOSE_NAS} config -q
PREVIEW_COMMIT={sha} docker compose -p {PROJECT} -f {COMPOSE_NAS} up -d
""")


def s_health():
    probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
    return script("health", f'docker exec {CONTAINER} python -c "{probe}"')


def s_logs():
    return script("logs", f"docker logs --tail 20 {CONTAINER} 2>&1 || true")


def s_down():
    # From / with -p only: compose works on the project's labels and never reads the compose file or preview.env.
    # A failed down falls back to removing the container; the leftovers step proves what is gone either way.
    return script("compose-down", f"""
cd / && docker compose -p {PROJECT} down 2>&1 || {{ echo "compose down failed: removing {CONTAINER} directly"; docker rm -f {CONTAINER} 2>&1 || true; }}
""")


def s_image_rm():
    return script("image-rm", f"""
if docker image inspect {IMAGE} >/dev/null 2>&1; then docker image rm {IMAGE} >/dev/null && echo removed; else echo absent; fi
""")


def s_files_rm():
    return script("files-rm", f"""
rm -f {SQLITE}/media.db {SQLITE}/media.db-wal {SQLITE}/media.db-shm {SQLITE}/.media.db.tmp {ENV_FILE} {BASE}/.preview.env.tmp
echo removed
""")


def s_leftovers():
    return script("leftovers", f"""
echo "container=$(docker ps -a --filter name=^{CONTAINER}$ --format '{{{{.Names}}}}' | tr '\\n' ' ')"
echo "network=$(docker network ls --filter name={PROJECT} --format '{{{{.Name}}}}' | tr '\\n' ' ')"
echo "image=$(docker image ls {IMAGE} --format '{{{{.Repository}}}}' | tr '\\n' ' ')"
""")


# ---------- deps ----------
class Deps:
    """What the tests replace: the NAS (sh script -> (rc, out, err)), the clock (aware UTC), sleep, ref resolution."""

    def __init__(self, nas=None, now=None, sleep=None, resolve=None, log_dir="default"):
        self.nas = nas or nas_sh
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self.sleep = sleep or time.sleep
        self.resolve = resolve or resolve_ref
        if log_dir == "default":
            try:
                log_dir = jc.log_dir(jc.clone_root())
            except Exception:  # noqa: BLE001 - not in a git repo: no log file
                log_dir = None
        self.log_dir = log_dir


def resolve_ref(ref):
    """(sha, label) for a PR number or a branch name, from GitHub / origin. Read only."""
    if not ref.isdigit() and (not BRANCH_RE.match(ref) or ref.startswith("-") or ".." in ref):
        raise jc.Refused(f"bad branch name {ref!r}")
    clone = jc.clone_root()
    if ref.isdigit():
        pr = jc.gh_json(["pr", "view", ref, "--repo", jc.repo_slug(clone), "--json",
                         "number,state,headRefName,headRefOid"], cwd=clone)
        return pr["headRefOid"], f"PR #{pr['number']} ({pr['headRefName']}, {pr['state']})"
    out = jc.git("ls-remote", "origin", f"refs/heads/{ref}", cwd=clone)
    if not out:
        raise jc.Refused(f"branch {ref} is not on origin")
    return out.split()[0], f"branch {ref}"


# ---------- shared steps ----------
def read(d, op_script, timeout=60):
    """A read-only NAS script: runs in a dry run too. Raises on a non-zero exit."""
    rc, out, err = d.nas(op_script, timeout)
    if rc != 0:
        raise RuntimeError(first_err(rc, out, err))
    return out


def change(r, d, op_script, timeout=60):
    """A state-changing NAS script: in a dry run the step is DRY and shows the whole script."""
    r.write_guard("ssh sh -s <<\n" + op_script.rstrip())
    rc, out, err = d.nas(op_script, timeout)
    if rc != 0:
        raise RuntimeError(first_err(rc, out, err))
    return out


def then(_, detail):
    """Run-then-describe for one-line steps: the command's output is not the detail."""
    return detail


def mem_mb(d):
    out = read(d, s_mem())
    if not out.strip().isdigit():
        raise RuntimeError("could not read MemAvailable")
    return int(out.strip())


def slot(d):
    """{'status': running|exited|...|absent, 'started': str, 'commit': str}."""
    out = read(d, s_inspect())
    if out.strip() in ("", "absent"):
        return {"status": "absent", "started": "", "commit": ""}
    status, _, rest = out.strip().partition("|")
    started, _, commit = rest.partition("|")
    return {"status": status, "started": started, "commit": commit}


def uptime(started, now_utc):
    try:
        t = dt.datetime.strptime(started[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return "?"
    s = max(0, int((now_utc - t).total_seconds()))
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def down_steps(r, d, prefix=""):
    r.step(f"{prefix}compose down", lambda: then(change(r, d, s_down(), 120), f"{PROJECT} down"))
    r.step(f"{prefix}remove image {IMAGE}", lambda: f"image {change(r, d, s_image_rm(), 120)}")
    r.step(f"{prefix}remove media.db copy and env",
           lambda: then(change(r, d, s_files_rm()), "media.db copy and preview.env removed"))

    def leftovers():
        r.write_guard("check: no container, network or image named for the preview")
        out = read(d, s_leftovers())
        found = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        left = {k: v.strip() for k, v in found.items() if v.strip()}
        if left or set(found) != {"container", "network", "image"}:
            raise jc.Refused("left behind: " + (", ".join(f"{k} {v}" for k, v in left.items()) or out or "no answer"))
        return "container none, network none, image none"

    r.step(f"{prefix}nothing left", leftovers)


# ---------- up ----------
def cmd_up(r, a, d):
    st = {}

    def window():
        now = d.now()
        local = melbourne(now)
        if not in_window(now):
            raise jc.Refused(f"outside the NAS window: {local:%H:%M} Melbourne, previews run 07:00-21:30")
        return f"{local:%H:%M} Melbourne, inside 07:00-21:30"

    def resolve():
        sha, label = d.resolve(a.ref)
        if not SHA_RE.match(sha or ""):
            raise jc.Refused(f"{a.ref} did not resolve to a commit")
        st["sha"], st["label"] = sha, label
        return f"{label} at {sha[:7]}"

    def lock():
        out = read(d, s_lock())
        if out.startswith("held"):
            raise jc.Refused(f"a deploy holds {LOCK} (pid {out.split()[-1]}); try again when it finishes")
        return "stale lock (holder gone), no deploy running" if out == "stale" else "no deploy running"

    def current():
        st["slot"] = slot(d)
        s = st["slot"]
        if s["status"] == "absent":
            return "slot free"
        return f"slot {s['status']} at {s['commit'][:7] or '?'}: it will be replaced"

    def mem_before():
        mb = mem_mb(d)
        st["mem_before"] = mb
        if mb < MEM_START_MB:
            raise jc.Refused(f"NAS available memory {mb} MB is under {MEM_START_MB} MB (1,200 floor + preview headroom)")
        return f"{mb} MB available (need {MEM_START_MB})"

    def compose_text():
        return COMPOSE_SRC.read_text(encoding="utf-8")

    r.step("deploy window", window)
    r.step(f"resolve {a.ref}", resolve)
    r.step("deploy lock", lock)
    r.step("current slot", current)
    if st["slot"]["status"] != "absent":
        old = st["slot"]["commit"][:7] or "?"
        r.log(f"replacing the running slot at {old} with {st['sha'][:7]}")
        down_steps(r, d, prefix="replace: ")
        st["replaced"] = old
    r.step("NAS memory before start", mem_before)
    sha = st["sha"]
    r.step(f"checkout {sha[:7]} into {SRC}", lambda: f"HEAD {change(r, d, s_checkout(sha), 300)[:7]}")
    r.step(f"build {IMAGE}", lambda: then(change(r, d, s_build(sha), 1800), f"{IMAGE} built from {sha[:7]}"))
    r.step("restore media.db copy", lambda: f"from {change(r, d, s_restore(), 300)}")

    def env():
        out = change(r, d, s_env())
        lines = out.splitlines()
        keys = set(lines[1].split()) if len(lines) > 1 else set()
        bad = keys - set(ENV_IN)
        if bad:  # cannot happen with the grep, but never start a slot holding a write key
            raise jc.Refused("preview.env holds keys outside the allow-list: " + ", ".join(sorted(bad)))
        if not keys:
            raise jc.Refused("preview.env is empty: no allow-listed key in the live .env")
        missing = sorted(set(ENV_IN) - keys)
        return f"{len(keys)} allow-listed keys, chmod 600" + (f"; not set live: {', '.join(missing)}" if missing else "")

    r.step("build preview.env (allow-list)", env)
    r.step("write compose file", lambda: then(change(r, d, s_compose_write(compose_text())), COMPOSE_NAS))
    r.step("start joey-preview", lambda: then(change(r, d, s_up(sha), 180), f"{PROJECT} up"))

    def health():
        r.write_guard(f"poll /healthz inside {CONTAINER} every {HEALTH_EVERY_S} s, up to {HEALTH_TRIES * HEALTH_EVERY_S} s")
        for i in range(HEALTH_TRIES):
            rc, _, _ = d.nas(s_health(), 30)
            if rc == 0:
                return f"/healthz answered after {i + 1} poll(s)"
            if i < HEALTH_TRIES - 1:
                d.sleep(HEALTH_EVERY_S)
        return "FAIL", f"/healthz did not answer within {HEALTH_TRIES * HEALTH_EVERY_S} s"

    if r.step("wait for /healthz", health) == "FAIL":
        rc, out, _ = d.nas(s_logs(), 30)
        for line in out.splitlines()[-20:]:
            r.log(f"  log: {line}")
        down_steps(r, d, prefix="teardown: ")
        return

    def mem_after():
        r.write_guard("read NAS available memory with the slot up")
        mb = mem_mb(d)
        st["mem_after"] = mb
        if mb < MEM_FLOOR_MB:
            return "FAIL", f"{mb} MB available is under the {MEM_FLOOR_MB} MB floor: tearing the slot down"
        return f"{mb} MB available (floor {MEM_FLOOR_MB})"

    if r.step("NAS memory after start", mem_after) == "FAIL":
        down_steps(r, d, prefix="teardown: ")
        return

    def report():
        r.write_guard("print commit, URL and memory")
        use = read(d, s_stats()).strip() or "?"
        r.log(f"commit  {sha} ({st['label']})")
        if st.get("replaced"):
            r.log(f"replaced  {st['replaced']}")
        r.log(f"URL     {URL} (Access; container {CONTAINER}:8000 on {MAIN_NETWORK})")
        r.log(f"memory  NAS available {st['mem_before']} MB before, {st['mem_after']} MB after; {CONTAINER} {use}")
        return f"{sha[:7]} live in {CONTAINER}"

    r.step("report", report)


# ---------- down / status ----------
def cmd_down(r, a, d):
    def current():
        s = slot(d)
        return "slot free (cleaning up anyway)" if s["status"] == "absent" else f"slot {s['status']} at {s['commit'][:7] or '?'}"

    r.step("current slot", current)
    down_steps(r, d)


def cmd_status(r, a, d):
    def state():
        s = slot(d)
        if s["status"] == "absent":
            return "not running (no joey-preview container)"
        out = f"{s['status']}, commit {s['commit'] or '?'}, up {uptime(s['started'], d.now())}"
        if s["status"] == "running":
            out += f", memory {read(d, s_stats()).strip() or '?'}"
        return out

    r.step("joey-preview", state)
    r.step("NAS available memory", lambda: f"{mem_mb(d)} MB (floor {MEM_FLOOR_MB})")


# ---------- entry ----------
def build_parser():
    p = argparse.ArgumentParser(prog="joey.py preview", description="The joey-preview slot on the NAS: up, down, status.")
    sub = p.add_subparsers(dest="action", required=True)
    up = sub.add_parser("up", help="build a branch or PR head and start the slot (replaces a running one)")
    up.add_argument("ref", help="branch name (e.g. main, feat/JY-012-preview) or PR number")
    sub.add_parser("down", help="stop the slot; remove its image, media.db copy and env file")
    sub.add_parser("status", help="running or not, commit, uptime, memory")
    for s in sub.choices.values():
        s.add_argument("--dry-run", action="store_true", help="print each step and NAS script; change nothing")
    return p


def main(argv, deps=None):
    a = build_parser().parse_args(argv)
    d = deps or Deps()
    r = jc.Runner(f"preview {a.action}", dry_run=a.dry_run, log_dir=d.log_dir)
    body = {"up": cmd_up, "down": cmd_down, "status": cmd_status}[a.action]
    title = " ".join(x for x in ("preview", a.action, getattr(a, "ref", None)) if x)
    return r.execute(title, lambda runner: body(runner, a, d))
