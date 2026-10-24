# JY-224 Flaky test: test_metadata_long_request_state_short

Status: building
Size: S
Live risk: none
Area: `tests/hub/test_media_speed.py`
Needs: none
Options page: none: test-only fix, no screen

## Problem
`tests/hub/test_media_speed.py::test_metadata_long_request_state_short` failed about 3 runs in 8 when the machine was busy. It visits the film page, moves the frozen clock 11 minutes, and visits again. It never waited for the first visit's background Seerr read, so that read was still in flight when the clock moved.

## Cause (proven 2026-10-24)
The first `client.get` starts the title's background read (`media_film.warm_extras`) and returns without waiting. Under load that read is still running when the test advances `clock`, so the second visit joins the running job (or the job writes its cache entries after the jump). The title body is then fetched once, not twice: `assert 1 == 2` on `/api/v1/movie/603`. Fast machines finish the read before the clock moves, so it passed.

Measured before the fix (2026-10-24, 32 busy-loop processes on 16 cores, the old test):
- 10 separate pytest runs of the test alone: 4 failed, 6 passed. Every failure was `assert 1 == 2` on the title body count.
- One process, the test repeated 20 times: 19 failed, 1 passed (the same assertion; the first repeat passes, later ones start while the previous read is still draining).
- Same test, no extra load, 10 separate runs: 0 failed.

Measured after the fix, same load, one process, 20 repeats: 20 passed. The file alone, no load: all pass.

## Acceptance criteria
1. The test calls `media_film.drain_extras()` after the first visit, before the clock moves.
2. No assertion changes. The TTL pins (title body 2, shelves 2, ratings 1 then 2) stay as they were.
3. 20 of 20 passes under the same load as the "before" measurement. Met (see Cause).

## Data
None.

## Performance budget
None apply (test only).

## Out of scope
Any change in `hub/`. The TTL behaviour is right; only the test's timing was wrong.

## Accept checklist
CI green; the before/after rates in the PR.

## Shipped notes
PR and the after-fix rate are in the PR description.
