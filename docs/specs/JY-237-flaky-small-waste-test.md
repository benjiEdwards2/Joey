# JY-237 Flaky test file: test_media_small_waste.py errors under -n 4

Status: parked
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

## Acceptance criteria
1. If it recurs: capture the traceback, then fix the cause with a test that fails on the old code (rule 4). Until then none.

## Out of scope
Any change to the test file or conftest without a reproduction.

## Shipped notes
Parked, nothing shipped.
