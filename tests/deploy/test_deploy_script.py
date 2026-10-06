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
    gate = SCRIPT.index("docker run --rm life-test")
    converge = SCRIPT.index("up -d")
    assert gate < converge, "suite must gate BEFORE containers converge"
    assert "GATE-FAIL" in SCRIPT  # a red suite is logged and aborts


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
    The lock is an atomic mkdir (BusyBox-safe), taken before the pull, released by an EXIT trap,
    and a second runner exits non-zero with a word instead of touching the stack."""
    lock = SCRIPT.index('mkdir "$LOCK"')
    assert lock < SCRIPT.index("== pull (ff-only) ==")
    assert "trap 'rmdir \"$LOCK\" 2>/dev/null' EXIT" in SCRIPT
    assert "another deploy is running" in SCRIPT and "exit 2" in SCRIPT
    assert "flock" not in SCRIPT  # not guaranteed on the NAS BusyBox
