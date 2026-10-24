# JY-244 Flaky tests: partof banner and media-speed tests race the page's background read

Status: shipped 2026-10-25
Size: S
Live risk: none
Area: tests/hub/test_media_partof.py, tests/hub/test_media_speed.py
Needs: none
Options page: none: test-only fix

## Problem
`tests/hub/test_media_partof.py::test_following_state_inside_the_banner` failed once under `-n auto tests/` (IndexError in `collection()`).

## Cause
Same shape as JY-236 and JY-243: the test races the film page's background read (`media_film` extras pool). The Harbour collection banner is a deferred part. The test read the bare `client.get` page, which only holds the banner if the read had landed before the render. Reproduced: a throwaway pytest plugin that sleeps before `media_film._load_extras` failed it every time at 0.1 s.
The same slowed run found four more tests in `tests/hub/test_media_speed.py` that count Seerr calls after a page view with no wait for that read: `test_tv_title_never_asks_for_ratingscombined`, `test_a_404_is_remembered_across_cache_clears_and_restarts`, `test_short_cache_remembers_a_404_too`, `test_metadata_long_request_state_short` (its last view had no drain). Only the tests were wrong.

## Acceptance criteria
1. The partof test reads the page with `whole(client, url)` (page plus its parts request, as the browser does). No assertion changed.
2. The four media-speed tests call `media_film.drain_extras()` after a view, before the next cache clear or count. No assertion changed.
3. Green with the read slowed 0 to 0.5 s, in looped runs under load, and under the CI command.

## Data
None.

## Performance budget
None.

## Out of scope
- `test_runner_history_tail` (reported failing once under `-n 2 tests/hub` on another branch, passing alone). Not reproduced here: 25 runs of the file beside `-n 2 tests/hub` and 6 CPU hogs, 0 failures. No failure text was available. Its tests do no page reads except `test_the_server_page_reuses_the_hub_cards_parsed_history` (counts `_history_lines` calls across a reloaded `hub.main`). The runner-history cache `store._HISTORY` is process-global and not reset by the conftest fixture, and the hub loop threads read it, so that test is the suspect. Needs the failing output before a fix. Proposed as its own item if it recurs.

## Proof
Method: "slowed" = a plugin that sleeps before `media_film._load_extras`.
- Before, slowed 0.1 s: partof test failed; `tests/hub` under `-n 4` had 5 failures (partof, four media-speed, plus the JY-243 test that this branch got from main).
- After, slowed 0, 0.1, 0.5 s: both files 47 passed each time. `tests/hub` slowed 0.1 s: only the JY-243 test failed (fixed on main; gone after the rebase).
- After, rebased on origin/main (81524f3): both files 30 times in a row while `-n 4 tests/hub` ran four times beside them: 30 clean, loads 4 x 2808 passed.
- CI command `python -m pytest -q -n auto tests/`, twice: 3722 passed, 1 skipped, both times.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #152, squash-merged as `ab6351d` (ab6351d37f16ae697235966ffe77b528280521ce).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
