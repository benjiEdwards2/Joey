# JY-240 Pre-gate free-memory check in deploy.sh

Status: building
Size: S
Live risk: deploy (changes `deploy/deploy.sh`, the only path to production)
Area: `deploy/deploy.sh` (one check before the gate), `tests/deploy/test_deploy_script.py`, `tests/scripts/test_joey_closeout.py` (pins only, no close-out code change), `deploy/README.md`, `docs/reference/tech-notes.md`, this spec
Needs: JY-235 (tmpfs gate; shipped 2026-10-24)
Options page: none: no screen

From the JY-235 review (should-fix, 2026-10-24).

## Problem
The gate drops NAS available memory by ~400–450 MB (JY-235: start 1,791 MB, minimum 1,271–1,381 MB across the proof runs). Started on an already busy NAS, it can push available memory under the 1,200 MB floor in `CLAUDE.md` (and swap over 1,273 MB). deploy.sh should look before it starts the gate and refuse to run it when there is no headroom.

## Acceptance criteria
1. Before the gate (`docker build` of `life-test` + the suite), deploy.sh reads MemAvailable and swap used (SwapTotal − SwapFree) from `/proc/meminfo` with BusyBox `awk` (`free` column layout differs between BusyBox builds).
2. Thresholds are variables at the top of the script with a dated comment: `GATE_MIN_AVAIL_MB=1650` (1,650 − 450 = 1,200) and `GATE_MAX_SWAP_MB=1273`.
3. If available < 1,650 MB, swap used > 1,273 MB, or MemAvailable cannot be read (fail closed), the gate does not run: one clear line (`SKIPPED-LOW-MEMORY (<reason>) — gate not run, tree back on <prev> ...`), one history line `SKIPPED-LOW-MEMORY`, the tree reset to the previous SHA (as `gate_fail`), the live stack untouched, exit 1.
4. Exactly on the thresholds (1,650 MB available, 1,273 MB swap) the gate runs.
5. `SKIPPED-LOW-MEMORY` is not green for close-out: `scripts/joey_closeout.py` (`last_green`: PASS / NOTHING-TO-DEPLOY only) and JoeyTV's `pr_close_out.py` (same regex) refuse the next deploy until `--after-fail` or a later green run. No close-out code change; pinned by tests.
6. BusyBox sh only; the NOTHING-TO-DEPLOY path is unchanged (no gate, no check).
7. Tests: string pins (check before the gate, after the pull; gate_skip resets before logging; variables at the top) and a behaviour test that runs deploy.sh under a local POSIX sh with a fake `docker` on PATH and a fake meminfo, below / on / above each threshold, plus an unreadable file.

## Data
None. `deploy/history.log` gains one outcome word.

## Performance budget
NAS available memory ≥ 1,200 MB and swap ≤ 1,273 MB during the gate: this item is the guard. Full gate ≤ 10 min: unchanged (one `awk` read).

## Options and the pick
None: no screen. Threshold from the orchestrator brief (2026-10-24): 1,650 MB so the ~450 MB gate leaves ≥ 1,200 MB. The HITLIST row's "~1,400 MB" predates the JY-235 numbers.

## Out of scope
Monitoring memory during the gate; freeing memory automatically; the preview's own 1,400 MB check (JY-012).

## Accept checklist
- `deploy.sh` diff: check before `gate`, variables at the top.
- `python -m pytest -q tests/deploy/` output in the PR.
- After merge: the first deploy still runs the old copy (deploy.sh runs the script it read before its pull); from the next deploy on, the log shows `== memory check (JY-240) ==` and a `memory: available ... swap used ...` line.

## Questions for B.
None.

## Shipped notes
