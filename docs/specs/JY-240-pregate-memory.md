# JY-240 Pre-gate free-memory check in deploy.sh

Status: building
Size: S
Live risk: deploy (changes `deploy/deploy.sh`, the only path to production)
Area: `deploy/deploy.sh` (one check before the gate), `tests/deploy/test_deploy_script.py`, `tests/scripts/test_joey_closeout.py` (pins only, no close-out code change), `deploy/README.md`, `docs/reference/tech-notes.md`, this spec
Needs: JY-235 (tmpfs gate; shipped 2026-10-24)
Options page: none: no screen

From the JY-235 review (should-fix, 2026-10-24).

## Problem
The gate drops NAS available memory by ~400–520 MB with `-n 2` (JY-235: start 1,791 MB, minimum 1,271–1,381 MB across the proof runs). Started on an already busy NAS, it can push available memory under the 1,200 MB floor in `CLAUDE.md` (and swap over 1,273 MB). deploy.sh should look before it starts the gate, and not run it when there is no headroom.

## Measurements
| Gate | NAS available drop | Duration | Source |
|---|---|---|---|
| `-n 2` | 410–520 MB (about 400–450 MB in the JY-235 proof runs) | 192–299 s | JY-235, 2026-10-24 |
| `-n 1` | 243 MB | 342 s | measured 2026-10-24 |

`-n 1` is slower but far inside the 10 min gate budget, and it holds the floor from a lower start: 1,460 − 243 = 1,217 MB; 1,720 − 520 = 1,200 MB.

## Acceptance criteria
1. Before the gate (`docker build` of `life-test` + the suite), deploy.sh reads MemAvailable and swap used (SwapTotal − SwapFree) from `/proc/meminfo` with BusyBox `awk` (`free` column layout differs between BusyBox builds).
2. Thresholds are variables at the top of the script with a dated comment: `GATE_FULL_AVAIL_MB=1720`, `GATE_MIN_AVAIL_MB=1460` and `GATE_MAX_SWAP_MB=1273`.
3. By available memory just before the gate: ≥ 1,720 MB runs the gate with `-n 2`; 1,460–1,719 MB runs it with `-n 1`; < 1,460 MB skips the deploy.
4. A skip (available < 1,460 MB, swap used > 1,273 MB, or MemAvailable cannot be read: fail closed) does not run the gate: one clear line (`SKIPPED-LOW-MEMORY (<reason>; gate=skip avail=<MB>) — gate not run, tree back on <prev> ...`), one history line `SKIPPED-LOW-MEMORY`, the tree reset to the previous SHA (as `gate_fail`), the live stack untouched, exit 1.
5. Exactly on the thresholds the higher mode runs: 1,720 MB runs `-n 2`, 1,460 MB runs `-n 1`, 1,273 MB swap runs the gate; 1,719 MB runs `-n 1`, 1,459 MB skips.
6. The chosen mode and the available MB are printed (`memory check: gate=-n1 avail=1588`) and written to history.log as `gate=-n1 avail=1588` (`gate=-n2 ...`, `gate=skip avail=...`; `avail=?` when unreadable). On `PASS` and `GATE-FAIL` the tag is appended after the existing text (`suite green, smoke ok tv=<tv> gate=-n1 avail=1588`), so every reader still parses: `scripts/joey_closeout.py` and JoeyTV's `pr_close_out.py` match ` PASS ` / `NOTHING-TO-DEPLOY` and `new=`; `scripts/budgets.py` matches `PASS ` and `dur=`; `scripts/joey.py` does not read history.log. `NOTHING-TO-DEPLOY` lines are unchanged.
7. `SKIPPED-LOW-MEMORY` is not green for close-out: `scripts/joey_closeout.py` (`last_green`: PASS / NOTHING-TO-DEPLOY only) and JoeyTV's `pr_close_out.py` (same regex) refuse the next deploy until `--after-fail` or a later green run. No close-out code change; pinned by tests.
8. BusyBox sh only (no bashisms, no awk `strftime`); the NOTHING-TO-DEPLOY path is unchanged (no gate, no check).
9. Tests: string pins (check before the gate, after the pull; gate_skip resets before logging; variables at the top; `-n $GATE_N`; the tag format) and a behaviour test that runs deploy.sh under a local POSIX sh with a fake `docker` on PATH and a fake meminfo, below / on / above each threshold (1,459, 1,460, 1,588, 1,719, 1,720 MB; swap 1,273 / 1,274), plus an unreadable file. The middle-band cases fail on the first JY-240 commit (ad3a56b, which skipped below 1,650 MB and always ran `-n 2`). The existing `-n 2` pin in `test_gate_runs_the_full_suite_in_parallel_with_a_pinned_xdist` changes to `-n $GATE_N` (2026-10-24, this item).

## Data
None. `deploy/history.log` gains one outcome word.

## Performance budget
NAS available memory ≥ 1,200 MB and swap ≤ 1,273 MB during the gate: this item is the guard. Full gate ≤ 10 min: `-n 1` takes about 342 s (measured 2026-10-24), `-n 2` 192–299 s; plus one `awk` read.

## Options and the pick
None: no screen. The first build (ad3a56b) skipped below a single 1,650 MB threshold (1,650 − 450 = 1,200 MB). The HITLIST row's "~1,400 MB" predates the JY-235 numbers.

B.'s pick, in chat on 2026-10-24: "JY-240: adapt"

Adapt means, by NAS `free -m` available memory just before the gate: ≥ 1,720 MB gate as today (`-n 2`); 1,460–1,719 MB gate with `-n 1`; < 1,460 MB skip the deploy. The measurements above back the bands.

## Out of scope
Monitoring memory during the gate; freeing memory automatically; the preview's own 1,400 MB check (JY-012).

## Accept checklist
- `deploy.sh` diff: check before `gate`, variables at the top.
- `python -m pytest -q tests/deploy/` output in the PR.
- After merge: the first deploy still runs the old copy (deploy.sh runs the script it read before its pull); from the next deploy on, the log shows `== memory check (JY-240) ==` and a `memory: available ... swap used ...` line.

## Questions for B.
None.

## Shipped notes
