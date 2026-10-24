# JY-227 Full deploy gate within 10 minutes

Status: shipped 2026-10-24
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

### Split (orchestrator, 2026-10-24)
Criteria 1 (laptop profile, recorded above) and 2 (hot spots fixed without weakening tests) ship in this PR. Criteria 3–5 can only be proven on the NAS after this merges (deploy.sh runs from main): they move to **JY-235** ("Gate ≤ 10 min: measure after JY-227, `-n 3` trial only if still over, three deploys ≤ 600 s"), with the quiet-NAS `--durations` profile (B.'s answer 3a) as its first step. Recorded here per rule 4's spirit: no criterion is dropped, only moved.

## Data
None.

## Performance budget
Full gate ≤ 10 min; NAS available memory ≥ 1,200 MB during the gate.

## Options and the pick
None: no screen.

## Out of scope
CI speed; NAS hardware; moving tests out of the gate (unless B. answers question 2 "yes").

## Accept checklist
- CI green; reviews posted; laptop before/after numbers in the spec. (The three deploy history lines with dur ≤ 600 s and the memory samples are JY-235's accept check after the split.)

## Questions for B.
Answers: B., orchestrator session, 2026-10-24: "Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance." = every recommended answer below, and ready.
1. Order of work? **a (recommended):** profile first and fix the hot spots, then try `-n 3` only if still over 10 min. **b:** try `-n 3` first.
2. The tooling tests (`tests/scripts/`) test laptop-only scripts that never run on the NAS, yet cost 58 % of the suite. **a (recommended):** keep them in the gate and make them fast first (criterion 2); revisit only if the gate is still over 10 min. **b:** run them in CI only, not in the NAS gate (gate drops roughly 4–7 min at once; bends rule 13's "full suite").
3. May one deploy run with `--durations` on a quiet NAS to profile the real gate? **a (recommended):** yes, with qBittorrent capped. **b:** no, profile on the laptop only.

Reply in one message, e.g. "JY-227: 1a 2a 3a, ready".

## Build notes
2026-10-24, criterion 2 (builder). Test setup changed, no test removed, skipped or weakened, every assertion kept (rule 4):
- `test_joey_closeout.py`: the full world `w` copies a per-session template (`Templates`: base origin + clone, plus one variant per `files` tuple holding the item's worktree and pushed commit) with `shutil.copytree`, then rewrites the copy's absolute paths (`url.<origin>.insteadOf`, the worktree's `.git` and `gitdir` files). A test that changes main before `item()` gets the base copy and builds the item commit itself, as before. `FakeGh` squash-merges in the bare origin with `merge-tree --write-tree` + `commit-tree` + `update-ref` instead of a scratch clone + `merge --squash` + push. Refusal and gate tests were already on the light world.
- `test_joey_worktree.py`: `Repo` copies a per-session origin + clone (one per origin URL). Setup-only `worktree new` in `Repo.item()` runs `joey_worktree.main` in-process; every test of `new`, `remove` and `list` still runs the CLI as a subprocess.
- Both: the sandbox gitconfig sets `maintenance.auto=false` and `receive.autogc=false` (git spawned a `maintenance run --auto` after every commit, fetch and push).

Laptop profile, 2026-10-24, `-n 4`, main 3b20517 vs this branch, run back to back (no other pytest running, except one other builder's run during the full "after"; Windows spawns a git process in ~130 ms, so git-heavy tests weigh far more here than on Linux):

| Run | before | after |
|---|---|---|
| `tests/scripts/` wall | 136 s | 95 s |
| `tests/scripts/` summed | 524 s (closeout 331, worktree 162) | 308 s (closeout 167, worktree 110) |
| full `tests/` wall | 289 s | 222 s |
| tests | 3,495 passed, 1 skipped | 3,495 passed, 1 skipped |

What is left in `tests/scripts/` is mostly the code under test: one `close-out` run makes ~29 git calls of its own, and the worktree tests run the CLI as a subprocess. The NAS share of `tests/scripts/` is unknown until the quiet-NAS profile run (criterion 1).

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #65, squash-merged as `432005e` (432005e389e2376736fbc0fcbd64f5c2971d4a97).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
