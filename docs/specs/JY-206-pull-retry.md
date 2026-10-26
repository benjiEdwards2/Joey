# JY-206 deploy.sh pull retry (E0, code part)

Status: review
Size: S
Live risk: deploy (changes `deploy/deploy.sh`, the only path to production)
Area: `deploy/deploy.sh` (the pull step), `tests/deploy/test_deploy_script.py`, `deploy/README.md` (one line), this spec
Needs: none
Options page: none: no screen

HITLIST row JY-206: "ADM IPv6 DNS entry + deploy.sh pull retry (E0)". This spec is the code half only.

## Problem
The NAS loses container DNS now and then under load ("Could not resolve hostname github.com"). `deploy.sh` already retried the pull 3 times, 5 s apart (2026-10-13). 5 s is too short for the resolver to recover, so a deploy can still abort on the pull. The retry should wait longer between tries and say what it is doing.

## Acceptance criteria
1. The pull (`GIT pull --ff-only`, the alpine/git container with the `joey_deploy` key) is tried at most 3 times, 20 s apart. `PULL_TRIES=3` and `PULL_WAIT=20` are variables in the script.
2. Each try prints `pull attempt N/3`. Each failure that has a retry left prints `pull failed (attempt N/3) — retrying in 20 s`, then sleeps 20 s. The third failure prints `pull failed (attempt 3/3) — aborting` to stderr and exits 1 as before (ABORTED line in `history.log` via the EXIT trap). There is no sleep after the last try.
3. A pull that works on try 1, 2 or 3 carries on to the gate unchanged.
4. BusyBox sh only: a `while :` loop with `$(( ))` arithmetic, no `for ((`, brace ranges, `[[ ]]`, `local` or arrays.
5. Tests, written red first: string pins (variables, log lines, no bashisms, no sleep after the last try) and behaviour tests that run the real script under a local POSIX sh with a fake `docker` (fails the pull 0, 1, 2 and 3 times) and a fake `sleep` (records the seconds, returns at once). The old pin for "retrying in 5 s" changes to the new wording (2026-10-26, this item).

## Data
None.

## Performance budget
Full gate ≤ 10 min: unchanged. A pull that fails twice now costs 40 s of waiting instead of 10 s, only when DNS is down.

## Options and the pick
None: no screen. The brief for this item fixed 3 tries, 20 s apart.

## Out of scope
- **The ADM IPv6 DNS entry is B.'s hands** (a setting in the Synology ADM control panel). This item does not touch it and cannot test it. It stays on the HITLIST row for B.
- The container's own resolver retries (`--dns-opt attempts:3 --dns-opt timeout:2`) are unchanged.
- The `tv_publish` docker run and other network steps: no retry added.

## Accept checklist
- `deploy.sh` diff: the pull block only (plus its header comment).
- `python -m pytest -q tests/deploy/` output in the PR.
- After merge: `deploy.sh` runs the copy it read before its own pull, so the change takes effect from the **second** deploy after the merge. That deploy's log shows `pull attempt 1/3`.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
