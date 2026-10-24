# JY-243 Flaky tests: JY-119 episode-ratings tests fail on a loaded CI runner

Status: shipped 2026-10-25
Size: S
Live risk: none
Area: tests/hub/test_episode_ratings.py
Needs: none
Options page: none: test-only fix

## Problem
After JY-119 (PR #124, `3ff5f63`) merged green, CI on the next PR (chore/JY-142-shipped, head `b6c7465`, .md files only) failed two tests in `tests/hub/test_episode_ratings.py` under `python -m pytest -q -n auto tests/`:
- `test_off_server_failing_omdb_never_fails_the_page` (line 587): `fake.ep_calls()` held `['tt9100777']` where `[]` was expected.
- `test_jellyfin_listing_the_show_with_no_seasons_draws_one_block_and_unique_season_ids`: `seen[-1]["ratings"]` was None ("the new branch fired" failed).

## Cause
A race between the test's next step and the page's background read in the `film-extras` pool (`media_film.warm_extras`), the same shape as JY-236. Not shared module state, not xdist order, not the clock, not BackgroundTask order: the autouse `_fresh_media_caches` fixture already clears every cache and drains the pool between tests, and the BackgroundTask fill runs before `client.get` returns.
1. **Off-server, failing OMDb.** The first view queues the title's extras read; its last step is the Metacritic lookup `media_omdb.metascore("tt9100777")`. The test clears `fake.calls` without waiting for that read. On a slow runner the lookup lands after the clear, so `ep_calls()` (which leaves out only the on-server show's own id) sees it. The CI log matches: the "omdb lookup failed: Timeout" line comes last.
2. **Jellyfin has the show, no seasons.** This branch (`media_film.build_film`, the `elif` on `t.get("seasons")`) needs Jellyseerr's title body cached at render time. The item page renders deferred, so the first (cold) view only queues that read. If the read has not landed by the render, the first view plans no fill. The second view then plans it and renders with nothing stored, so `ratings` is None (the product draws the block on the next view, by design).
Only the tests are wrong; the product behaviour is as specced.

## Acceptance criteria
1. Both tests wait for the in-flight read with `media_film.drain_extras()` (the JY-236 pattern): before `fake.calls.clear()` in the off-server test; after the first view in the no-seasons test, which then takes one more view so the fill can be planned and its result drawn. No assertion changes (rule 4: none weakened, so no dated line needed).
2. `test_off_server_next_view_draws_seasons_compared_from_stored_rows` gets the same drain before its `fake.calls.clear()`: same race shape (its Metacritic lookup can land after the clear), not seen failing.
3. Green with the background read slowed from 0 to 1 s, and in looped plain runs under load.

## Data
None.

## Performance budget
None.

## Out of scope
- `tests/hub/test_media_partof.py::test_following_state_inside_the_banner` failed once in three local CI-command runs (IndexError). It fails every time with the extras read slowed 0.1 s, so it looks like the same race. Proposed as its own item.

## Proof
Method: "slowed" = a throwaway pytest plugin that sleeps before `media_film._load_extras` (stands in for a loaded runner); `-k` picks the three tests named above plus `test_a_failing_omdb_never_fails_the_page` (4 tests a run).
- Before, slowed, 5 runs per delay: 0 s 1 failure (no-seasons test, unslowed); 0.005, 0.01, 0.05, 0.1, 0.3, 1.0 s 5/5 runs failed the no-seasons test; 0.02 s 5/5 runs failed both CI tests, with the CI assertion text and log lines.
- After, slowed, same 8 delays x 5 runs: 160 passed, 0 failed.
- After, plain: the whole file 30 times in a row while `pytest -n 4 tests/hub` ran beside it: 1320 passed, 0 failed (the load run: 2802 passed).
- After, the CI command `python -m pytest -q -n auto tests/`, 3 runs: 3716 passed twice; once 1 failed (the out-of-scope partof test above), 3715 passed.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #145, squash-merged as `22bbd0b` (22bbd0b7815b79e8ae59d5746764a82c632eeff1).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
