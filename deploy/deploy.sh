#!/bin/sh
# Joey deploy — THE ONLY PATH TO PRODUCTION (rule 13, DECISIONS 2026-08-25).
# gate -> deploy -> smoke -> rollback. Runs ON the NAS as root:
#   /volume1/Docker/joey/life-dashboard/deploy/deploy.sh
#
# NAS notes (DECISIONS 2026-08-31): BusyBox sh (no bash, no brace expansion);
# git has no host binary — every git call goes through an alpine/git container
# with the joey_deploy key (resolver retries on; the pull itself retries 3x, 20 s apart); the full suite runs in the union life-test image
# (production images carry only their own deps).
#
# Usage: deploy.sh [--force]   (--force redeploys even when the pull brought nothing new)
# It detaches from your ssh session and logs to deploy/logs/deploy-<UTC>-<pid>.log (re-attach: tail -f <log>).
# Every run that takes the lock appends ONE line to history.log (review D-03, 2026-10-09):
# PASS | NOTHING-TO-DEPLOY | GATE-FAIL | SKIPPED-LOW-MEMORY | ROLLED-BACK | ROLLBACK-FAILED | ABORTED. PASS and
# NOTHING-TO-DEPLOY also carry tv=<status> (Joey TV release publishing, WP-B8).
set -eu
set -o pipefail

REPO=/volume1/Docker/joey/life-dashboard
DEPLOY_DIR=$REPO/deploy
HISTORY=$DEPLOY_DIR/history.log
STAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
START=$(date +%s)
PREV_SHA=?
NEW_SHA=?
LOGGED=0

# Pre-gate memory check (JY-240, 2026-10-24; B.: "JY-240: adapt"). The gate costs ~400-520 MB of available memory with
# `-n 2` (JY-235: start 1,791 MB, min 1,271-1,381 MB) but only ~243 MB with `-n 1` (measured 2026-10-24: 342 s). By NAS
# available memory just before the gate: >= GATE_FULL_AVAIL_MB runs `-n 2`; GATE_MIN_AVAIL_MB up to just under
# GATE_FULL_AVAIL_MB runs `-n 1`; below GATE_MIN_AVAIL_MB (or swap used over GATE_MAX_SWAP_MB) the gate does not run:
# SKIPPED-LOW-MEMORY (see mem_check / gate_skip). The mode and the available MB go to the output and history.log.
GATE_FULL_AVAIL_MB=1720
GATE_MIN_AVAIL_MB=1460
GATE_MAX_SWAP_MB=1273
MEMINFO=/proc/meminfo
GATE_N=2
GATE_TAG="gate=none avail=?"

# Gate stop set (JY-256, 2026-10-28; B.: "Deploy gate: stop sonarr, radarr, prowlarr and flaresolverr for the gate and
# start them again after (option A + H). Go."). The media apps hold ~430 MB of retained heap within hours of boot, so the
# gate stops these containers (only the running ones) just before mem_check and starts them again right after the suite;
# measured 2026-10-27: ~504 MB freed. `docker stop`, never `docker pause` (a paused process keeps its memory). Spaces or
# commas; the environment overrides it; an empty value turns it off. Each name goes into GATE_STOP_FILE before its stop;
# every exit path starts what is listed (gate_start, once per run; the EXIT trap is the net), and the next run starts
# anything a crashed run left there. The file sits in deploy/logs, not /tmp: the NAS powers off at 22:00, and a stopped
# `unless-stopped` container stays stopped across the reboot. History lines carry stopped=<names>.
GATE_STOP_SET=${GATE_STOP_SET-sonarr radarr prowlarr flaresolverr}
GATE_STOP_FILE=$DEPLOY_DIR/logs/gate-stopped.list
GATE_STOP_TAG=
GATE_STOP_DONE=0

FORCE=0
case "${1:-}" in
    --force) FORCE=1 ;;
    "") ;;
    *) echo "usage: deploy.sh [--force]" >&2; exit 64 ;;
esac

# Survive the ssh session (2026-10-20: the laptop lid closed, ssh dropped, SIGHUP killed deploy.sh during
# `compose up`, hub sat "Created" and joeyhome.net answered 502 for 11 h). The first run re-execs itself under setsid:
# a new session has no controlling terminal, so neither the tty hangup nor sshd's killpg reaches it (ignoring HUP alone
# is not enough: `docker run` re-arms SIGHUP for its signal proxy). HUP is ignored too, stdin is /dev/null and all
# output goes to deploy/logs/deploy-<UTC>-<pid>.log. This shell only follows the log and returns the child's exit code; if it
# dies with the session (or on Ctrl-C) the deploy carries on. The re-exec runs before the lock and the pull, so the
# child is this same pre-pull script, as an undetached run would be.
if [ -z "${JOEY_DEPLOY_DETACHED:-}" ]; then
    LOG_DIR=$DEPLOY_DIR/logs
    mkdir -p "$LOG_DIR"
    LOG=$LOG_DIR/deploy-$(date -u '+%Y%m%dT%H%M%SZ')-$$.log   # pid: two starts in one second never share a log
    : > "$LOG"
    DETACH=
    if command -v setsid >/dev/null 2>&1; then
        DETACH=setsid
    else
        echo "!! setsid not found: HUP is ignored, but a dropped ssh session can still stop a docker run step. Keep the session open. !!" >&2
    fi
    JOEY_DEPLOY_DETACHED=1
    JOEY_DEPLOY_LOG=$LOG
    export JOEY_DEPLOY_DETACHED JOEY_DEPLOY_LOG
    ( trap '' HUP; exec $DETACH sh "$0" "$@" ) </dev/null >"$LOG" 2>&1 &
    CHILD=$!
    echo "deploy running detached (pid $CHILD), log: $LOG"
    echo "safe to disconnect or Ctrl-C: the deploy carries on. Re-attach: tail -f $LOG"
    tail -n +1 -f "$LOG" &
    TAIL=$!
    trap 'kill "$TAIL" 2>/dev/null; echo; echo "stopped watching, the deploy carries on (pid $CHILD). re-attach: tail -f $LOG"; exit 130' INT HUP TERM
    rc=0
    wait "$CHILD" || rc=$?
    sleep 2   # BusyBox tail -f polls once a second: let it print the last lines
    kill "$TAIL" 2>/dev/null || true
    trap - INT HUP TERM
    echo "== deploy.sh exited $rc, full log: $LOG =="
    exit "$rc"
fi

GIT() {
    docker run --rm --dns-opt attempts:3 --dns-opt timeout:2 -v "$REPO":/work -v /root/.ssh:/root/.ssh:ro -w /work \
        -e GIT_SSH_COMMAND='ssh -i /root/.ssh/joey_deploy' alpine/git "$@"
}

log_history() {
    echo "$STAMP $1 prev=$PREV_SHA new=${NEW_SHA:-?} $2${GATE_STOP_TAG:+ $GATE_STOP_TAG} end=$(date -u '+%Y-%m-%dT%H:%M:%SZ') dur=$(($(date +%s) - START))s" >> "$HISTORY"
    LOGGED=1
}

# Joey TV releases (WP-B8; Q36 = a, Q38 = automatic): after smoke PASSES, and on NOTHING-TO-DEPLOY, publish the GitHub
# Release for the tree's tv/VERSION into the tv-app dir that joey-media serves at https://media.joeyhome.net/app/.
# NEVER inside rollback() or gate_fail(). It prints ONE status token for the history line (`tv=<token>`:
# published:<code> | current | pending:<code> | skipped:no-token | FAIL:<reason>) and never fails the deploy - the
# token is the signal (runbook R4: a lingering tv=pending means a deploy was missed after a release). The token file
# deploy/tv.env is NAS-only; the container runs as the image's uid 1000, so the dir is created and handed to it.
TV_APP_DIR=/volume1/Docker/joey/data/tv-app
tv_publish() {
    if [ ! -f "$DEPLOY_DIR/tv.env" ]; then
        echo "skipped:no-token"
        return 0
    fi
    if ! { mkdir -p "$TV_APP_DIR" && chown 1000:1000 "$TV_APP_DIR"; }; then
        echo "FAIL:tv-app-dir"
        return 0
    fi
    tv_status=$(docker run --rm --dns-opt attempts:3 --dns-opt timeout:2 --env-file "$DEPLOY_DIR/tv.env" \
        -v "$REPO":/repo:ro -v "$TV_APP_DIR":/out life-hub python /repo/deploy/tv_publish.py) || true
    echo "${tv_status:-FAIL:no-status}" | tail -n 1
}

# Gate stop set (JY-256): start every container listed in GATE_STOP_FILE ($1 says when, for the log). A container that
# will not start stays listed (the next run tries again) and lands in the history tag as start-failed=<names>. `docker
# start` on a running container does nothing, so a repeat is harmless. Every step is guarded: this runs inside the EXIT
# trap too, where a `set -e` abort would skip the lock release.
start_listed() {
    listed=$(cat "$GATE_STOP_FILE" 2>/dev/null || true)
    if [ -z "$listed" ]; then
        rm -f "$GATE_STOP_FILE" 2>/dev/null || true
        return 0
    fi
    failed=
    for c in $listed; do
        t=$(date +%s)
        if docker start "$c" >/dev/null; then
            echo "gate stop set: started $c in $(($(date +%s) - t)) s ($1)"
        else
            echo "!! gate stop set: could not start $c ($1) — start it by hand: docker start $c !!" >&2
            failed="${failed:+$failed }$c"
        fi
    done
    if [ -n "$failed" ]; then
        printf '%s\n' $failed > "$GATE_STOP_FILE" || true
        GATE_STOP_TAG="${GATE_STOP_TAG:+$GATE_STOP_TAG }start-failed=$(echo $failed | tr ' ' ',')"
    else
        rm -f "$GATE_STOP_FILE" 2>/dev/null || true
    fi
}
# Once per run: after the suite, in gate_fail / gate_skip before their history line, and in the EXIT trap. The flag is
# set only when a pass finished, so a signal mid-start lets the trap finish the job.
gate_start() {
    if [ "$GATE_STOP_DONE" -eq 1 ]; then return 0; fi
    start_listed "$1"
    GATE_STOP_DONE=1
}

# One deploy at a time (2026-10-06: two concurrent deploys made smoke race the hub's
# startup and forced a rollback). mkdir is the atomic lock on BusyBox. The holder's pid
# and log go into the lock dir (2026-10-20, detached deploys): a live holder always blocks,
# a dead one is stale at once, and only a pid-less lock (pre-pid, or the instant between
# mkdir and the write) falls back to "stale after 30 min" — a gate + rollback can run longer.
# The traps release it on every exit path, kill included (`trap EXIT` alone does not fire
# on a signal in ash), and log ABORTED when the run dies before an outcome line was
# written (e.g. `set -e` on a failed pull).
LOCK=/tmp/joey-deploy.lock
if ! mkdir "$LOCK" 2>/dev/null; then
    holder=$(cat "$LOCK/pid" 2>/dev/null || true)
    if { [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; } \
        || { [ -z "$holder" ] && [ -z "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ]; }; then
        held_log=$(cat "$LOCK/log" 2>/dev/null || true)
        echo "!! another deploy is running (pid ${holder:-?}, lock $LOCK) — try again when it finishes !!"
        echo "watch it: tail -f ${held_log:-$DEPLOY_DIR/logs/<newest>}"
        exit 2
    fi
    echo "stale deploy lock (holder ${holder:-unknown} is gone) — removing"
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || { echo "!! another deploy took the lock first — try again when it finishes !!"; exit 2; }
fi
echo "$$" > "$LOCK/pid"
echo "${JOEY_DEPLOY_LOG:-}" > "$LOCK/log"
on_exit() {
    rc=$?
    trap - EXIT
    trap '' INT TERM   # JY-256: a second signal must not cut the restart or the lock release short
    gate_start "on exit $rc" || true
    if [ "$LOGGED" -eq 0 ]; then
        note="exit $rc before an outcome"
        # back to PREV_SHA so a plain rerun redeploys instead of saying NOTHING-TO-DEPLOY
        if [ "$NEW_SHA" != "?" ] && [ "$NEW_SHA" != "$PREV_SHA" ]; then
            GIT reset --hard "$PREV_SHA" >/dev/null 2>&1 && note="$note — tree reset to prev, rerun deploy.sh"
        fi
        log_history "ABORTED" "$note" || true
    fi
    rm -f "$LOCK/pid" "$LOCK/log"
    rmdir "$LOCK" 2>/dev/null || true
    exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# JY-256: a run that died while the stop set was down (killed, or the NAS powered off) left its list; start those first.
# Runs after the lock is taken, so it covers the stale-lock path and never races a live deploy.
start_listed "left by an earlier run" || true

cd "$REPO"
PREV_SHA=$(GIT rev-parse --short HEAD)

echo "== pull (ff-only) =="
# Intermittent container DNS loss under NAS load (2026-10-13: 3 attempts, 5 s apart; JY-206, 2026-10-26: 5 s was too short
# for the resolver to recover, so 3 tries 20 s apart). Each try is logged; the last failure aborts (ABORTED line via the
# EXIT trap). Plain POSIX sh (BusyBox): no bashisms. No sleep after the last try.
PULL_TRIES=3
PULL_WAIT=20
attempt=1
while :; do
    echo "pull attempt $attempt/$PULL_TRIES"
    if GIT pull --ff-only; then break; fi
    if [ "$attempt" -ge "$PULL_TRIES" ]; then echo "pull failed (attempt $attempt/$PULL_TRIES) — aborting" >&2; exit 1; fi
    echo "pull failed (attempt $attempt/$PULL_TRIES) — retrying in $PULL_WAIT s"
    attempt=$((attempt + 1))
    sleep "$PULL_WAIT"
done
NEW_SHA=$(GIT rev-parse --short HEAD)
if [ "$PREV_SHA" = "$NEW_SHA" ] && [ "$FORCE" -eq 0 ]; then
    TV=$(tv_publish)
    log_history "NOTHING-TO-DEPLOY" "already at $NEW_SHA (use --force to redeploy) tv=$TV"
    echo "NOTHING-TO-DEPLOY: already at $NEW_SHA (deploy.sh --force to redeploy), tv=$TV"
    exit 0
fi

# Never leave the tree on an untested SHA: the next run's PREV_SHA (its rollback target)
# must be code that passed the gate (review D-02). The live stack is untouched here.
gate_fail() {
    GIT reset --hard "$PREV_SHA" || echo "!! git reset to $PREV_SHA failed — reset the tree by hand !!" >&2
    gate_start "after a red gate" || true
    log_history "GATE-FAIL" "$1 — tree reset to prev, live stack untouched $GATE_TAG"
    echo "GATE FAILED ($1) — deploy aborted, tree back on $PREV_SHA, live stack untouched." >&2
    exit 1
}

# A low-memory NAS skips the gate instead of pushing it under the floor (JY-240). Same tree handling as gate_fail
# (the next run's PREV_SHA stays tested code), its own outcome word: close-out tools treat only PASS / NOTHING-TO-DEPLOY
# as green, so the next close-out refuses until --after-fail or a later green run.
gate_skip() {
    GIT reset --hard "$PREV_SHA" || echo "!! git reset to $PREV_SHA failed — reset the tree by hand !!" >&2
    GATE_TAG="gate=skip avail=${avail:-?}"
    gate_start "after a skipped gate" || true
    log_history "SKIPPED-LOW-MEMORY" "$1 — gate not run, tree reset to prev, live stack untouched $GATE_TAG"
    echo "SKIPPED-LOW-MEMORY ($1; $GATE_TAG) — gate not run, tree back on $PREV_SHA, live stack untouched. Free memory, then rerun deploy.sh." >&2
    exit 1
}
# Available and swap used in MB from /proc/meminfo (BusyBox awk; `free` column layout varies between BusyBox builds).
# Prints "<avail> <swap_used>"; fails when MemAvailable is missing.
mem_now() {
    awk '/^MemAvailable:/ {a = $2} /^SwapTotal:/ {t = $2} /^SwapFree:/ {f = $2}
        END {if (a == "") exit 1; print int(a / 1024), int((t - f) / 1024)}' "$MEMINFO"
}
mem_check() {
    mem=$(mem_now) || gate_skip "could not read MemAvailable from $MEMINFO"
    avail=${mem% *}
    swap=${mem#* }
    echo "memory: available $avail MB (gate -n 2 at >= $GATE_FULL_AVAIL_MB, -n 1 at >= $GATE_MIN_AVAIL_MB), swap used $swap MB (max $GATE_MAX_SWAP_MB)"
    if [ "$avail" -lt "$GATE_MIN_AVAIL_MB" ]; then
        gate_skip "available $avail MB < $GATE_MIN_AVAIL_MB MB before the gate"
    fi
    if [ "$swap" -gt "$GATE_MAX_SWAP_MB" ]; then
        gate_skip "swap used $swap MB > $GATE_MAX_SWAP_MB MB before the gate"
    fi
    if [ "$avail" -lt "$GATE_FULL_AVAIL_MB" ]; then GATE_N=1; else GATE_N=2; fi
    GATE_TAG="gate=-n$GATE_N avail=$avail"
    echo "memory check: $GATE_TAG"
}
# Stop the running members of GATE_STOP_SET (JY-256). Each name is listed before its stop, so a run that dies mid-stop
# still starts it again; the tag is kept current so an ABORTED line shows what was down.
gate_stop() {
    if [ -z "$GATE_STOP_SET" ]; then
        echo "gate stop set: empty, nothing stopped"
        return 0
    fi
    if before=$(mem_now); then echo "memory before the stop set: available ${before% *} MB"; fi
    mkdir -p "$(dirname "$GATE_STOP_FILE")"
    stopped=
    GATE_STOP_TAG="stopped=none"
    for c in $(echo "$GATE_STOP_SET" | tr ',' ' '); do
        if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" != true ]; then
            echo "gate stop set: $c is not running, left alone"
            continue
        fi
        echo "$c" >> "$GATE_STOP_FILE"
        t=$(date +%s)
        if docker stop "$c" >/dev/null; then
            echo "gate stop set: stopped $c in $(($(date +%s) - t)) s"
            stopped="${stopped:+$stopped,}$c"
            GATE_STOP_TAG="stopped=$stopped"
        else
            echo "!! gate stop set: could not stop $c — it keeps running !!" >&2
        fi
    done
    echo "gate stop set: $GATE_STOP_TAG"
}

echo "== compose validate =="
cd "$DEPLOY_DIR"   # picks up docker-compose.yml + any local override
docker compose config -q || gate_fail "compose config invalid"
# hub + connectors join the media stack's network (N-09); `up` fails without it, so check first
docker network inspect media-server_default >/dev/null 2>&1 \
    || gate_fail "network media-server_default missing — start the media stack first"
# Edge profile on (COMPOSE_PROFILES in deploy/.env enables swag; Joey TV WP-A3). swag runs in host network mode
# (WP-A4, Q44 = a), so it needs no Docker network and the gate has nothing extra to check for it.
edge_active() {
    docker compose config --services 2>/dev/null | grep -qx swag
}

echo "== build test image + FULL SUITE GATE (rule 13) =="
# --network none: the suite is offline-clean (review T-01), so the gate cannot reach the LAN.
# -n $GATE_N (pytest-xdist, review N-44; 2 or 1 by free memory, JY-240): two workers — -n auto (one per core) drove the 3.7 GB NAS to load 12 and 1.2 GB swap on 2026-10-09; the suite was ~9 of the ~10 minutes.
# /tmp is a tmpfs (JY-235, 2026-10-24): on the NAS overlay disk the SQLite-heavy tests made the suite 996 s; in RAM it is
# ~192 s. `exec` is required (Docker's tmpfs is noexec by default, so git skipped a test's hook and the gate went red);
# TMPDIR points pytest's tmp_path there, and retention=failed keeps only failing tests' dirs so 512m is enough.
cd "$REPO"
gate() {
    docker build -q -f deploy/test.Dockerfile -t life-test . >/dev/null \
        && docker run --rm --network none --tmpfs /tmp:rw,exec,size=512m,mode=1777 -e TMPDIR=/tmp life-test python -m pytest -q -n $GATE_N -o tmp_path_retention_policy=failed tests/
}
echo "== gate stop set (JY-256) =="
gate_stop
echo "== memory check (JY-240) =="
mem_check
gate || gate_fail "test build or suite red"
gate_start "after the gate"

# Wait for a service to listen (up to 90 s) before judging it: a fixed 5 s sleep raced the
# hub's startup on a NAS that had just built two images (2026-10-06, two false rollbacks).
wait_for() {
    i=0
    while [ $i -lt 18 ]; do
        if docker compose exec -T "$1" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" 2>/dev/null; then
            return 0
        fi
        i=$((i + 1)); sleep 5
    done
    echo "$1 did not answer /healthz within 90 s" >&2
    return 1
}
wait_for_hub() {
    wait_for hub
}
# The guest front (Joey TV WP-B1): joey-media runs only when COMPOSE_PROFILES carries `media` (WP-B5 step 1).
# edge_active()'s twin: `config --services` lists only active-profile services (proven on Compose v5.3.1, WP-A4).
media_active() {
    docker compose config --services 2>/dev/null | grep -qx joey-media
}
# Same image as the hub, so the same build and the same rollback path; its own smoke checks the media front
# (/healthz front=media, private paths 404, / -> 303) from inside the container.
media_smoke() {
    if ! media_active; then
        return 0
    fi
    wait_for joey-media \
        && docker compose exec -T joey-media python tests/deploy/smoke.py --front media
}
# The public edge (Joey TV WP-A3), only when swag is running (edge profile on). SWAG stays "running" even when
# nginx inside it fails, so `--status restarting` cannot catch a broken conf. The confs are single-file binds, so
# recreate_swag (below), not this reload, applies a conf change; the reload is harmless. Up to 120 s: a fresh swag
# installs its mods and certificate before nginx starts.
# The health curl runs from the host network (a pinned curl image; the NAS has no curl guarantee) to 127.0.0.1:443.
edge_smoke() {
    if [ -z "$(docker compose ps --status running -q swag 2>/dev/null)" ]; then
        return 0
    fi
    i=0
    while [ $i -lt 24 ]; do
        if docker compose exec -T swag nginx -t >/dev/null 2>&1 \
            && docker compose exec -T swag nginx -s reload >/dev/null 2>&1 \
            && [ "$(docker run --rm --network host curlimages/curl:8.23.0 -sk --max-time 10 --resolve jellyfin.joeyhome.net:443:127.0.0.1 https://jellyfin.joeyhome.net/health)" = "Healthy" ]; then
            return 0
        fi
        i=$((i + 1)); sleep 5
    done
    echo "edge: nginx -t / reload / https://jellyfin.joeyhome.net/health not healthy within 120 s" >&2
    docker compose exec -T swag nginx -t >&2 || true
    return 1
}
# The six ./swag confs are single-FILE `:ro` binds, which pin the inode: `git pull` writes new files (new inodes), so a
# running swag keeps the old conf and `nginx -s reload` cannot help (WP-A4, 2026-10-19: PR #5 deployed, jail.local not
# live). Under the edge profile, swag is force-recreated (a ~10 s edge blip) only when the deploy changed a file under
# deploy/swag/ (P6, 2026-10-19). The rollback crosses the same PREV..NEW range, so the same diff decides there.
# --force, or a diff git cannot answer, recreates to be safe. A change to the swag service in docker-compose.yml needs
# nothing here: `compose up` recreates a service whose config changed.
swag_confs_changed() {
    if [ "$FORCE" -eq 1 ]; then return 0; fi
    ! GIT diff --quiet "$PREV_SHA" "$NEW_SHA" -- deploy/swag
}
recreate_swag() {
    if edge_active && swag_confs_changed; then
        docker compose up -d --force-recreate swag
    fi
}
smoke() {
    wait_for_hub \
        && docker compose exec -T hub python tests/deploy/smoke.py \
        && media_smoke \
        && [ -z "$(docker compose ps --status restarting -q)" ] \
        && edge_smoke
}
# One rollback path for every post-gate failure (compose build, compose up, smoke) — review
# D-03: under `set -e` a failing build/up used to exit with no rollback and no history line.
# Everything runs inside `if`, so a failing step lands in ROLLBACK-FAILED instead of aborting.
rollback() {
    echo "!! $1 — rolling back to $PREV_SHA !!" >&2
    cd "$DEPLOY_DIR"
    if GIT reset --hard "$PREV_SHA" \
        && docker compose build \
        && docker compose up -d --remove-orphans \
        && recreate_swag \
        && smoke; then
        log_history "ROLLED-BACK" "$1 on new SHA; previous SHA healthy"
        echo "############ ROLLED BACK to $PREV_SHA ############" >&2
    else
        log_history "ROLLBACK-FAILED" "$1 on new SHA, and the previous SHA is unhealthy too — manual intervention"
        echo "############ ROLLBACK ALSO UNHEALTHY — investigate ############" >&2
    fi
    exit 1
}

echo "== build + converge =="
cd "$DEPLOY_DIR"
docker compose build || rollback "compose build failed"
docker compose up -d --remove-orphans || rollback "compose up failed"
recreate_swag || rollback "swag recreate failed"

echo "== smoke =="
smoke || rollback "smoke failed"

# Reclaim what each build leaves behind (review D-08): dangling images and week-old build cache.
docker image prune -f >/dev/null || true
docker builder prune -f --filter until=168h >/dev/null || true
echo "== tv release =="
TV=$(tv_publish)
log_history "PASS" "suite green, smoke ok tv=$TV $GATE_TAG"
echo "DEPLOY OK: $PREV_SHA -> $NEW_SHA, tv=$TV"
exit 0
