"""joey.py preview up / down / status (JY-012): one preview slot, compose project `joey-preview`, on the NAS.

  python scripts/joey.py preview up <branch | PR number>   build that exact commit and start the slot (replaces a running one)
  python scripts/joey.py preview down                      stop the slot, remove its image, media.db copy and env file
  python scripts/joey.py preview status                    running or not, commit, uptime, memory use, NAS available memory
  Every subcommand takes --dry-run: read-only checks still run, every change prints the NAS script it would run, and a
  check that would stop a real run (window, lock, memory, NAS unreachable) is recorded and the dry run goes on.

up refuses outside 07:00-21:30 Melbourne time, while a deploy holds /tmp/joey-deploy.lock, or when NAS available memory
is under 1,400 MB. Then it TAKES that lock in deploy.sh's own format (JY-228): a directory holding the pid of a detached
holder process on the NAS, so a deploy.sh started meanwhile exits 2 and close-out waits; one docker build at a time.
It is released on success, on failure and after a teardown; the holder removes it itself after LOCK_HOLD_S, so a dead
laptop never leaves a lock. It checks the commit out into /volume1/Docker/joey/preview/src (alpine/git + the read-only
deploy key, as deploy.sh), builds `life-hub-preview`, restores the newest daily media.db backup into the preview data
dir, builds the preview env from an allow-list of the live .env keys (ENV_IN; never a copy, chmod 600, never printed),
writes this repo's deploy/preview/docker-compose.yml next to it, checks the deploy lock is still its own, starts the
slot and polls /healthz inside the container. From the media.db restore on, any FAIL (no /healthz, available memory
under 1,200 MB after the start, an ssh error, a failed compose up) tears the slot down again, so no container, media.db
copy or preview.env is left behind.

NAS scripts go over joey_common.ssh_run as `sh -s` on stdin (UTF-8 bytes, LF kept). Docker commands inside them read
</dev/null so they never eat the rest of the script. Changes are guarded here, not with Runner.ssh_change, so a dry run
prints each whole script. Each script starts with `# joey-preview:<op>`, which the tests' fake NAS dispatches on.
Stdlib only, Python 3.12. Importing this module does no work.
"""
import argparse
import datetime as dt
import re
import secrets
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
META = f"{BASE}/meta"   # preview-only META_CACHE_DIR; posters come from the live img cache, mounted :ro
ENV_FILE = f"{BASE}/preview.env"
COMPOSE_NAS = f"{BASE}/docker-compose.yml"
LIVE_REPO = "/volume1/Docker/joey/life-dashboard"
LIVE_ENVS = (f"{LIVE_REPO}/deploy/.env", f"{LIVE_REPO}/deploy/hub.env")  # hub.env (optional) overrides .env, as compose
MAIN_NETWORK = "deploy_default"  # deploy.sh runs compose in deploy/ with no -p: project "deploy"
BACKUPS = "/volume1/Docker/joey/backups/media"
BACKUP_RE = r"^media-[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.db\.gz$"  # hub/media_backup.py NAME_RE
LOCK = "/tmp/joey-deploy.lock"
LOCK_NOTE = f"{BASE}/lock.log"  # LOCK/log points here: deploy.sh prints it as "watch it: tail -f <log>" when refused
# The holder releases the lock by itself after this, whatever happens to the laptop. JY-234: it outlasts the worst case
# of every step timeout from the take to the release (replace, build, health poll, teardown: about 77 min, pinned by
# tests/scripts/test_joey_preview.py), so the lock never lapses while a run is still working; and it stays under
# close-out's 90 min wait for the lock, so a close-out started meanwhile still gets its turn after a dead laptop.
LOCK_HOLD_S = 88 * 60
PID_RE = re.compile(r"^[0-9]+$")
# Shell helpers for the lock scripts (BusyBox ash and dash). alive: kill -0 succeeds on a zombie, and in the gate
# container (no --init) nothing reaps an orphaned holder, so a pid whose /proc/<pid>/stat state is Z counts as dead
# (JY-228 review). The state is the first field after "(comm) ". With /proc mounted, a pid whose /proc/<pid> directory
# is gone was reaped between kill -0 and the check: dead (JY-239). Fail safe: a /proc/<pid> that exists but whose stat
# reads empty (a failed fork of sed/cut under load, a missing tool) is ALIVE, so a live deploy's lock is never taken.
# With no /proc at all, kill -0 decides.
SH_ALIVE = ("alive() { kill -0 \"$1\" 2>/dev/null || return 1; "
            "if [ -r \"/proc/self/stat\" ] && [ ! -e \"/proc/$1\" ]; then return 1; fi; "
            "z=$(sed 's/^.*) //' \"/proc/$1/stat\" 2>/dev/null | cut -d' ' -f1); [ \"$z\" != Z ]; }")
# nap: one pause of a wait loop that runs at most $naps times. JY-234: where sleep takes whole seconds only (sleep 0.1
# fails), 50 naps of 1 s came close to the 60 s ssh timeout; then it is 10 naps of 1 s. Either way a loop waits at most
# 10 s.
SH_NAP = "nap_s=0.1; naps=50; sleep 0.1 2>/dev/null || { nap_s=1; naps=10; }; nap() { sleep \"$nap_s\"; }"
# ours: the pid is alive AND its command line carries this run's token ($t). The holder is `sh -c '<script>'` and its
# script holds the token, so a pid the kernel has handed to another process since (PID reuse) is never signalled
# (JY-234). A cmdline that reads but lacks the token (another process, or empty: a kernel thread) is not ours, and with
# no /proc/<pid> at all nothing proves it is: the release then treats the holder as gone and removes the lock; a holder
# that was in fact alive only sleeps on, harmless, as its own trap removes nothing once the owner file is gone. Fail
# safe, as JY-239: a live pid whose /proc/<pid> exists but whose cmdline cannot be read (unreadable, a failed tr fork
# under load) counts as ours, so the release signals it and waits rather than drop a live holder's lock.
SH_OURS = ("ours() { alive \"$1\" || return 1; [ -e \"/proc/$1\" ] || return 1; "
           "[ -r \"/proc/$1/cmdline\" ] || return 0; "
           "c=$(tr '\\000' '\\n' < \"/proc/$1/cmdline\" 2>/dev/null) || return 0; "
           "case \"$c\" in *\"$t\"*) return 0;; esac; return 1; }")

WINDOW = (dt.time(7, 0), dt.time(21, 30))
MEM_START_MB = 1400   # 1,200 floor + preview headroom
MEM_FLOOR_MB = 1200
HEALTH_TRIES = 24     # x HEALTH_EVERY_S = 120 s
HEALTH_EVERY_S = 5

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
UNRESOLVED = "<commit>"

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
    "JELLYFIN_URL": ("a LAN address, no credential; with no key the Jellyfin-backed reads fail visibly, "
                     "and guest sign-in is off (the preview runs the private front)"),
    "JELLYFIN_USER": "a display name (owner mapping), no credential",
    "JELLYFIN_USER_HER": "a display name (owner mapping), no credential",
    "JELLYFIN_USER_ALIASES": "display names (not in .env.example), no credential",
    "OMDB_API_KEY": "Metacritic pill, read-only lookups",
    "QUIET_MBPS": "a number on the Quiet mode row; nothing is sent without QBIT_*",
    "FULL_MBPS": "a number on the Full speed confirm; nothing is sent without QBIT_*",
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
    "JELLYFIN_API_KEY": "write: Continue watching marks watched / unwatched / reset on the live Jellyfin (rule 7)",
    "JELLYFIN_POSTER_API_KEY": "write: the JY-260 poster write-back (uploads, locks, reverts Jellyfin images); a secret",
    "POSTERS_DIR": "the live poster store is never a preview path (previews must not write posters)",
    "POSTERS_PER_PASS": "poster backfill pacing; the preview renders no posters",
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
    "META_CACHE_DIR": "set in compose to a preview-only dir",
    "JELLYFIN_LIBRARY_EVERY_S": "connectors only",
    "MEDIA_STATUS_HOSTS": "connectors only",
    "AREAS_PATH": "the image default; a host path would not exist in the preview",
    "HUB_DEV": "local dev only",
    "SUPABASE_URL": "parked connector",
    "SUPABASE_KEY": "parked connector",
    "HA_URL": "parked connector",
    "HA_TOKEN": "parked connector",
    "NAS_SHARES_ROOT": "parked connector",
    "PLAYER_API": "JY-053 player API stays off in the preview (it writes Jellyfin playback progress)",
    "JELLYFIN_PLAYER_TOKEN_YOU": "write: a household member's own Jellyfin token (player progress); JY-053",
    "JELLYFIN_PLAYER_TOKEN_HER": "write: a household member's own Jellyfin token (player progress); JY-053",
    "JELLYFIN_PUBLIC_URL": "the player's stream host; the player API is off in the preview",
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
def nas_sh(script, timeout=60):
    """Run one sh script on the NAS -> (rc, stdout, stderr), stripped."""
    r = jc.ssh_run("sh -s", stdin=script, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def script(op, body):
    return f"# joey-preview:{op}\n{body.strip()}\n"


def first_err(rc, out, err):
    lines = (err or out or "no output").splitlines()
    return f"exit {rc}: {lines[-1] if lines else 'no output'}"


def short(sha):
    return sha[:7] if SHA_RE.match(sha or "") else (sha or "?")


# ---------- the NAS scripts ----------
def s_lock():
    return script("lock", f"""
if [ -d {LOCK} ]; then
    p=$(cat {LOCK}/pid 2>/dev/null || true)
    if [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null; then echo stale; else echo "held ${{p:-?}}"; fi
else
    echo free
fi""")


def s_lock_take(sha, token):
    """mkdir the deploy lock exactly as deploy.sh does (same stale rule; a zombie holder is dead), write this run's
    token to LOCK/owner, then start a detached holder that writes its own pid into LOCK/pid and removes the lock when
    it exits: TERM from s_lock_release, or LOCK_HOLD_S running out. The holder only writes its pid, and only removes
    the lock, while LOCK/owner is this run's token. Prints `held <pid|?>` (nothing changed), or `taken <holder pid>`
    (+ ` stale <old pid>` when a dead holder's lock was cleared). The holder script is in single quotes, so it holds
    none.

    JY-234, the pid write: the holder writes its pid to LOCK/.pid.<pid>, checks the owner, then renames it to LOCK/pid
    (mv is atomic). If the lock dir was replaced after the check (a deploy cleared it and took its own), the temp file
    went with the old dir and the mv fails, so the holder never writes its pid into someone else's lock, and a reader
    never sees a half-written pid. What remains, in the holder's exit trap and in s_lock_release, is a check of
    LOCK/owner followed by rm: a deploy.sh that clears this lock as stale and takes its own in the microseconds
    between the two would lose its pid file. That needs the holder already dead at that instant, and it is the same
    class as deploy.sh's own stale check followed by rm -rf; sh has no atomic compare-and-remove."""
    own = f'[ "$(cat {LOCK}/owner 2>/dev/null)" = "{token}" ]'
    tmp = f"{LOCK}/.pid.$$"
    holder = (f'{own} || exit 0; echo $$ > {tmp} || exit 0; '
              f'if {own}; then mv -f {tmp} {LOCK}/pid 2>/dev/null || exit 0; else rm -f {tmp}; exit 0; fi; s=; '
              f'rel() {{ [ -z "$s" ] || kill "$s" 2>/dev/null; '
              f'if {own} && [ "$(cat {LOCK}/pid 2>/dev/null)" = "$$" ]; then '
              f'rm -f {LOCK}/pid {LOCK}/log {LOCK}/owner {LOCK}/.pid.*; rmdir {LOCK} 2>/dev/null; fi; }}; '
              f'trap rel EXIT; trap "exit 143" TERM; trap "exit 130" INT; '
              f'sleep {LOCK_HOLD_S} & s=$!; wait "$s"')
    return script("lock-take", f"""
L={LOCK}
{SH_ALIVE}
{SH_NAP}
note=
if ! mkdir "$L" 2>/dev/null; then
    holder=$(cat "$L/pid" 2>/dev/null || true)
    if {{ [ -n "$holder" ] && alive "$holder"; }} \\
        || {{ [ -z "$holder" ] && [ -z "$(find "$L" -maxdepth 0 -mmin +30 2>/dev/null)" ]; }}; then
        echo "held ${{holder:-?}}"
        exit 0
    fi
    rm -rf "$L"
    mkdir "$L" 2>/dev/null || {{ echo "held ?"; exit 0; }}
    note=" stale ${{holder:-?}}"
fi
echo {token} > "$L/owner"
mkdir -p {BASE}
echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') preview up {short(sha)} holds the deploy lock while it builds" > {LOCK_NOTE}
echo {LOCK_NOTE} > "$L/log"
DETACH=
if command -v setsid >/dev/null 2>&1; then DETACH=setsid; fi
( trap '' HUP; exec $DETACH sh -c '{holder}' ) </dev/null >/dev/null 2>&1 &
i=0
while :; do
    p=$(cat "$L/pid" 2>/dev/null || true)
    if [ -n "$p" ] && alive "$p"; then echo "taken $p$note"; exit 0; fi
    i=$((i + 1))
    [ "$i" -le "$naps" ] || break
    nap
done
rm -f "$L/pid" "$L/log" "$L/owner" "$L"/.pid.*
rmdir "$L" 2>/dev/null || true
echo "the lock holder did not start" >&2
exit 1""")


def s_lock_release(token):
    """Release the lock this run took, found by its token in LOCK/owner (so it also works after a take whose answer was
    lost): stop the holder (its EXIT trap removes the lock), wait until it is gone or a zombie, then remove whatever of
    the lock is left, so a dead-pid lock is never left. A lock without this run's token is never touched. JY-234: the
    pid in LOCK/pid is signalled only while it is `ours` (its command line carries the token); a reused pid is never
    signalled, and counts as a holder that is gone. The owner check before the rm is the race s_lock_take documents."""
    return script("lock-release", f"""
L={LOCK}
t={token}
{SH_ALIVE}
{SH_NAP}
{SH_OURS}
if [ "$(cat "$L/owner" 2>/dev/null)" != "$t" ]; then echo "not ours"; exit 0; fi
p=$(cat "$L/pid" 2>/dev/null || true)
if [ -n "$p" ] && ours "$p"; then
    kill "$p" 2>/dev/null || true
    i=0
    while ours "$p" && [ "$i" -lt "$naps" ]; do nap; i=$((i + 1)); done
    if ours "$p"; then echo "holder $p did not stop" >&2; exit 1; fi
fi
if [ "$(cat "$L/owner" 2>/dev/null)" = "$t" ]; then
    rm -f "$L/pid" "$L/log" "$L/owner" "$L"/.pid.*
    rmdir "$L" 2>/dev/null || true
fi
if [ -d "$L" ] && [ "$(cat "$L/owner" 2>/dev/null)" = "$t" ]; then echo "lock still held" >&2; exit 1; fi
echo released""")


def s_mem():
    return script("mem", "awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo")


def s_inspect():
    fmt = '{{.State.Status}}|{{.State.StartedAt}}|{{index .Config.Labels "joey.preview.commit"}}'
    return script("inspect", f"docker inspect {CONTAINER} --format '{fmt}' </dev/null 2>/dev/null || echo absent")


def s_stats():
    return script("stats", f"docker stats --no-stream --format '{{{{.MemUsage}}}}' {CONTAINER} </dev/null")


def s_checkout(sha):
    return script("checkout", f"""
set -eu
mkdir -p {SRC}
GIT() {{
    docker run --rm --dns-opt attempts:3 --dns-opt timeout:2 -v {SRC}:/work -v /root/.ssh:/root/.ssh:ro -w /work \\
        -e GIT_SSH_COMMAND='ssh -i /root/.ssh/joey_deploy' alpine/git "$@" </dev/null
}}
if [ ! -d {SRC}/.git ]; then
    URL=$(docker run --rm -v {LIVE_REPO}:/work:ro -w /work alpine/git config --get remote.origin.url </dev/null)
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
    return script("build", f"cd {SRC} && docker build -q -f hub/Dockerfile --label joey.preview.commit={sha} -t {IMAGE} . </dev/null")


def s_restore():
    return script("restore", f"""
set -eu
B=$(ls {BACKUPS} | grep -E '{BACKUP_RE}' | tail -n 1 || true)
[ -n "$B" ] || {{ echo "no daily backup in {BACKUPS}" >&2; exit 3; }}
mkdir -p {SQLITE} {META}
rm -f {SQLITE}/media.db {SQLITE}/media.db-wal {SQLITE}/media.db-shm
gunzip -c "{BACKUPS}/$B" > {SQLITE}/.media.db.tmp
mv {SQLITE}/.media.db.tmp {SQLITE}/media.db
chown -R 1000:1000 {SQLITE} {META}
echo "$B"
""")


def s_env():
    # Each file is followed by a newline: a .env without a trailing newline must never glue its last line onto the next
    # file's first line (an allowed key would then carry a hub.env secret in its value).
    files = " ".join(LIVE_ENVS)
    return script("env", f"""
set -eu
[ -f {LIVE_ENVS[0]} ] || {{ echo "no live .env" >&2; exit 3; }}
umask 077
mkdir -p {BASE}
for f in {files}; do
    if [ -f "$f" ]; then cat "$f"; echo; fi
done | tr -d '\\r' | grep -E '{allow_regex()}' > {BASE}/.preview.env.tmp || true
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
docker network inspect {MAIN_NETWORK} >/dev/null 2>&1 </dev/null || {{ echo "network {MAIN_NETWORK} missing: is the main stack up?" >&2; exit 3; }}
cd {BASE}
PREVIEW_COMMIT={sha} docker compose -p {PROJECT} -f {COMPOSE_NAS} config -q </dev/null
PREVIEW_COMMIT={sha} docker compose -p {PROJECT} -f {COMPOSE_NAS} up -d </dev/null
""")


def s_health():
    probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
    return script("health", f'docker exec {CONTAINER} python -c "{probe}" </dev/null')


def s_logs():
    return script("logs", f"docker logs --tail 20 {CONTAINER} </dev/null 2>&1 || true")


def s_down():
    # From / with -p only: compose works on the project's labels and never reads the compose file or preview.env.
    # A failed down falls back to removing the container; the leftovers step proves what is gone either way.
    return script("compose-down", f"""
cd / && docker compose -p {PROJECT} down </dev/null 2>&1 || {{ echo "compose down failed: removing {CONTAINER} directly"; docker rm -f {CONTAINER} </dev/null 2>&1 || true; }}
""")


def s_image_rm():
    return script("image-rm", f"""
if docker image inspect {IMAGE} >/dev/null 2>&1 </dev/null; then docker image rm {IMAGE} >/dev/null </dev/null && echo removed; else echo absent; fi
""")


def s_files_rm():
    return script("files-rm", f"""
rm -f {SQLITE}/media.db {SQLITE}/media.db-wal {SQLITE}/media.db-shm {SQLITE}/.media.db.tmp {ENV_FILE} {BASE}/.preview.env.tmp
echo removed
""")


def s_leftovers():
    return script("leftovers", f"""
echo "container=$(docker ps -a --filter name=^{CONTAINER}$ --format '{{{{.Names}}}}' </dev/null | tr '\\n' ' ')"
echo "network=$(docker network ls --filter name={PROJECT} --format '{{{{.Name}}}}' </dev/null | tr '\\n' ' ')"
echo "image=$(docker image ls {IMAGE} --format '{{{{.Repository}}}}' </dev/null | tr '\\n' ' ')"
echo "files=$(ls {SQLITE}/media.db {ENV_FILE} {BASE}/.preview.env.tmp 2>/dev/null | tr '\\n' ' ')"
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


def check(r, name, fn):
    """A read-only check. A real run stops on its FAIL; a dry run records what would have stopped it (DRY) and goes on,
    so every later step and command still prints."""
    if not r.dry:
        return r.step(name, fn)

    def guarded():
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - Refused, ssh errors: shown, never fatal in a dry run
            return "DRY", f"a real run would stop here: {e}"

    return r.step(name, guarded)


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


def down_steps(r, d, prefix="", best_effort=False):
    """compose down, image, media.db copy and preview.env, then prove nothing is left. best_effort (a teardown after a
    failure) runs every step even when one fails."""
    def leftovers():
        r.write_guard("check: no container, network, image, media.db copy or preview.env left")
        out = read(d, s_leftovers())
        found = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        left = {k: v.strip() for k, v in found.items() if v.strip()}
        if left or set(found) != {"container", "network", "image", "files"}:
            raise jc.Refused("left behind: " + (", ".join(f"{k} {v}" for k, v in left.items()) or out or "no answer"))
        return "container none, network none, image none, media.db copy and preview.env gone"

    steps = [
        (f"{prefix}compose down", lambda: then(change(r, d, s_down(), 120), f"{PROJECT} down")),
        (f"{prefix}remove image {IMAGE}", lambda: f"image {change(r, d, s_image_rm(), 120)}"),
        (f"{prefix}remove media.db copy and env", lambda: then(change(r, d, s_files_rm()), "media.db copy and preview.env removed")),
        (f"{prefix}nothing left", leftovers),
    ]
    for name, fn in steps:
        try:
            r.step(name, fn)
        except jc.Stop:
            if not best_effort:
                raise


# ---------- up ----------
def cmd_up(r, a, d):
    st = {"sha": UNRESOLVED, "label": a.ref, "slot": {"status": "absent", "started": "", "commit": ""},
          "token": secrets.token_hex(8)}  # this run's mark in LOCK/owner: release touches only its own lock

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

    def take():
        st["took"] = True  # from here a holder may exist, whatever the answer: the finally releases by token
        out = change(r, d, s_lock_take(st["sha"], st["token"]), 60).split()
        if out[:1] == ["held"]:
            st["took"] = False  # a deploy's lock: nothing of ours to release
            pid = out[1] if len(out) > 1 else "?"
            raise jc.Refused(f"a deploy holds {LOCK} (pid {pid}); try again when it finishes")
        if out[:1] != ["taken"] or len(out) < 2 or not PID_RE.match(out[1]):
            raise RuntimeError(f"unexpected answer from the lock: {' '.join(out) or 'nothing'}")
        st["lock_pid"] = out[1]
        stale = f"; cleared a stale lock (pid {out[3]} gone)" if out[2:3] == ["stale"] and len(out) > 3 else ""
        return f"held by this preview (holder pid {out[1]}, gives up after {LOCK_HOLD_S // 60} min){stale}"

    def lock_again():
        if r.dry:  # nothing was taken in a dry run: show whether a deploy would be in the way
            return lock()
        out = read(d, s_lock())
        if out != f"held {st['lock_pid']}":
            raise jc.Refused(f"the deploy lock is no longer this preview's (holder pid {st['lock_pid']}; lock: {out})")
        return f"still held by this preview (pid {st['lock_pid']})"

    def release():
        out = change(r, d, s_lock_release(st["token"]), 60)
        return f"{LOCK} released" if out == "released" else "this run holds no lock (nothing to release)"

    def current():
        st["slot"] = slot(d)
        s = st["slot"]
        if s["status"] == "absent":
            return "slot free"
        return f"slot {s['status']} at {short(s['commit'])}: it will be replaced"

    def mem_before():
        mb = mem_mb(d)
        st["mem_before"] = mb
        if mb < MEM_START_MB:
            raise jc.Refused(f"NAS available memory {mb} MB is under {MEM_START_MB} MB (1,200 floor + preview headroom)")
        return f"{mb} MB available (need {MEM_START_MB})"

    check(r, "deploy window", window)
    check(r, f"resolve {a.ref}", resolve)
    if r.dry:
        check(r, "deploy lock", lock)
    try:
        r.step("take the deploy lock", take)
        locked_up(r, a, d, st, current, mem_before, lock_again)
    finally:
        if st.get("took") or r.dry:
            try:
                r.step("release the deploy lock", release)
            except jc.Stop:  # FAIL row recorded (exit 1); never hides the error that got us here
                pass


def locked_up(r, a, d, st, current, mem_before, lock_again):
    """Everything between taking and releasing the deploy lock: replace, checkout, build, start (or teardown)."""
    check(r, "current slot", current)
    if st["slot"]["status"] != "absent":
        old = short(st["slot"]["commit"])
        r.log(f"replacing the running slot at {old} with {short(st['sha'])}")
        down_steps(r, d, prefix="replace: ")
        st["replaced"] = old
    check(r, "NAS memory before start", mem_before)
    sha = st["sha"]
    r.step(f"checkout {short(sha)} into {SRC}", lambda: f"HEAD {short(change(r, d, s_checkout(sha), 300))}")
    r.step(f"build {IMAGE}", lambda: then(change(r, d, s_build(sha), 1800), f"{IMAGE} built from {short(sha)}"))
    # From here the NAS holds a media.db copy, then preview.env and the slot: any FAIL tears it all down.
    try:
        start_slot(r, d, st, lock_again)
    except jc.Stop:
        if not r.dry:
            r.log("FAIL after the restore: tearing the slot down (container, image, media.db copy, preview.env)")
            down_steps(r, d, prefix="teardown: ", best_effort=True)
        raise


def start_slot(r, d, st, lock_again):
    sha = st["sha"]
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
    r.step("write compose file",
           lambda: then(change(r, d, s_compose_write(COMPOSE_SRC.read_text(encoding="utf-8"))), COMPOSE_NAS))
    check(r, "deploy lock (again, after the build)", lock_again)
    r.step("start joey-preview", lambda: then(change(r, d, s_up(sha), 180), f"{PROJECT} up"))

    def health():
        r.write_guard(f"poll /healthz inside {CONTAINER} every {HEALTH_EVERY_S} s, up to {HEALTH_TRIES * HEALTH_EVERY_S} s")
        for i in range(HEALTH_TRIES):
            rc, _, _ = d.nas(s_health(), 30)
            if rc == 0:
                return f"/healthz answered after {i + 1} poll(s)"
            if i < HEALTH_TRIES - 1:
                d.sleep(HEALTH_EVERY_S)
        _, out, _ = d.nas(s_logs(), 30)
        for line in out.splitlines()[-20:]:
            r.log(f"  log: {line}")
        raise jc.Refused(f"/healthz did not answer within {HEALTH_TRIES * HEALTH_EVERY_S} s")

    r.step("wait for /healthz", health)

    def mem_after():
        r.write_guard("read NAS available memory with the slot up")
        mb = mem_mb(d)
        st["mem_after"] = mb
        if mb < MEM_FLOOR_MB:
            raise jc.Refused(f"{mb} MB available is under the {MEM_FLOOR_MB} MB floor")
        return f"{mb} MB available (floor {MEM_FLOOR_MB})"

    r.step("NAS memory after start", mem_after)

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
        return "slot free (cleaning up anyway)" if s["status"] == "absent" else f"slot {s['status']} at {short(s['commit'])}"

    check(r, "current slot", current)
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

    check(r, "joey-preview", state)
    check(r, "NAS available memory", lambda: f"{mem_mb(d)} MB (floor {MEM_FLOOR_MB})")


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
