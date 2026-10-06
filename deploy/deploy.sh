#!/bin/sh
# Joey deploy — THE ONLY PATH TO PRODUCTION (rule 13, DECISIONS 2026-08-25).
# gate -> deploy -> smoke -> rollback. Runs ON the NAS as root:
#   /volume1/Docker/joey/life-dashboard/deploy/deploy.sh
#
# NAS notes (DECISIONS 2026-08-31): BusyBox sh (no bash, no brace expansion);
# git has no host binary — every git call goes through an alpine/git container
# with the joey_deploy key; the full suite runs in the union life-test image
# (production images carry only their own deps).
set -eu
set -o pipefail

REPO=/volume1/Docker/joey/life-dashboard
DEPLOY_DIR=$REPO/deploy
HISTORY=$DEPLOY_DIR/history.log
STAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

GIT() {
    docker run --rm -v "$REPO":/work -v /root/.ssh:/root/.ssh:ro -w /work \
        -e GIT_SSH_COMMAND='ssh -i /root/.ssh/joey_deploy' alpine/git "$@"
}

log_history() {
    echo "$STAMP $1 prev=$PREV_SHA new=${NEW_SHA:-?} $2" >> "$HISTORY"
}

# One deploy at a time (2026-10-06: two concurrent deploys made smoke race the hub's
# startup and forced a rollback). mkdir is the atomic lock on BusyBox; a stale lock
# (older than 30 min) is removed. The trap releases it on any exit path.
LOCK=/tmp/joey-deploy.lock
if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
        echo "stale deploy lock (>30 min) — removing"; rmdir "$LOCK"; mkdir "$LOCK"
    else
        echo "!! another deploy is running (lock $LOCK) — try again when it finishes !!"
        exit 2
    fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

cd "$REPO"
PREV_SHA=$(GIT rev-parse --short HEAD)

echo "== pull (ff-only) =="
GIT pull --ff-only
NEW_SHA=$(GIT rev-parse --short HEAD)

echo "== compose validate =="
cd "$DEPLOY_DIR"   # picks up docker-compose.yml + any local override
docker compose config -q

echo "== build test image + FULL SUITE GATE (rule 13) =="
cd "$REPO"
docker build -q -f deploy/test.Dockerfile -t life-test . >/dev/null
if ! docker run --rm life-test; then
    log_history "GATE-FAIL" "suite red — live stack untouched"
    echo "SUITE RED — deploy aborted, live stack untouched." >&2
    exit 1
fi

echo "== build + converge =="
cd "$DEPLOY_DIR"
docker compose build
docker compose up -d --remove-orphans

echo "== smoke =="
smoke() {
    sleep 5
    docker compose exec -T hub python tests/deploy/smoke.py \
        && [ -z "$(docker compose ps --status restarting -q)" ]
}
if smoke; then
    log_history "PASS" "suite green, smoke ok"
    echo "DEPLOY OK: $PREV_SHA -> $NEW_SHA"
    exit 0
fi

echo "!! SMOKE FAILED — rolling back to $PREV_SHA !!" >&2
GIT reset --hard "$PREV_SHA"
docker compose build
docker compose up -d --remove-orphans
if smoke; then
    log_history "ROLLED-BACK" "smoke failed on new SHA; previous SHA healthy"
    echo "############ ROLLED BACK to $PREV_SHA ############" >&2
else
    log_history "ROLLBACK-FAILED" "smoke failed on BOTH SHAs — manual intervention"
    echo "############ ROLLBACK ALSO UNHEALTHY — investigate ############" >&2
fi
exit 1
