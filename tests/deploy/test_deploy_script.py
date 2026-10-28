"""WP9 — deploy.sh is the only path to production (rule 13).

These tests pin the load-bearing ordering of the script: the full-suite gate
runs BEFORE the live stack is touched, smoke failure triggers a rollback to
the captured PREV_SHA, and every outcome appends to history.log. smoke.py
itself is exercised for real by the deploy (and its unit shape here).
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (REPO_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
SMOKE = (REPO_ROOT / "tests" / "deploy" / "smoke.py").read_text(encoding="utf-8")


def test_script_is_busybox_safe_and_strict():
    assert SCRIPT.startswith("#!/bin/sh")  # NAS has no bash (DECISIONS 2026-08-31)
    assert "set -eu" in SCRIPT
    assert "set -o pipefail" in SCRIPT
    assert "{sqlite," not in SCRIPT  # no brace expansion under BusyBox


# The gate's `docker run` prefix. Re-pointed 2026-10-24 (JY-235): the tmpfs /tmp flags now sit between
# `--network none` and the image name; the offline, full-suite and -n 2 pins below are unchanged in substance.
GATE_RUN = "docker run --rm --network none --tmpfs /tmp:rw,exec,size=512m,mode=1777 -e TMPDIR=/tmp life-test"


def test_gate_runs_before_the_live_stack_is_touched():
    gate = SCRIPT.index(GATE_RUN)
    converge = SCRIPT.index("up -d")
    assert gate < converge, "suite must gate BEFORE containers converge"
    assert "GATE-FAIL" in SCRIPT  # a red suite is logged and aborts


def test_gate_runs_offline():
    """D-09 (2026-10-09): the suite is offline-clean, so the gate container gets no network."""
    assert GATE_RUN in SCRIPT
    assert GATE_RUN.startswith("docker run --rm --network none ")
    assert "docker run --rm life-test" not in SCRIPT


def test_gate_runs_the_full_suite_in_parallel_with_a_pinned_xdist():
    """N-44 (2026-10-09): ~9 of a deploy's ~10 minutes were the suite; xdist spreads it over
    the cores. Still the FULL tests/ tree (rule 13), and xdist is pinned for the image."""
    assert GATE_RUN + " python -m pytest -q -n $GATE_N -o tmp_path_retention_policy=failed tests/" in SCRIPT
    dev = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert "pytest-xdist==3.8.0" in dev


def test_gate_tmp_is_an_exec_tmpfs_with_failed_only_retention():
    """JY-235 (2026-10-24): on the NAS the container's /tmp sat on the slow overlay disk and the SQLite-heavy tests
    made the suite 996 s; a tmpfs /tmp made it 192 s. Docker's tmpfs is noexec unless `exec` is given (git then skipped
    a test's hook: 1 failure), TMPDIR must point pytest's tmp_path at it, and retention=failed keeps 512m enough."""
    line = next(ln for ln in SCRIPT.splitlines() if GATE_RUN in ln)
    tmpfs = re.search(r"--tmpfs (\S+)", line).group(1)
    path, opts = tmpfs.split(":", 1)
    opts = opts.split(",")
    assert path == "/tmp"
    assert "exec" in opts and "noexec" not in opts
    assert "rw" in opts and "size=512m" in opts and "mode=1777" in opts
    assert "-e TMPDIR=/tmp" in line
    assert "-o tmp_path_retention_policy=failed" in line
    assert line.index(GATE_RUN) < line.index("-o tmp_path_retention_policy=failed")  # a pytest option, not docker's


def test_gate_fail_resets_the_tree_to_prev_sha():
    """D-02: a red gate (or invalid compose) must not leave the tree on the untested SHA,
    or the next deploy's PREV_SHA (its rollback target) is code that never passed."""
    body = SCRIPT[SCRIPT.index("gate_fail() {"):]
    body = body[:body.index(chr(10) + "}" + chr(10))]
    assert body.index('GIT reset --hard "$PREV_SHA"') < body.index('log_history "GATE-FAIL"')
    assert "exit 1" in body
    assert 'gate || gate_fail "test build or suite red"' in SCRIPT
    assert 'docker compose config -q || gate_fail' in SCRIPT


def test_one_rollback_function_covers_build_up_and_smoke_failures():
    """D-03: no bare `docker compose build` / `up` that `set -e` could abort on silently."""
    assert "rollback() {" in SCRIPT
    assert SCRIPT.index("rollback() {") < SCRIPT.index("== build + converge ==")
    assert 'docker compose build || rollback "compose build failed"' in SCRIPT
    assert 'docker compose up -d --remove-orphans || rollback "compose up failed"' in SCRIPT
    assert 'smoke || rollback "smoke failed"' in SCRIPT
    bare = [ln.strip() for ln in SCRIPT.splitlines()
            if ln.strip() in ("docker compose build", "docker compose up -d --remove-orphans")]
    assert not bare, bare


def test_every_exit_path_writes_one_history_line_with_a_duration():
    """D-03: an EXIT trap logs ABORTED when no outcome was logged; every line carries dur=NNNs."""
    assert "trap on_exit EXIT" in SCRIPT
    assert '"ABORTED"' in SCRIPT and "LOGGED=1" in SCRIPT
    assert 'dur=$(($(date +%s) - START))s' in SCRIPT and "START=$(date +%s)" in SCRIPT


def test_pass_prunes_images_and_old_build_cache():
    """D-08: dangling images and week-old build cache are reclaimed after a PASS, never fatal."""
    prune = SCRIPT.index("docker image prune -f")
    assert SCRIPT.index('smoke || rollback "smoke failed"') < prune < SCRIPT.index('log_history "PASS"')
    assert "docker builder prune -f --filter until=168h" in SCRIPT


def test_no_new_sha_means_nothing_to_deploy_unless_forced():
    assert "NOTHING-TO-DEPLOY" in SCRIPT and "--force) FORCE=1" in SCRIPT
    check = SCRIPT.index('if [ "$PREV_SHA" = "$NEW_SHA" ] && [ "$FORCE" -eq 0 ]; then')
    assert SCRIPT.index("NEW_SHA=$(GIT rev-parse --short HEAD)") < check < SCRIPT.index("== compose validate ==")


def test_rollback_returns_to_prev_sha_and_logs():
    assert 'PREV_SHA=$(GIT rev-parse --short HEAD)' in SCRIPT
    assert 'GIT reset --hard "$PREV_SHA"' in SCRIPT
    assert "ROLLED-BACK" in SCRIPT
    assert "ROLLBACK-FAILED" in SCRIPT  # both-unhealthy is loud, never silent
    assert "history.log" in SCRIPT


def test_git_goes_through_the_container_with_the_deploy_key():
    assert "alpine/git" in SCRIPT
    assert "joey_deploy" in SCRIPT
    assert "--ff-only" in SCRIPT  # deploys never merge


def test_smoke_runs_inside_the_hub_and_checks_the_hub_endpoints():
    # exec -T inside the hub container: works before AND after WP11 removes
    # the LAN port override.
    assert "docker compose exec -T hub python tests/deploy/smoke.py" in SCRIPT
    assert "127.0.0.1:8000" in SMOKE
    assert "/healthz" in SMOKE


def test_one_deploy_at_a_time_lock_is_taken_before_anything_and_released_on_exit():
    """2026-10-06: two concurrent deploys raced smoke against the hub's startup → rollback.
    The lock is an atomic mkdir (BusyBox-safe), taken before the pull, released by the EXIT trap
    (INT/TERM exit through it too — D-10), and a second runner exits non-zero with a word
    instead of touching the stack."""
    lock = SCRIPT.index('mkdir "$LOCK"')
    assert lock < SCRIPT.index("trap on_exit EXIT") < SCRIPT.index("== pull (ff-only) ==")
    assert 'rmdir "$LOCK" 2>/dev/null || true' in SCRIPT
    assert "trap 'exit 130' INT" in SCRIPT and "trap 'exit 143' TERM" in SCRIPT
    assert "another deploy is running" in SCRIPT and "exit 2" in SCRIPT
    assert "flock" not in SCRIPT  # not guaranteed on the NAS BusyBox


def test_smoke_waits_for_the_hub_to_listen_instead_of_a_fixed_sleep():
    """2026-10-06: two false rollbacks - the hub took longer than 5 s to listen after the
    image build. Smoke now polls /healthz (18 x 5 s) and only then runs smoke.py."""
    assert "wait_for_hub" in SCRIPT and SCRIPT.index("wait_for_hub()") < SCRIPT.index("smoke()")
    assert "/healthz" in SCRIPT and "[ $i -lt 18 ]" in SCRIPT
    assert "    sleep 5" + chr(10) + "    docker compose exec -T hub python tests/deploy/smoke.py" not in SCRIPT


def test_a_missing_media_network_fails_the_gate_before_the_stack_is_touched():
    """N-09: compose `up` cannot start hub/connectors without the external media network."""
    check = SCRIPT.index("docker network inspect media-server_default")
    assert check < SCRIPT.index("== build + converge ==")
    assert 'gate_fail "network media-server_default missing' in SCRIPT[check:check + 200]


def test_pull_retries_three_times_and_git_container_gets_resolver_retries():
    """2026-10-13: three deploys aborted on 'Could not resolve hostname github.com' (UDP DNS loss under NAS load).
    Re-pointed 2026-10-26 (JY-206): 3 tries, now 20 s apart (5 s was too short for the NAS resolver to recover)."""
    assert "--dns-opt attempts:3 --dns-opt timeout:2" in SCRIPT
    assert "PULL_TRIES=3" in SCRIPT and "PULL_WAIT=20" in SCRIPT
    assert "if GIT pull --ff-only; then" in SCRIPT
    assert 'echo "pull attempt $attempt/$PULL_TRIES"' in SCRIPT
    assert 'echo "pull failed (attempt $attempt/$PULL_TRIES) — retrying in $PULL_WAIT s"' in SCRIPT
    assert 'echo "pull failed (attempt $attempt/$PULL_TRIES) — aborting" >&2; exit 1' in SCRIPT
    assert "retrying in 5 s" not in SCRIPT


def test_pull_retry_loop_is_busybox_safe():
    """JY-206: plain POSIX sh only - no bash `for ((..))`, `{1..3}`, `[[ ]]`, `$RANDOM`, `local` or arrays."""
    block = SCRIPT[SCRIPT.index("PULL_TRIES=3"):SCRIPT.index("NEW_SHA=$(GIT rev-parse")]
    for bashism in ("for ((", "{1..", "[[", "$RANDOM", "local ", "=(", "&>"):
        assert bashism not in block, bashism
    assert block.index("sleep") > block.index("retrying in")  # sleeps only after saying so, never after the last try


# ---- Joey TV WP-A3 (2026-10-18): the public edge (swag, `edge` profile) ----

def _body(name: str) -> str:
    body = SCRIPT[SCRIPT.index(chr(10) + name + "() {") + 1:]  # at a line start: "smoke" is not "edge_smoke"
    return body[:body.index(chr(10) + "}" + chr(10))]


def test_smoke_checks_the_edge_only_when_swag_is_running():
    """SWAG stays "running" when nginx inside it fails, so `--status restarting` cannot see a broken conf. The confs
    are single-file binds, so recreate_swag (not this reload) applies a conf change; the reload is harmless. Skipped
    when the edge profile is off."""
    assert SCRIPT.index("edge_smoke() {") < SCRIPT.index("smoke() {" + chr(10) + "    wait_for_hub")
    assert "&& edge_smoke" in _body("smoke")
    edge = _body("edge_smoke")
    guard = edge.index('if [ -z "$(docker compose ps --status running -q swag 2>/dev/null)" ]; then')
    assert "return 0" in edge[guard:guard + 200]  # profile off: nothing to check
    test = edge.index("docker compose exec -T swag nginx -t")
    reload_ = edge.index("docker compose exec -T swag nginx -s reload")
    health = edge.index("--resolve jellyfin.joeyhome.net:443:127.0.0.1 https://jellyfin.joeyhome.net/health")
    assert guard < test < reload_ < health
    assert '= "Healthy"' in edge[health:health + 120]
    # the host-side curl runs from a pinned image (no curl binary assumed on the NAS), host network = 127.0.0.1:443
    assert re.search(r"docker run --rm --network host curlimages/curl:[0-9][^ ]* ", edge)
    assert "curlimages/curl:latest" not in SCRIPT
    assert "return 1" in edge  # a failed edge check fails smoke -> the one rollback path


def test_host_mode_edge_needs_no_network_gate():
    """Mode (a) host (WP-A4, 2026-10-19): swag joins no Docker network, so the pre-gate no longer checks joey-edge
    (jellyfin stays attached to it on the NAS, outside this compose). edge_active() stays, defined before the gate."""
    active = _body("edge_active")
    assert "docker compose config --services" in active and "grep -qx swag" in active
    assert SCRIPT.index("edge_active() {") < SCRIPT.index("== build test image + FULL SUITE GATE")
    assert "joey-edge" not in SCRIPT
    assert "docker network inspect media-server_default" in SCRIPT  # the media network gate is unchanged


def test_edge_profile_recreates_swag_after_up_and_on_rollback_only_on_swag_changes():
    """WP-A4 (2026-10-19, PR #5 deployed but not live): the six swag confs are single-FILE `:ro` binds, which pin the
    inode; `git pull` writes new inodes, so a running swag keeps the old conf and `nginx -s reload` cannot help. Under
    the edge profile swag is force-recreated after the main `up` and before the edge smoke, and the rollback recreates
    it too so a rolled-back conf takes effect. A failed recreate rolls back.
    P6 (2026-10-19): only when the deploy changed a file under deploy/swag/ (each recreate is a ~10 s edge blip). The
    rollback crosses the same PREV..NEW range, so the same diff decides there. --force, or a diff git cannot answer,
    recreates to be safe. A change to the swag service in compose needs nothing here: `compose up` recreates it."""
    changed = _body("swag_confs_changed")
    force = changed.index('if [ "$FORCE" -eq 1 ]; then return 0; fi')
    diff = changed.index('! GIT diff --quiet "$PREV_SHA" "$NEW_SHA" -- deploy/swag')
    assert force < diff
    recreate = _body("recreate_swag")
    guard = recreate.index("if edge_active && swag_confs_changed; then")  # edge_active stays the outer guard
    assert guard < recreate.index("docker compose up -d --force-recreate swag")
    up = SCRIPT.index('docker compose up -d --remove-orphans || rollback "compose up failed"')
    call = SCRIPT.index('recreate_swag || rollback "swag recreate failed"')
    assert (SCRIPT.index("edge_active() {") < SCRIPT.index("swag_confs_changed() {") < SCRIPT.index("recreate_swag() {")
            < SCRIPT.index("rollback() {"))
    assert up < call < SCRIPT.index('smoke || rollback "smoke failed"')
    back = _body("rollback")
    assert (back.index("docker compose up -d --remove-orphans") < back.index("&& recreate_swag")
            < back.index("&& smoke; then"))
    assert "every deploy" not in SCRIPT  # the always-recreate wording is gone


# ---- 2026-10-20 incident: the laptop lid closed, ssh dropped, SIGHUP killed deploy.sh during `compose up`, hub sat
# "Created" and joeyhome.net answered 502 for 11 h. deploy.sh now detaches itself, logs to a file and keeps the lock. ----

def _detach_block() -> str:
    start = SCRIPT.index('if [ -z "${JOEY_DEPLOY_DETACHED:-}" ]; then')
    return SCRIPT[start:SCRIPT.index(chr(10) + "fi" + chr(10), start)]


def test_deploy_detaches_into_its_own_session_before_the_lock_and_the_pull():
    """The first run re-execs itself (marker JOEY_DEPLOY_DETACHED) under setsid: a new session has no controlling
    terminal, so neither the tty hangup nor sshd's killpg on the old process group reaches it. Ignoring HUP alone is not
    enough: `docker run` (GIT, the gate, the edge curl) re-arms SIGHUP for its signal proxy. The re-exec comes after the
    argument check and BEFORE the lock and the pull, so the child is this same pre-pull script (no re-exec ordering
    problem with the self-update), and the parent never holds the lock."""
    block = _detach_block()
    assert SCRIPT.index("usage: deploy.sh [--force]") < SCRIPT.index(block) < SCRIPT.index('mkdir "$LOCK"')
    assert SCRIPT.index(block) < SCRIPT.index("== pull (ff-only) ==")
    assert "command -v setsid" in block and "DETACH=setsid" in block
    assert "JOEY_DEPLOY_DETACHED=1" in block and "export JOEY_DEPLOY_DETACHED JOEY_DEPLOY_LOG" in block
    assert """( trap '' HUP; exec $DETACH sh "$0" "$@" ) </dev/null >"$LOG" 2>&1 &""" in block


def test_detached_deploy_ignores_hup_and_reads_nothing_from_the_terminal():
    """Belt and braces under setsid (and the whole defence when setsid is missing, with a loud warning): HUP is ignored,
    which children such as `docker compose` inherit, stdin is /dev/null and stdout/stderr go only to the log, so a dead
    terminal can neither signal the deploy nor fail one of its writes (EIO/EPIPE under `set -e`)."""
    block = _detach_block()
    assert "trap '' HUP" in block and "</dev/null" in block and '>"$LOG" 2>&1' in block
    assert "setsid not found" in block  # the weaker fallback is never silent


def test_foreground_follows_the_log_and_returns_the_childs_exit_code():
    """B. still watches live: the parent tails the log from line 1 and exits with the child's code (push.sh and the
    history line stay meaningful). Ctrl-C or a dropped session only stops the watcher and prints the re-attach line."""
    block = _detach_block()
    assert 'tail -n +1 -f "$LOG" &' in block
    assert 'wait "$CHILD" || rc=$?' in block and 'exit "$rc"' in block
    trap = block.index("trap 'kill \"$TAIL\" 2>/dev/null;")
    assert "re-attach: tail -f $LOG" in block[trap:trap + 200] and "INT HUP TERM" in block[trap:trap + 200]
    assert block.index('wait "$CHILD"') < block.index('kill "$TAIL" 2>/dev/null || true')


def test_deploy_log_lives_in_deploy_logs_and_is_ignored_by_git_and_docker():
    """deploy/logs/deploy-<UTC>-<pid>.log, one per run. Never committed and never in the life-test build context (the log of
    the running deploy is being written while `docker build .` reads the context)."""
    block = _detach_block()
    assert "LOG_DIR=$DEPLOY_DIR/logs" in block
    assert "LOG=$LOG_DIR/deploy-$(date -u '+%Y%m%dT%H%M%SZ')-$$.log" in block
    git = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    docker = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "/deploy/logs/" in git and "deploy/logs/" in docker


def test_deploy_log_never_gets_secrets():
    """The log takes everything deploy.sh prints: no shell tracing, no env dump, compose config only in quiet mode."""
    assert "set -x" not in SCRIPT and "set -o xtrace" not in SCRIPT
    assert "printenv" not in SCRIPT and not re.search(r"^\s*env\s*$", SCRIPT, re.M)
    assert re.findall(r"docker compose config(?! -q| --services)", SCRIPT) == []


def test_lock_records_its_holder_and_only_a_dead_holder_or_an_old_pidless_lock_is_stale():
    """A detached deploy makes overlap likelier, and a legit deploy (gate + rollback) can pass 30 min, so age alone no
    longer breaks the lock: the holder's pid (and log) are written into the lock dir; a live pid always blocks, a dead
    one is stale at once, and only a pid-less lock (pre-pid, or the instant between mkdir and the write) falls back to
    the 30-min rule. A lost race for the fresh lock exits 2 instead of running."""
    lock = SCRIPT[SCRIPT.index("LOCK=/tmp/joey-deploy.lock"):SCRIPT.index("on_exit() {")]
    assert 'holder=$(cat "$LOCK/pid" 2>/dev/null || true)' in lock
    assert 'kill -0 "$holder"' in lock and "-mmin +30" in lock
    assert lock.index('kill -0 "$holder"') < lock.index('rm -rf "$LOCK"') < lock.index('echo "$$" > "$LOCK/pid"')
    assert 'mkdir "$LOCK" 2>/dev/null || {' in lock  # the re-take after a stale break never runs unlocked
    assert '"${JOEY_DEPLOY_LOG:-}" > "$LOCK/log"' in lock and "tail -f" in lock  # the refusal says how to watch
    assert 'rm -f "$LOCK/pid" "$LOCK/log"' in _body("on_exit")


def test_detach_uses_only_busybox_safe_forms():
    """BusyBox ash/applets: no bash-isms, no util-linux-only setsid flags, no GNU `tail --pid`, no disown."""
    for bad in ("setsid -w", "setsid -f", "--pid", "disown", "[[", "<<<", "$(<"):
        assert bad not in SCRIPT, bad


# ---- Joey TV WP-B8 step 5 (Q38 = automatic): deploy.sh publishes the tv-<code> release after smoke passes ----

def test_tv_publish_runs_after_smoke_and_on_nothing_to_deploy_only():
    """After smoke PASSES (after the prunes, right before the PASS line) and in the NOTHING-TO-DEPLOY path; never in
    rollback() / gate_fail() / recreate_swag(), and never before smoke."""
    body = _body("tv_publish")
    assert ('docker run --rm --dns-opt attempts:3 --dns-opt timeout:2 --env-file "$DEPLOY_DIR/tv.env"' in body
            and '-v "$REPO":/repo:ro -v "$TV_APP_DIR":/out life-hub python /repo/deploy/tv_publish.py' in body)
    assert "TV_APP_DIR=/volume1/Docker/joey/data/tv-app" in SCRIPT
    calls = [i for i in range(len(SCRIPT)) if SCRIPT.startswith("TV=$(tv_publish)", i)]
    assert len(calls) == 2
    nothing = SCRIPT.index('if [ "$PREV_SHA" = "$NEW_SHA" ] && [ "$FORCE" -eq 0 ]; then')
    assert nothing < calls[0] < SCRIPT.index('log_history "NOTHING-TO-DEPLOY"') < SCRIPT.index("== compose validate ==")
    assert (SCRIPT.index('smoke || rollback "smoke failed"') < SCRIPT.index("docker builder prune -f")
            < calls[1] < SCRIPT.index('log_history "PASS"'))
    for name in ("rollback", "gate_fail", "recreate_swag", "smoke", "media_smoke", "edge_smoke", "on_exit"):
        assert "tv_publish" not in _body(name), name
    assert SCRIPT.index("tv_publish() {") < nothing   # defined before its first use


def test_tv_status_lands_in_the_single_history_line():
    assert 'log_history "PASS" "suite green, smoke ok tv=$TV $GATE_TAG"' in SCRIPT
    assert 'log_history "NOTHING-TO-DEPLOY" "already at $NEW_SHA (use --force to redeploy) tv=$TV"' in SCRIPT
    assert SCRIPT.count('log_history "PASS"') == 1 and SCRIPT.count('log_history "NOTHING-TO-DEPLOY"') == 1


def test_tv_publish_never_fails_the_deploy_and_skips_without_a_token():
    body = _body("tv_publish")
    guard = body.index('if [ ! -f "$DEPLOY_DIR/tv.env" ]; then')
    assert 'echo "skipped:no-token"' in body[guard:guard + 120]
    assert guard < body.index("docker run")
    assert ") || true" in body                    # a failed container is a status, not a `set -e` abort
    assert 'echo "${tv_status:-FAIL:no-status}" | tail -n 1' in body
    assert "exit" not in body and "return 1" not in body
    assert 'chown 1000:1000 "$TV_APP_DIR"' in body   # the life-hub image runs as uid 1000


def test_tv_token_file_is_never_committed_or_in_the_build_context():
    git = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    docker = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "*.env" in git and "!*.env.example" in git          # deploy/tv.env ignored, the template kept
    assert "**/*.env" in docker and "!**/*.env.example" in docker
    example = (REPO_ROOT / "deploy" / "tv.env.example").read_text(encoding="utf-8")
    assert re.search(r"^GH_TV_TOKEN=$", example, re.M)            # empty in the template


# ---- JY-240 (2026-10-24): pre-gate memory check. The gate costs ~400-450 MB of available memory (JY-235), so it
# starts only with swap used <= 1,273 MB and adapts to available memory (B.'s pick "JY-240: adapt", 2026-10-24):
# >= 1,720 MB gate with -n 2; 1,460-1,719 MB gate with -n 1; below 1,460 MB SKIPPED-LOW-MEMORY, tree back on prev. ----

def test_memory_floor_is_a_dated_variable_at_the_top():
    top = SCRIPT[:SCRIPT.index('if [ -z "${JOEY_DEPLOY_DETACHED:-}" ]; then')]
    assert "GATE_FULL_AVAIL_MB=1720" + chr(10) in top and "GATE_MIN_AVAIL_MB=1460" + chr(10) in top
    assert "GATE_MAX_SWAP_MB=1273" + chr(10) in top
    assert "MEMINFO=/proc/meminfo" + chr(10) in top
    assert "JY-240, 2026-10-24" in top


def test_memory_check_runs_right_before_the_gate_and_after_the_pull():
    call = SCRIPT.index("mem_check" + chr(10) + 'gate || gate_fail "test build or suite red"')
    assert SCRIPT.index("NEW_SHA=$(GIT rev-parse --short HEAD)") < SCRIPT.index("mem_check() {") < call
    assert SCRIPT.index("== memory check (JY-240) ==") < call < SCRIPT.index("== build + converge ==")
    assert SCRIPT.count("mem_check" + chr(10)) == 1  # one call: the gate path only, not NOTHING-TO-DEPLOY


def test_gate_skip_resets_the_tree_logs_its_own_word_and_exits_non_zero():
    body = _body("gate_skip")
    assert body.index('GIT reset --hard "$PREV_SHA"') < body.index('log_history "SKIPPED-LOW-MEMORY"')
    assert "exit 1" in body and "docker run" not in body
    check = _body("mem_check")
    assert '-lt "$GATE_MIN_AVAIL_MB"' in check and '-lt "$GATE_FULL_AVAIL_MB"' in check
    assert '-gt "$GATE_MAX_SWAP_MB"' in check
    assert 'gate_skip "could not read MemAvailable' in check  # unreadable memory fails closed
    assert "SKIPPED-LOW-MEMORY" in SCRIPT[:SCRIPT.index("set -eu")]  # listed with the other outcome words


def test_gate_worker_count_comes_from_the_memory_band_and_is_logged():
    assert "-n $GATE_N " in _body("gate") and "-n 2 " not in _body("gate")
    assert 'GATE_TAG="gate=-n$GATE_N avail=$avail"' in _body("mem_check")
    assert 'GATE_TAG="gate=skip avail=${avail:-?}"' in _body("gate_skip")  # unreadable memory: avail=?
    # the PASS line keeps its readable prefix (close-out, budgets and JoeyTV match ` PASS `, new=, dur=); the tag follows
    assert 'log_history "PASS" "suite green, smoke ok tv=$TV $GATE_TAG"' in SCRIPT


def _pipefail_sh():
    """Same pick as tests/deploy/test_media_offsite.py: a local POSIX sh that, like NAS BusyBox sh, takes pipefail."""
    for argv in (["sh"], ["busybox", "sh"], ["bash", "--posix"]):
        exe = shutil.which(argv[0])
        if exe and subprocess.run([exe, *argv[1:], "-c", "set -o pipefail"],
                                  capture_output=True, timeout=30).returncode == 0:
            return [exe, *argv[1:]]
    return None


SH = _pipefail_sh()

# Fake docker: logs every call, answers the alpine/git rev-parse (prev, then new SHA) and turns the suite red, so a run
# that reaches the gate stops at GATE-FAIL and never touches the live stack.
# JY-256: it also keeps the running containers in $FAKE_DIR/running (`inspect -f`, `stop`, `start`); each stop adds
# FAKE_FREE_PER_STOP MB to the fake MemAvailable; FAKE_START_FAILS names containers that will not start; FAKE_SUITE_OK
# turns the suite green (the run then goes on to build, up and smoke, all answered 0); FAKE_SUITE_SIGNAL makes the suite
# send TERM to deploy.sh; FAKE_BUILD_FAILS makes `compose build` fail (rollback); FAKE_STOP_FAILS names containers whose
# `docker stop` fails (they keep running).
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$FAKE_DIR/docker.log"
for a; do last=$a; done
case "$*" in
    *rev-parse*)
        n=$(cat "$FAKE_DIR/revs" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE_DIR/revs"
        if [ "$n" -eq 1 ]; then echo aaaaaaa; else echo bbbbbbb; fi ;;
    *"pull --ff-only"*)
        n=$(cat "$FAKE_DIR/pulls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE_DIR/pulls"
        if [ "$n" -le "${FAKE_PULL_FAILS:-0}" ]; then echo "fatal: Could not resolve hostname github.com" >&2; exit 128; fi ;;
    *"life-test python"*)
        if [ -n "${FAKE_SUITE_SIGNAL:-}" ]; then kill -TERM "$PPID"; exit 1; fi
        if [ -n "${FAKE_SUITE_OK:-}" ]; then exit 0; fi
        exit 1 ;;
    "inspect -f"*)
        if grep -qx "$last" "$FAKE_DIR/running" 2>/dev/null; then echo true; else echo false; fi ;;
    "stop "*)
        case " ${FAKE_STOP_FAILS:-} " in *" $last "*) echo "Error: cannot stop $last" >&2; exit 1 ;; esac
        grep -vx "$last" "$FAKE_DIR/running" > "$FAKE_DIR/running.tmp" || true
        mv "$FAKE_DIR/running.tmp" "$FAKE_DIR/running"
        if [ -n "${FAKE_FREE_PER_STOP:-}" ]; then
            add=$((FAKE_FREE_PER_STOP * 1024))
            awk -v add="$add" '/^MemAvailable:/ {$0 = "MemAvailable: " ($2 + add) " kB"} {print}' "$FAKE_DIR/meminfo" > "$FAKE_DIR/meminfo.tmp"
            mv "$FAKE_DIR/meminfo.tmp" "$FAKE_DIR/meminfo"
        fi ;;
    "start "*)
        case " ${FAKE_START_FAILS:-} " in *" $last "*) echo "Error: cannot start $last" >&2; exit 1 ;; esac
        echo "$last" >> "$FAKE_DIR/running" ;;
    "compose build")
        if [ -n "${FAKE_BUILD_FAILS:-}" ]; then exit 1; fi ;;
esac
exit 0
"""

# Fake chown (JY-260 posters_dir): records its arguments; FAKE_CHOWN_FAILS makes it fail. The real NAS path is never
# touched: the harness points JOEY_POSTERS_DIR at a temp dir.
FAKE_CHOWN = """#!/bin/sh
echo "$*" >> "$FAKE_DIR/chown.log"
if [ -n "${FAKE_CHOWN_FAILS:-}" ]; then echo "chown: Operation not permitted" >&2; exit 1; fi
exit 0
"""

# Fake sleep: records the seconds asked for and returns at once, so the retry back-off is checked without waiting.
FAKE_SLEEP = """#!/bin/sh
echo "$*" >> "$FAKE_DIR/sleep.log"
exit 0
"""


def _meminfo(avail_mb, swap_used_mb, swap_total_mb=4096):
    lines = ["MemTotal:        3800000 kB", "MemFree:          200000 kB"]
    if avail_mb is not None:
        lines.append(f"MemAvailable:    {avail_mb * 1024} kB")
    lines += [f"SwapTotal:       {swap_total_mb * 1024} kB",
              f"SwapFree:        {(swap_total_mb - swap_used_mb) * 1024} kB"]
    return chr(10).join(lines) + chr(10)


def _run_deploy(tmp_path, avail_mb, swap_used_mb, pull_fails=0, running=(), free_per_stop=0, suite_ok=False,
                suite_signal=False, start_fails=(), stop_set=None, inject=None, leftover=None, stale_lock=False,
                build_fails=False, stop_fails=(), posters_fail=None):
    repo = tmp_path / "repo"
    (repo / "deploy").mkdir(parents=True)
    if leftover is not None:  # JY-256: a stop list left by a crashed run
        (repo / "deploy" / "logs").mkdir()
        (repo / "deploy" / "logs" / "gate-stopped.list").write_text(leftover, encoding="utf-8", newline=chr(10))
    if stale_lock:  # a lock whose holder is gone
        (tmp_path / "lock").mkdir()
        (tmp_path / "lock" / "pid").write_text("999999" + chr(10), encoding="utf-8", newline=chr(10))
    fake = tmp_path / "fake"
    (fake / "bin").mkdir(parents=True)
    (fake / "running").write_text("".join(c + chr(10) for c in running), encoding="utf-8", newline=chr(10))
    (fake / "bin" / "docker").write_text(FAKE_DOCKER, encoding="utf-8", newline=chr(10))
    (fake / "bin" / "docker").chmod(0o755)
    (fake / "bin" / "sleep").write_text(FAKE_SLEEP, encoding="utf-8", newline=chr(10))
    (fake / "bin" / "sleep").chmod(0o755)
    (fake / "bin" / "chown").write_text(FAKE_CHOWN, encoding="utf-8", newline=chr(10))
    (fake / "bin" / "chown").chmod(0o755)
    posters = tmp_path / "posters" / "out"
    if posters_fail == "mkdir":   # a plain file where a parent folder should be: mkdir -p fails
        (tmp_path / "posters").write_text("not a folder", encoding="utf-8")
    (fake / "meminfo").write_text(_meminfo(avail_mb, swap_used_mb), encoding="utf-8", newline=chr(10))
    script = SCRIPT
    for old, new in (("REPO=/volume1/Docker/joey/life-dashboard", "REPO=" + repo.as_posix()),
                     ("MEMINFO=/proc/meminfo", "MEMINFO=" + (fake / "meminfo").as_posix()),
                     ("LOCK=/tmp/joey-deploy.lock", "LOCK=" + (tmp_path / "lock").as_posix())):
        assert script.count(old + chr(10)) == 1, old
        script = script.replace(old + chr(10), new + chr(10))
    # The retry sleep is pointed at the fake by absolute path: a PATH lookup is not enough on every sh (a BusyBox ash with
    # standalone applets, or a builtin, runs the real `sleep` and the CI run on Linux saw an empty sleep.log; JY-206).
    wait = '    sleep "$PULL_WAIT"' + chr(10)
    assert script.count(wait) == 1
    script = script.replace(wait, '    "' + (fake / "bin" / "sleep").as_posix() + '" "$PULL_WAIT"' + chr(10))
    if inject:  # (anchor, replacement): e.g. an error that set -e turns into an abort
        assert script.count(inject[0]) == 1, inject[0]
        script = script.replace(*inject)
    path = tmp_path / "deploy.sh"
    path.write_text(script, encoding="utf-8", newline=chr(10))
    env = dict(os.environ, JOEY_DEPLOY_DETACHED="1", FAKE_DIR=fake.as_posix(), FAKE_PULL_FAILS=str(pull_fails),
               FAKE_FREE_PER_STOP=str(free_per_stop or ""), FAKE_SUITE_OK="1" if suite_ok else "",
               FAKE_SUITE_SIGNAL="1" if suite_signal else "", FAKE_START_FAILS=" ".join(start_fails),
               FAKE_BUILD_FAILS="1" if build_fails else "", FAKE_STOP_FAILS=" ".join(stop_fails),
               JOEY_POSTERS_DIR=posters.as_posix(), FAKE_CHOWN_FAILS="1" if posters_fail == "chown" else "",
               PATH=str(fake / "bin") + os.pathsep + os.environ.get("PATH", ""))
    env.pop("GATE_STOP_SET", None)  # the script's default, unless a test sets it
    if stop_set is not None:
        env["GATE_STOP_SET"] = stop_set
    r = subprocess.run([*SH, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    calls = (fake / "docker.log").read_text(encoding="utf-8") if (fake / "docker.log").exists() else ""
    history = (repo / "deploy" / "history.log").read_text(encoding="utf-8").splitlines()
    return r, calls, history


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
@pytest.mark.parametrize("avail, swap, workers, why", [
    (1459, 500, None, "available 1459 MB < 1460 MB before the gate"),
    (1300, 0, None, "available 1300 MB < 1460 MB before the gate"),
    (1460, 1273, 1, None),                          # on the lower edge (and swap on its limit): gate with -n 1
    (1588, 0, 1, None),                             # the measured NAS case: -n 1
    (1719, 0, 1, None),
    (1720, 0, 2, None),                             # on the upper edge: the full gate
    (2000, 1273, 2, None),
    (2000, 1274, None, "swap used 1274 MB > 1273 MB before the gate"),
    (None, 0, None, "could not read MemAvailable"),  # unreadable: fail closed
])
def test_fake_meminfo_drives_skip_vs_gate(tmp_path, avail, swap, workers, why):
    r, calls, history = _run_deploy(tmp_path, avail, swap)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert len(history) == 1, history
    assert "compose build" not in calls and "up -d" not in calls  # the live stack is never touched
    assert "pull --ff-only" in calls and "compose config -q" in calls
    if workers:
        assert "life-test python -m pytest" in calls
        assert f"pytest -q -n {workers} " in calls and f"-n {3 - workers} " not in calls
        tag = f"gate=-n{workers} avail={avail}"
        assert tag in out  # printed in the output ...
        assert " GATE-FAIL prev=aaaaaaa new=bbbbbbb " in history[0] and tag in history[0]  # ... and in history.log
    else:
        assert "life-test" not in calls  # neither the test-image build nor the suite
        assert " SKIPPED-LOW-MEMORY prev=aaaaaaa new=bbbbbbb " in history[0] and why in history[0]
        assert "gate not run, tree reset to prev, live stack untouched" in history[0]
        assert "gate=skip avail=" in history[0] and "gate=skip avail=" in out
        assert "reset --hard aaaaaaa" in calls
        assert calls.index("compose config -q") < calls.index("reset --hard aaaaaaa")
        assert "SKIPPED-LOW-MEMORY (" in out and "rerun deploy.sh" in out
    # close-out's green test (scripts/joey_closeout.py last_green, JoeyTV pr_close_out.py): never green here
    assert not re.match(r"^\S+ (PASS|NOTHING-TO-DEPLOY) ", history[0])
    # the line stays parseable: new= and dur= are still found (scripts/joey_closeout.py, scripts/budgets.py)
    assert re.search(r"\bnew=[0-9a-f]{7,40}\b", history[0]) and re.search(r"\bdur=\d+s\b", history[0])


def _fake_log(tmp_path, name):
    path = tmp_path / "fake" / name
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
@pytest.mark.parametrize("fails", [0, 1, 2])
def test_pull_that_recovers_within_three_tries_goes_on_to_the_gate(tmp_path, fails):
    """JY-206: a pull that fails once or twice (DNS loss) is retried 20 s apart and the deploy carries on."""
    r, calls, history = _run_deploy(tmp_path, 2000, 0, pull_fails=fails)
    out = r.stdout + r.stderr
    assert calls.count("pull --ff-only") == fails + 1, calls
    assert _fake_log(tmp_path, "sleep.log") == ["20"] * fails
    assert f"pull attempt {fails + 1}/3" in out
    for n in range(1, fails + 1):
        assert f"pull failed (attempt {n}/3) — retrying in 20 s" in out
    assert "compose config -q" in calls  # went past the pull
    assert " GATE-FAIL " in history[0]  # the fake suite is red: the run stops there, as the other fake runs do


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_pull_that_fails_three_times_aborts_as_before(tmp_path):
    """JY-206: three tries, 20 s apart (two waits, none after the last try), then fail: exit 1, ABORTED line, no gate."""
    r, calls, history = _run_deploy(tmp_path, 2000, 0, pull_fails=3)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert calls.count("pull --ff-only") == 3
    assert _fake_log(tmp_path, "sleep.log") == ["20", "20"]
    assert "pull failed (attempt 1/3) — retrying in 20 s" in out and "pull failed (attempt 2/3) — retrying in 20 s" in out
    assert "pull failed (attempt 3/3) — aborting" in out
    assert "compose config -q" not in calls and "life-test" not in calls
    assert len(history) == 1 and " ABORTED " in history[0], history


# ---- JY-256 (2026-10-27): stop the arr set for the gate. B.: "Deploy gate: stop sonarr, radarr, prowlarr and
# flaresolverr for the gate and start them again after (option A + H). Go." Measured 2026-10-27: about 504 MB freed. ----

FOUR = ("sonarr", "radarr", "prowlarr", "flaresolverr")
STOPPED_ALL = "stopped=sonarr,radarr,prowlarr,flaresolverr"


def _list_file(tmp_path):
    return tmp_path / "repo" / "deploy" / "logs" / "gate-stopped.list"


def _at(lines, needle):
    """Index of the first fake-docker call that starts with `needle`."""
    return next(i for i, ln in enumerate(lines) if ln.startswith(needle))


def _running(tmp_path):
    return (tmp_path / "fake" / "running").read_text(encoding="utf-8").split()


def test_gate_stop_set_is_a_dated_variable_at_the_top_and_never_names_the_core_media():
    top = SCRIPT[:SCRIPT.index('if [ -z "${JOEY_DEPLOY_DETACHED:-}" ]; then')]
    line = "GATE_STOP_SET=${GATE_STOP_SET-sonarr radarr prowlarr flaresolverr}"
    assert line + chr(10) in top  # `-`, not `:-`: an empty GATE_STOP_SET in the environment turns it off
    assert "GATE_STOP_FILE=$DEPLOY_DIR/logs/gate-stopped.list" + chr(10) in top  # not /tmp: survives the 22:00 power-off
    assert "JY-256, 2026-10-27" in top
    for core in ("qbittorrent", "jellyfin", "jellyseerr", "gluetun"):
        assert core not in line
    assert not re.search(r"^[^#]*docker pause", SCRIPT, re.M)  # a paused process keeps its memory


def test_stop_sits_before_the_memory_check_and_start_right_after_the_gate():
    stop = SCRIPT.index("gate_stop" + chr(10) + 'echo "== memory check (JY-240) =="' + chr(10) + "mem_check" + chr(10))
    gate = SCRIPT.index('gate || gate_fail "test build or suite red"' + chr(10) + 'gate_start "after the gate"' + chr(10))
    assert SCRIPT.index("NEW_SHA=$(GIT rev-parse --short HEAD)") < stop < gate < SCRIPT.index("== build + converge ==")
    assert SCRIPT.count("gate_stop" + chr(10)) == 1  # the gate path only, never NOTHING-TO-DEPLOY
    # gate_fail and gate_skip start the set before their history line; the EXIT trap is the net, never cut short
    for fn in ("gate_fail", "gate_skip"):
        body = _body(fn)
        assert body.index("gate_start ") < body.index("log_history")
    exit_body = _body("on_exit")
    assert "trap '' INT TERM" in exit_body
    assert exit_body.index("gate_start ") < exit_body.index('log_history "ABORTED"') < exit_body.index('rmdir "$LOCK"')
    assert 'if [ "$GATE_STOP_DONE" -eq 1 ]; then return 0; fi' in _body("gate_start")  # once per run
    # a list left by a crashed run is started right after the lock is taken (stale-lock path included), before the pull
    recover = SCRIPT.index('start_listed "left by an earlier run"')
    assert SCRIPT.index("trap 'exit 143' TERM") < recover < SCRIPT.index("== pull (ff-only) ==")
    # each name is listed before its stop; only running containers are stopped
    stop_body = _body("gate_stop")
    assert stop_body.index('>> "$GATE_STOP_FILE"') < stop_body.index('docker stop "$c"')
    assert "{{.State.Running}}" in stop_body
    assert "${GATE_STOP_TAG:+ $GATE_STOP_TAG}" in _body("log_history")


def test_gate_stop_set_is_busybox_safe():
    for fn in ("gate_stop", "start_listed", "gate_start"):
        body = _body(fn)
        for bashism in ("local ", "[[", "=(", "{1..", "&>", "<<<", "${!", "declare"):
            assert bashism not in body, (fn, bashism)


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_stop_then_re_measure_then_gate_then_start_before_the_build(tmp_path):
    """1,380 MB would skip; the fake frees 130 MB per stop, so the re-measure sees 1,900 MB and the gate runs -n 2."""
    r, calls, history = _run_deploy(tmp_path, 1380, 0, running=FOUR, free_per_stop=130, suite_ok=True)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    lines = calls.splitlines()
    suite = _at(lines, "run --rm --network none")
    for c in FOUR:
        assert _at(lines, "inspect -f {{.State.Running}} " + c) < _at(lines, "stop " + c) < suite
        assert suite < _at(lines, "start " + c) < _at(lines, "compose build")
        assert lines.count("stop " + c) == 1 and lines.count("start " + c) == 1
    assert "pytest -q -n 2 " in calls
    assert "memory before the stop set: available 1380 MB" in out
    assert out.index("gate stop set: stopped flaresolverr in ") < out.index("memory check: gate=-n2 avail=1900")
    assert out.index("memory check: gate=-n2 avail=1900") < out.index("gate stop set: started sonarr in ")
    assert "(after the gate)" in out
    assert len(history) == 1 and re.match(r"^\S+ PASS ", history[0]), history
    assert ("gate=-n2 avail=1900 " + STOPPED_ALL + " end=") in history[0]
    assert not _list_file(tmp_path).exists()
    assert sorted(_running(tmp_path)) == sorted(FOUR)


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
@pytest.mark.parametrize("path", ["gate-fail", "skip", "error", "signal"])
def test_restart_on_every_exit_path(tmp_path, path):
    """The error is an injected `false` right after the memory check (set -e aborts); the signal is a TERM the fake
    suite sends to deploy.sh."""
    kw = {"gate-fail": {}, "skip": {}, "signal": {"suite_signal": True},
          "error": {"inject": ("mem_check" + chr(10), "mem_check" + chr(10) + "false" + chr(10))}}[path]
    avail = 1300 if path == "skip" else 2000
    r, calls, history = _run_deploy(tmp_path, avail, 0, running=FOUR, **kw)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    lines = calls.splitlines()
    last_stop = max(_at(lines, "stop " + c) for c in FOUR)
    for c in FOUR:
        assert lines.count("stop " + c) == 1 and lines.count("start " + c) == 1, calls  # once per run
        assert last_stop < _at(lines, "start " + c)
    word = {"gate-fail": "GATE-FAIL", "skip": "SKIPPED-LOW-MEMORY", "error": "ABORTED", "signal": "ABORTED"}[path]
    assert len(history) == 1 and f" {word} " in history[0], history
    assert STOPPED_ALL + " end=" in history[0]
    if path in ("gate-fail", "signal"):
        assert _at(lines, "run --rm --network none") < min(_at(lines, "start " + c) for c in FOUR)
    else:
        assert "life-test" not in calls
    if path == "signal":
        assert r.returncode == 143 and "exit 143 before an outcome" in history[0], out
    assert "compose build" not in calls and "up -d" not in calls  # the live Joey stack is never touched
    assert not _list_file(tmp_path).exists()
    assert sorted(_running(tmp_path)) == sorted(FOUR)


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_a_rollback_comes_after_the_start_and_starts_nothing_twice(tmp_path):
    """Green suite, then `compose build` fails: the set was started after the suite, so the rollback (and the EXIT trap
    after it) finds nothing left to start."""
    r, calls, history = _run_deploy(tmp_path, 2000, 0, running=FOUR, suite_ok=True, build_fails=True)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    lines = calls.splitlines()
    for c in FOUR:
        assert lines.count("stop " + c) == 1 and lines.count("start " + c) == 1, calls
        assert _at(lines, "run --rm --network none") < _at(lines, "start " + c) < _at(lines, "compose build")
    assert len(history) == 1 and " ROLLBACK-FAILED " in history[0] and STOPPED_ALL + " end=" in history[0], history
    assert not _list_file(tmp_path).exists()
    assert sorted(_running(tmp_path)) == sorted(FOUR)


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_a_container_that_was_already_stopped_is_left_alone(tmp_path):
    r, calls, history = _run_deploy(tmp_path, 2000, 0, running=("sonarr", "prowlarr"))
    out = r.stdout + r.stderr
    lines = calls.splitlines()
    for c in FOUR:
        assert "inspect -f {{.State.Running}} " + c in lines
    for c in ("radarr", "flaresolverr"):
        assert "stop " + c not in lines and "start " + c not in lines
        assert f"gate stop set: {c} is not running, left alone" in out
    for c in ("sonarr", "prowlarr"):
        assert lines.count("stop " + c) == 1 and lines.count("start " + c) == 1
    assert " GATE-FAIL " in history[0] and "stopped=sonarr,prowlarr end=" in history[0]
    assert _running(tmp_path) == ["sonarr", "prowlarr"]


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_nothing_running_logs_stopped_none(tmp_path):
    r, calls, history = _run_deploy(tmp_path, 2000, 0)
    assert not [ln for ln in calls.splitlines() if ln.startswith(("stop ", "start "))]
    assert " GATE-FAIL " in history[0] and "stopped=none end=" in history[0]
    assert not _list_file(tmp_path).exists()


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
@pytest.mark.parametrize("stale_lock", [False, True])
def test_a_list_left_by_a_crashed_run_is_restarted_first(tmp_path, stale_lock):
    """A run killed while the set was down (or the NAS powered off) leaves the list; the next run, stale lock or not,
    starts those containers right after it takes the lock, before the pull. The stop set is off here, so the only
    starts are the recovery's."""
    r, calls, history = _run_deploy(tmp_path, 2000, 0, stop_set="", leftover="radarr" + chr(10) + "sonarr" + chr(10),
                                    stale_lock=stale_lock)
    out = r.stdout + r.stderr
    lines = calls.splitlines()
    for c in ("radarr", "sonarr"):
        assert lines.count("start " + c) == 1 and _at(lines, "start " + c) < _at(lines, "run --rm")  # before any git
        assert f"gate stop set: started {c} in " in out
    assert "(left by an earlier run)" in out
    if stale_lock:
        assert "stale deploy lock" in out
    assert not _list_file(tmp_path).exists()
    assert len(history) == 1 and " GATE-FAIL " in history[0] and "stopped=" not in history[0]


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_a_container_that_will_not_start_stays_listed_and_is_logged(tmp_path):
    r, calls, history = _run_deploy(tmp_path, 2000, 0, running=FOUR, start_fails=("radarr",))
    out = r.stdout + r.stderr
    lines = calls.splitlines()
    for c in FOUR:
        assert lines.count("start " + c) == 1  # tried once in this run; the next run retries from the list
    assert "!! gate stop set: could not start radarr (after a red gate)" in out
    assert _list_file(tmp_path).read_text(encoding="utf-8").split() == ["radarr"]
    assert STOPPED_ALL + " start-failed=radarr end=" in history[0]


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_empty_gate_stop_set_is_a_no_op(tmp_path):
    r, calls, history = _run_deploy(tmp_path, 2000, 0, running=FOUR, stop_set="")
    lines = calls.splitlines()
    assert [ln for ln in lines if ln.startswith(("inspect -f", "stop ", "start "))] == []
    assert len(history) == 1 and " GATE-FAIL " in history[0] and "stopped=" not in history[0]
    assert "gate=-n2 avail=2000 end=" in history[0]  # the JY-240 line, unchanged
    assert not _list_file(tmp_path).exists()
    assert _running(tmp_path) == list(FOUR)


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_a_failed_stop_is_taken_off_the_list_and_the_gate_still_re_measures(tmp_path):
    """Review fix (2026-10-27): radarr's `docker stop` fails and it keeps running. The deploy re-measures and gates as
    usual, radarr is not in stopped= and not in the list, and nothing starts it (this run never stopped it)."""
    r, calls, history = _run_deploy(tmp_path, 1300, 0, running=FOUR, free_per_stop=130, suite_ok=True,
                                    stop_fails=("radarr",))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    lines = calls.splitlines()
    assert "!! gate stop set: could not stop radarr — it keeps running, taken off the list !!" in out
    assert "memory check: gate=-n1 avail=1690" in out  # re-measured: 1,300 + 3 x 130
    assert "start radarr" not in lines
    for c in ("sonarr", "prowlarr", "flaresolverr"):
        assert lines.count("start " + c) == 1
    assert "stopped=sonarr,prowlarr,flaresolverr end=" in history[0] and re.match(r"^\S+ PASS ", history[0])
    assert not _list_file(tmp_path).exists()
    assert sorted(_running(tmp_path)) == sorted(FOUR)


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_a_failed_recovery_start_is_tagged_and_the_deploy_carries_on(tmp_path):
    """Review fix (2026-10-27): a leftover radarr will not start. The recovery logs it and tags recovery-failed=radarr;
    the deploy carries on (stop set, gate); the gate's start tries radarr once more. Both tags stay on the line."""
    r, calls, history = _run_deploy(tmp_path, 2000, 0, running=("sonarr",), start_fails=("radarr",),
                                    leftover="radarr" + chr(10))
    out = r.stdout + r.stderr
    lines = calls.splitlines()
    assert "!! gate stop set: could not start radarr (left by an earlier run)" in out
    assert _at(lines, "start radarr") < _at(lines, "run --rm")  # the recovery, before the pull
    assert "life-test python" in calls  # carried on to the gate
    assert lines.count("start radarr") == 2 and lines.count("start sonarr") == 1
    assert len(history) == 1 and " GATE-FAIL " in history[0]
    assert "recovery-failed=radarr stopped=sonarr start-failed=radarr end=" in history[0], history
    assert _list_file(tmp_path).read_text(encoding="utf-8").split() == ["radarr"]


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
def test_the_poster_store_folder_is_made_and_handed_to_uid_1000_before_the_build(tmp_path):
    """JY-260 phase 2: posters_dir() before `compose build`, on the harness path (never the real /volume1)."""
    r, calls, history = _run_deploy(tmp_path, 2000, 0, suite_ok=True)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    store = tmp_path / "posters" / "out"
    assert store.is_dir() and _fake_log(tmp_path, "chown.log") == ["1000:1000 " + store.as_posix()]
    assert re.match(r"^\S+ PASS ", history[0]), history
    assert "POSTERS_OUT_DIR=${JOEY_POSTERS_DIR:-/volume1/Docker/joey/posters/out}" in SCRIPT


@pytest.mark.skipif(SH is None, reason="no POSIX sh with pipefail on this host")
@pytest.mark.parametrize("fail", ["mkdir", "chown"])
def test_a_poster_store_folder_that_cannot_be_made_rolls_back_cleanly(tmp_path, fail):
    r, calls, history = _run_deploy(tmp_path, 2000, 0, running=FOUR, suite_ok=True, posters_fail=fail)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "poster store dir" in out
    assert len(history) == 1 and " ROLLED-BACK " in history[0] and "poster store dir" in history[0], history
    lines = calls.splitlines()
    assert lines.count("compose build") == 1 and lines.count("compose up -d --remove-orphans") == 1   # rollback's only
    assert not _list_file(tmp_path).exists() and sorted(_running(tmp_path)) == sorted(FOUR)
