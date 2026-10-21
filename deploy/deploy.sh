#!/bin/sh
# Joey deploy — THE ONLY PATH TO PRODUCTION (rule 13, DECISIONS 2026-08-25).
# gate -> deploy -> smoke -> rollback. Runs ON the NAS as root:
#   /volume1/Docker/joey/life-dashboard/deploy/deploy.sh
#
# NAS notes (DECISIONS 2026-08-31): BusyBox sh (no bash, no brace expansion);
# git has no host binary — every git call goes through an alpine/git container
# with the joey_deploy key (resolver retries on; the pull itself retries 3x, 5 s apart); the full suite runs in the union life-test image
# (production images carry only their own deps).
#
# Usage: deploy.sh [--force]   (--force redeploys even when the pull brought nothing new)
# It detaches from your ssh session and logs to deploy/logs/deploy-<UTC>-<pid>.log (re-attach: tail -f <log>).
# Every run that takes the lock appends ONE line to history.log (review D-03, 2026-10-09):
# PASS | NOTHING-TO-DEPLOY | GATE-FAIL | ROLLED-BACK | ROLLBACK-FAILED | ABORTED.
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
    echo "$STAMP $1 prev=$PREV_SHA new=${NEW_SHA:-?} $2 end=$(date -u '+%Y-%m-%dT%H:%M:%SZ') dur=$(($(date +%s) - START))s" >> "$HISTORY"
    LOGGED=1
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
    trap - EXIT INT TERM
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

cd "$REPO"
PREV_SHA=$(GIT rev-parse --short HEAD)

echo "== pull (ff-only) =="
# intermittent container DNS loss under NAS load (2026-10-13): 3 attempts, 5 s apart; the 3rd failure aborts (ABORTED line via the EXIT trap)
for attempt in 1 2 3; do
    if GIT pull --ff-only; then break; fi
    if [ "$attempt" -eq 3 ]; then echo "pull failed (attempt 3/3) — aborting" >&2; exit 1; fi
    echo "pull failed (attempt $attempt/3) — retrying in 5 s"
    sleep 5
done
NEW_SHA=$(GIT rev-parse --short HEAD)
if [ "$PREV_SHA" = "$NEW_SHA" ] && [ "$FORCE" -eq 0 ]; then
    log_history "NOTHING-TO-DEPLOY" "already at $NEW_SHA (use --force to redeploy)"
    echo "NOTHING-TO-DEPLOY: already at $NEW_SHA (deploy.sh --force to redeploy)"
    exit 0
fi

# Never leave the tree on an untested SHA: the next run's PREV_SHA (its rollback target)
# must be code that passed the gate (review D-02). The live stack is untouched here.
gate_fail() {
    GIT reset --hard "$PREV_SHA" || echo "!! git reset to $PREV_SHA failed — reset the tree by hand !!" >&2
    log_history "GATE-FAIL" "$1 — tree reset to prev, live stack untouched"
    echo "GATE FAILED ($1) — deploy aborted, tree back on $PREV_SHA, live stack untouched." >&2
    exit 1
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
# -n 2 (pytest-xdist, review N-44): two workers — -n auto (one per core) drove the 3.7 GB NAS to load 12 and 1.2 GB swap on 2026-10-09; the suite was ~9 of the ~10 minutes.
cd "$REPO"
gate() {
    docker build -q -f deploy/test.Dockerfile -t life-test . >/dev/null \
        && docker run --rm --network none life-test python -m pytest -q -n 2 tests/
}
gate || gate_fail "test build or suite red"

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
log_history "PASS" "suite green, smoke ok"
echo "DEPLOY OK: $PREV_SHA -> $NEW_SHA"
exit 0
