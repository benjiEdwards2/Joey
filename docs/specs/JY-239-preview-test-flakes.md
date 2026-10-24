# JY-239 Preview lock tests: Linux CI flakes

Status: building
Size: S
Live risk: NAS write (the preview lock scripts only: `SH_ALIVE` in `scripts/joey_preview.py` changes; reviewed as L)
Area: `scripts/joey_preview.py` (`SH_ALIVE`), `tests/scripts/test_joey_preview.py`
Needs: JY-228 (shipped)
Options page: none: no screen

Source: the orchestrator, 2026-10-24. JY-228's real-sh lock tests turned unrelated PRs red on Linux CI (`-n auto`), three runs seen that day.

## Problem
Two JY-228 tests fail on Linux CI under load:
1. `test_real_holder_gives_the_lock_up_by_itself`: `assert (not False and not True)`. The lock was gone but the holder still answered `kill -0`. The holder removes the lock in its EXIT trap and exits a moment later; the test polled only for the lock, then checked the holder once.
2. `test_real_zombie_holder_counts_as_dead`: `FileNotFoundError: /proc/<pid>/stat`. The test made its zombie in sh (`( sleep 0 & ...; exec sleep 5 )`); the zombie could be reaped (by the shell before its exec, or once the 5 s parent ended under load) while the test read its stat file from Python.
The same race exists in the shell: `SH_ALIVE` treated a pid whose stat file vanished between `kill -0` and the read as alive (the state read was empty, and empty is not `Z`).

## Acceptance criteria
1. `SH_ALIVE`: a pid whose `/proc/<pid>/stat` is missing while `/proc` is mounted (`/proc/self/stat` readable) is dead; with no `/proc` at all, `kill -0` decides. BusyBox ash and dash compatible. Tested with a fake `/proc` (runs anywhere with `sh`).
2. The self-expiry test polls for both "lock gone" and "holder gone" with a generous deadline (60 s) and keeps its assertion; no fixed wait.
3. The Linux zombie test makes its zombie as its own `subprocess.Popen` child, never waited for until the end, so nothing can reap it mid-test; it reads the state through a helper where a missing stat file is `""`, not an error. Its assertions are unchanged (`kill -0` passes, `alive` says dead, release removes the lock).
4. Proof: `tests/scripts/test_joey_preview.py` run 30 times with `-n 4` and a CPU hog on every core: 0 failures. Output in the PR.
5. No test is weakened, skipped or deleted.

## Data
None.

## Performance budget
None apply (tests only; the lock scripts' timing is unchanged).

## Options and the pick
None: no screen.

## Out of scope
Other flaky tests. The gate's `--init`.

## Accept checklist
- CI green on Linux (the zombie test runs there); the 30-run output in the PR.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
