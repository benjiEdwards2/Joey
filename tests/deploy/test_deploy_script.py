"""WP9 — deploy.sh is the only path to production (rule 13).

These tests pin the load-bearing ordering of the script: the full-suite gate
runs BEFORE the live stack is touched, smoke failure triggers a rollback to
the captured PREV_SHA, and every outcome appends to history.log. smoke.py
itself is exercised for real by the deploy (and its unit shape here).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (REPO_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
SMOKE = (REPO_ROOT / "tests" / "deploy" / "smoke.py").read_text(encoding="utf-8")


def test_script_is_busybox_safe_and_strict():
    assert SCRIPT.startswith("#!/bin/sh")  # NAS has no bash (DECISIONS 2026-08-31)
    assert "set -eu" in SCRIPT
    assert "set -o pipefail" in SCRIPT
    assert "{sqlite," not in SCRIPT  # no brace expansion under BusyBox


def test_gate_runs_before_the_live_stack_is_touched():
    gate = SCRIPT.index("docker run --rm --network none life-test")
    converge = SCRIPT.index("up -d")
    assert gate < converge, "suite must gate BEFORE containers converge"
    assert "GATE-FAIL" in SCRIPT  # a red suite is logged and aborts


def test_gate_runs_offline():
    """D-09 (2026-10-09): the suite is offline-clean, so the gate container gets no network."""
    assert "docker run --rm --network none life-test" in SCRIPT
    assert "docker run --rm life-test" not in SCRIPT


def test_gate_runs_the_full_suite_in_parallel_with_a_pinned_xdist():
    """N-44 (2026-10-09): ~9 of a deploy's ~10 minutes were the suite; xdist spreads it over
    the cores. Still the FULL tests/ tree (rule 13), and xdist is pinned for the image."""
    assert "docker run --rm --network none life-test python -m pytest -q -n 2 tests/" in SCRIPT
    dev = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert "pytest-xdist==3.8.0" in dev


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
    """2026-10-13: three deploys aborted on 'Could not resolve hostname github.com' (UDP DNS loss under NAS load)."""
    assert "--dns-opt attempts:3 --dns-opt timeout:2" in SCRIPT
    assert "for attempt in 1 2 3; do" in SCRIPT
    assert "if GIT pull --ff-only; then break; fi" in SCRIPT
    assert "pull failed (attempt $attempt/3) — retrying in 5 s" in SCRIPT
