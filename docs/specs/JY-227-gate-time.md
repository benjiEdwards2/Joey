# JY-227 Full deploy gate within 10 minutes

Status: building
Size: M
Live risk: deploy (the gate itself)
Area: `tests/` (fixtures and slow tests), `deploy/deploy.sh` (pytest worker count only, if B. agrees), `tests/README.md`
Needs: none
Options page: none: no screen

Source: `scripts/budgets.py` (JY-013), 2026-10-23: "Full gate (deploy.sh) 15.3 min, budget 10 min".

## Problem
The full gate takes 15.0–15.3 min (history.log dur 899–919 s) against a 10-minute budget. Research, 2026-10-24 (read-only, last three deploy logs):

| Run | dur | pytest | everything else | tests |
|---|---|---|---|---|
| 10-23 10:07 | 919 s | 13.4 min (88 %) | 1.9 min | 3,410 |
| 10-23 05:46 | 907 s | 13.5 min (89 %) | 1.6 min | 3,410 |
| 10-21 00:12 | 839 s | 12.0 min (86 %) | 2.0 min | 2,679 |

The suite (`pytest -n 2` on a 4-core Celeron J4125) is the cost. Profile, 2026-10-24 (laptop, `-n 4 --durations`, main 3a7270b: 3,439 tests, 261 s wall, 854 s summed):

| Directory | summed s | share | tests |
|---|---|---|---|
| `tests/scripts/` | 493 | 58 % | 127 |
| `tests/hub/` | 329 | 38 % | 1,808 |
| connectors, deploy, others | ~32 | 4 % | ~1,500 |

The top 15 slowest tests are all in `tests/scripts/` (10–13 s each): `test_joey_closeout.py` (319 s; its `w` fixture builds a full git world per test, ~45 git calls) and `test_joey_worktree.py` (165 s; a bare origin + clone + `joey.py` subprocesses per test). Hub app builds are cheap (median setup 0.01 s, call 0.11 s). Collection costs ~18 s per xdist worker. Raw listing: `scratchpad/jy227_durations.txt` (orchestrator session).

The fix is mostly in the tooling tests (JY-010/011/012's own), not in the hub tests.

## Acceptance criteria
1. A `--durations=60` profile of the full suite (laptop, then one quiet-NAS gate run) is recorded in this spec with the top hot spots.
2. The biggest hot spots are fixed without weakening or skipping any test (rule 4): build each tooling test's template git repo once per module/session and copy it per test (`shutil.copytree` or `git clone --local`); refusal-path tests use the light world with no git; the fake squash-merge works in-process (`git merge-tree`/`commit-tree`) instead of a scratch clone. This absorbs JY-229 criterion 3 (JY-229 keeps only its dry-run fix).
3. If, after 2, the gate is still over 10 min: `-n 3` is tried with `free -m` sampled during the run; it stays only if available memory stays ≥ 1,200 MB and swap ≤ 1,273 MB throughout.
4. Gate ≤ 10 min (dur ≤ 600 s) on 3 consecutive PASS deploys on a quiet NAS (qBittorrent capped); numbers in the PR.
5. The full suite still runs before every deploy (rule 13).

## Data
None.

## Performance budget
Full gate ≤ 10 min; NAS available memory ≥ 1,200 MB during the gate.

## Options and the pick
None: no screen.

## Out of scope
CI speed; NAS hardware; moving tests out of the gate (unless B. answers question 2 "yes").

## Accept checklist
- CI green; reviews posted; three deploy history lines with dur ≤ 600 s and the memory samples in the PR.

## Questions for B.
Answers: B., orchestrator session, 2026-10-24: "Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance." = every recommended answer below, and ready.
1. Order of work? **a (recommended):** profile first and fix the hot spots, then try `-n 3` only if still over 10 min. **b:** try `-n 3` first.
2. The tooling tests (`tests/scripts/`) test laptop-only scripts that never run on the NAS, yet cost 58 % of the suite. **a (recommended):** keep them in the gate and make them fast first (criterion 2); revisit only if the gate is still over 10 min. **b:** run them in CI only, not in the NAS gate (gate drops roughly 4–7 min at once; bends rule 13's "full suite").
3. May one deploy run with `--durations` on a quiet NAS to profile the real gate? **a (recommended):** yes, with qBittorrent capped. **b:** no, profile on the laptop only.

Reply in one message, e.g. "JY-227: 1a 2a 3a, ready".

## Shipped notes
(filled at close-out)
