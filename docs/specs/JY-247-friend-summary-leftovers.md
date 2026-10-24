# JY-247 Friend summary leftovers

Status: shipped 2026-10-25
Size: S
Live risk: none
Area: hub/media_wrapped.py, tests/hub
Needs: none
Options page: none: no screen change; an existing note ("Plays since <date>") reads the friend's own date

Live risk sets the review tier (see `docs/PROCESS.md`). Anything other than `none` is reviewed as L.

## Problem
JY-190's final verifier found two household-derived values that could reach a friend's Wrapped/Diary summary in `hub/media_wrapped.py`: `recorder_start` (the household's earliest play date) and `show_runtimes` (average episode runtime from household plays).

## Acceptance criteria
1. `recorder_start` for a friend (`jf:<id>`) is the earliest `play.started_at` owned by that friend. With no plays it is None (the page's existing "no data" state: no "since" text). The household's date never reaches a friend. Test: `test_a_friends_summary_never_carries_the_households_earliest_date`.
2. you / her / both views are unchanged (same test asserts the both view still reads the household date).
3. `show_runtimes`: no code change, decision below.

## Data
Reads `play` in media.db; one query in `_read` now filters by the friend's owner key.

## Performance budget
None affected: same single MIN query as before.

## Decision: show_runtimes
A friend's summary never reaches it with data. `own_idx` is built from the household snapshot lists only for you / her / both; for a friend `own` is None (JY-190), so the key list is empty and `show_runtimes` returns {} with no query. Friends therefore get no runtimes and no progress words. Were it ever fed a friend's shows, the average is per-episode runtime metadata of the show, not a viewing count, so it would be acceptable. Kept as is.

## Out of scope
A friend-own runtime source; any change to the private views.

## Accept checklist
Nothing to try on a screen: the friend's Wrapped hours note reads "Plays since <their first play date>" or no "since" text.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #156, squash-merged as `5a0c746` (5a0c746a905a221b4c51ad73390b9b8ab71b94fe).
- Deploy: `2026-10-24T22:53:29Z PASS prev=35c5217 new=5a0c746 suite green, smoke ok tv=current gate=-n2 avail=1985 end=2026-10-24T23:01:29Z dur=480s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
