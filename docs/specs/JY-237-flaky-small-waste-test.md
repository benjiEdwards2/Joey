# JY-237 Flaky tests (small waste, upgrade why, warm library, player sessions)

Status: in review
Size: S
Live risk: none
Area: tests/hub/test_media_small_waste.py
Needs: none
Options page: none: test-only fix

## Problem
HITLIST: `tests/hub/test_media_small_waste.py` raised 2 errors on main under `-n 4` during the JY-104 build (2026-10-24); it passes alone.

## Result: not reproduced in 30+ tries (2026-10-24)
Machine: Windows, 16 cores, main at e930710, pytest 9.1.1 + xdist 3.8.0. Every run below passed, so there is no cause to fix and no code change in this PR.
- Full `pytest tests/hub -n 4`: 5 runs (2635 passed each); full `pytest tests -n 4`: 1 run (3512 passed, 1 skipped).
- The file alone with `-n 4`, 6 runs on a quiet machine; 8 runs beside 20 busy-loop processes (all cores saturated); 24 runs while a full `-n 4` tests/hub run executed in the background; 12 more of the file looping singly beside the same load.
- Total: 50+ attempts, 0 errors, 0 failures.

Notes for whoever sees it next (hypotheses only, none proven):
- Exactly two tests use the `real_sessions` fixture (`test_one_kept_session_per_upstream`, `test_a_session_keeps_no_cookies`), the only place a setup error with a count of 2 is natural. Its `next(...)` over `sys.modules` finds the conftest copy whose `REAL_UPSTREAM` is filled; an empty result would raise `StopIteration` inside the fixture generator and show as a setup error.
- The reported run was a builder worktree on Windows: a long worktree or temp path (Filename too long on `tmp_path` dirs, as seen in `tests/scripts/test_joey_closeout.py` runs from a long scratchpad path) would also give setup errors that pass alone.
- To catch it: re-run with `-n 4 -rA` and keep the first error's traceback; the traceback decides between these two.

## Acceptance criteria (first pass, superseded below)
1. If it recurs: capture the traceback, then fix the cause with a test that fails on the old code (rule 4). Until then none.

## Out of scope (first pass)
Any change to the test file or conftest without a reproduction.

## Flaky-tests round (2026-10-28, B.: "Go with 5.")
Scope grew from the one file to the four seen flaking under `-n 2` today: `test_media_small_waste.py`, `test_media_upgrade_why.py`, `test_media_warm_library.py`, `test_player_api.py::test_a_fifth_session_drops_the_owners_oldest`. JY-243/244/249 (film-extras race) were already shipped and are not touched.

### Repro rates before the fix (main, machine shared with 3 other test runs)
- Full `tests/hub`: `-n 2` 4 runs + `-n 4` 4 runs + 6 more mixed runs in a worktree: 0 failures.
- The four files together, `-n 4`, 15 runs: 0 failures.
- `test_a_fifth_session...` alone, 20 runs: 0 failures. Its cause is deterministic once the clock is frozen (below), so it is proven by a new test that fails on the old code.
- The other three files: not reproduced; no traceback was captured, so no root cause is claimed for them.

### Root causes and fixes
1. `test_a_fifth_session_drops_the_owners_oldest` (real bug in `hub/player_api.py::_keep`). It picked the owner's oldest session with `sorted((seen, sid))`. `seen` is `time.time()`, which ticks about 16 ms on Windows, so five starts made back to back share one `seen` and the tie fell to the random session id: a random session was dropped, not the oldest. Fix: sort on `seen` alone (stable sort, insertion order breaks the tie). Regression test `test_a_fifth_session_drops_the_oldest_even_when_the_clock_has_not_ticked` freezes the clock and forces descending ids; it fails on the old code and passes now.
2. `test_media_small_waste.py` `real_sessions` fixture (StopIteration, setup error x2). The fixture hunted `sys.modules` for a conftest copy with a filled `REAL_UPSTREAM`; three `conftest.py` files share the module name `conftest` (no `__init__.py`, prepend import mode), and `tests.hub.conftest` imported by other test files is a second, empty copy, so the hunt depends on which copy is alive. An empty hunt raises StopIteration. Fix: take `upstream.session` once at import time of the test file (collection, before any fixture patches it). Hypothesis-level: not reproduced, so this removes the only StopIteration source in the file rather than a proven cause.
3. `test_media_upgrade_why.py`, `test_media_warm_library.py`: not reproduced in any run; no change. If one recurs, keep the first traceback (`-rA`); candidates are a background thread from an earlier test calling a later test's patched `requests.get` (the JY-243/244/249 pattern) and the 16 ms clock.

## Acceptance criteria
1. The fifth-session regression test fails on the old `_keep` and passes on the new.
2. The affected tests, looped 20 times, and `-n 2 tests/hub` 3 times, are all green (numbers in the PR).

## Out of scope
Any change to assertions or any skip. No change to the two files with no reproduction.

## Shipped notes
Shipped in this PR; see the PR body for the proof-run numbers.
