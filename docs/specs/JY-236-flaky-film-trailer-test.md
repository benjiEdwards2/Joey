# JY-236 Flaky test: trailer-wins test fails on a slow machine

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: tests/hub/test_media_film.py
Needs: none
Options page: none: test-only fix

## Problem
`tests/hub/test_media_film.py::test_jellyfin_trailer_wins_and_short_or_foreign_urls_stay_plain_links` failed under load on Windows twice on 2026-10-24 (JY-101, JY-153 builds): the Trailer button held the vimeo link where the keyed YouTube link was expected. Linux CI passes.

## Cause
A race between the test's second page render and the film page's background read, not shared state or the clock.
1. The first GET of `/media/item/mov1` is a cold page: `film.pending` lists the Jellyseerr parts and `warm_extras` starts the title read in the `film-extras` pool.
2. The test then swaps the Jellyfin trailer to a vimeo link, calls `media_item.clear_cache()` and GETs again, without waiting for that read.
3. If the read has landed (`raw` cached) the second page picks the keyed Jellyseerr trailer (the expected result). If it has not, `raw` is MISSING, the only candidate is Jellyfin's vimeo link, and the button shows it (the real page then fills the keyed trailer later through `late_trailer`, by design).
Only the test is wrong: the product behaviour is as specced.

## Acceptance criteria
1. The test waits for the in-flight background read (`media_film.drain_extras()`) before the second GET. No assertion changes (rule 4: no assertion weakened, so no dated line needed).
2. 20/20 pass under load (`-n 4` of tests/hub running while the test loops) and 20/20 with the Jellyseerr read slowed by 0.05 s.

## Data
None.

## Performance budget
None.

## Out of scope
Other tests in `test_media_film.py`: with the Jellyseerr read slowed by 0.05 s the whole file was run; this was the only failure.

## Proof
Method: load = `pytest tests/hub -n 4` in the background while the single test loops; slow = a throwaway plugin that sleeps in `media_film.seerr_bundle` (stands in for a loaded machine).
- Before, plain load: 0/25 failed under `-n 4` load and 0/30 failed alone on this machine (the race window is a few ms; this machine did not hit it).
- Before, slowed read: 10/10 failed at 0.02 s, 0.1 s and 0.3 s (same assertion text as the report: vimeo link vs youtube key); 0/10 at 0 s.
- After: 20/20 pass with the read slowed 0.1 s; 20/20 pass looping beside a full `-n 4` tests/hub run (2635 passed).

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #107, squash-merged as `574ff88` (574ff887d010b70df05d31fd6f0fe84ba6db0d28).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
