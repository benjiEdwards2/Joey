# JY-225 Flaky test: test_a_two_megabyte_tail_hit_takes_under_two_ms

Status: building
Size: S
Live risk: none
Area: `tests/hub/test_runner_history_tail.py`
Needs: none
Options page: none: test-only fix, no screen

## Problem
The runner-history tail test asserted that the median of 20 cache hits on a 2 MB file took under 2 ms of wall-clock. Under load it failed about 2 runs in 8.

## Cause (proven 2026-10-24)
The limit measures how busy the machine is, not the code. With 32 busy-loop processes on 16 cores, hit medians of 57 to 390 ms were recorded for a call that does an `fstat` and a dict lookup (a quiet machine gives about 0.2 ms). The property the limit stood for is that an unchanged file costs no read and no parse.

Measured before the fix (2026-10-24, one pytest process, the test repeated 20 times, 32 CPU hogs): 7 failed, 13 passed. Every failure was the timing assertion.
Measured after the fix, same load: 20 passed. The file alone, no load: 6 passed.

## Acceptance criteria
1. The test asserts, by counting, that 20 hits on an unchanged 2 MB file call neither `store._history_lines` nor `store._parse_line`, and that each hit returns the same list object as the cold read.
2. No wall-clock assertion remains in the test.
3. The new test fails when the cache check is removed (mutation tried 2026-10-24: with the hit branch disabled it fails).
4. 20 of 20 pass under the same load as the "before" measurement. Met.

### Loosened pin (rule 4), 2026-10-24
The "under 2 ms median" pin is removed, not widened. Reason: a wall-clock bound cannot be made both tight and stable on a shared machine, and the deterministic count pins the same property (no re-read) more strictly. The 2 ms figure was recorded for a quiet machine in E1 (2026-10-13); the hub render budgets in `CLAUDE.md` are measured elsewhere.

## Data
None.

## Performance budget
None apply (test only).

## Out of scope
Any change in `hub/store.py`.

## Accept checklist
CI green; the before/after rates in the PR.

## Shipped notes
PR and the after-fix rate are in the PR description.
