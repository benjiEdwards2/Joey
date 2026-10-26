# JY-121 Merge play stats into History

Status: spec (built as the recommended option for B.'s morning review, 2026-10-26)
Size: S
Live risk: none
Area: `hub/media_nav.py`, `hub/templates/media_diary.html`, `hub/templates/media_server_history.html`, `hub/templates/_history_switch.html` (new), `hub/static/control-surface.css` (three `.histseg` lines, no token change), `hub/README.md`, `tests/hub/`
Needs: none
Options page: none yet. The before / after screenshots at four sizes are in `JoeyTV\review\morning-2026-10-27\JY-121\`.

## Questions for B.
1. How should Play stats join History?
   - **A: one History tab with a Diary · Play stats switch (built as).** Both pages carry the same two-part switch at the top. Play stats now lights Activity › History and its heading reads "History" (today it lights no tab and reads "Activity"). The "Play stats" text link under the stats line goes. Play stats keeps its URL, so links, the Overview "Most played" shelf and the friends' front rules do not change. No extra work on the History render.
   - **B: Play stats folded into the diary page.** A "Play stats · 30 days" fold under the month card (plays, hours, top 3 shows and films, hour bars); the separate page goes and its URL redirects. One page, but every History render pays for one more stats query, and the phone page gets longer.
   - **C: Play stats as its own Activity tab.** Eight tabs (Live · History · Play stats · To rate · …). Most visible, but it is the opposite of the nav tidy, which cut tabs.
2. Switch words: **"Diary · Play stats" (built as)**, or "Watches · Plays".

Data / privacy / budget notes:
- Data: none. No schema change, no new route. Both pages read what they read today.
- Privacy: Play stats is private-only today (`hub/guest.py` PRIVATE). The switch shows only where `guest_allows("/media/server/history")` is true, so the friends' front never sees it, and the TV's slim diary never shows it either (JY-196).
- Budget: hub page render p95 ≤ 50 ms. Option A adds one small include and no query, so no change is expected.

## Problem
Nav-tidy leftover (DECISIONS, 2026-10-13): "the play-recorder page keeps /media/server/history as a "Play stats" link inside History (merge later)". Today Play stats is a page under Activity with no tab lit and the heading "Activity", reached by a plain text link from the diary.

## Acceptance criteria
For option A:
1. `/media/server/history` lights Activity › History, and its page heading reads "History".
2. History (`/media/diary`) and Play stats (`/media/server/history`) both show one switch, `<nav class="seg histseg" aria-label="History view">` (the shared `.seg` recipe, current view filled like the season switch), with "Diary" and "Play stats"; the current page's link carries `aria-current="page"`.
3. The diary's old "Play stats" metaline link is gone (the switch replaces it).
4. On the friends' front the diary shows no switch and no link to `/media/server/history`; that route stays private.
5. On the TV (TV mode) the diary shows no switch.
6. Every other Activity page lights the tab it lit before.
7. The suite only grows. Three pins change, with dated notes (2026-10-26): `test_media_frame.py` ROUTES (`/media/server/history` now lights History), `test_media_plays.py::test_history_page_empty_in_frame` (History lit, was none) and `test_media_diary.py::test_diary_is_activity_history_and_links_play_stats` (the switch replaces the link). None deleted.

## Data
None.

## Performance budget
Hub page render, warm p95 ≤ 50 ms (row 1). No new query; measured on the NAS by `scripts/budgets.py` at the full check.

## Options and the pick
See "Questions for B.". Pending B.'s pick; built as A.

## Out of scope
- Moving the Play stats URL under `/media/diary` (would touch the guest route tables and many pins).
- Changing what Play stats shows.

## Accept checklist
- Activity › History: the switch reads Diary · Play stats; tap Play stats; History stays lit and the heading still reads History.
- The window chips (7 days … All time) still work on Play stats.
- Phone: the switch fits on one line above the month card.

## Shipped notes
