# JY-250 TV session fixes: 404 centring, Tonight safe area, season eyebrow, Back from episode, Diary month row

Status: building
Size: M
Live risk: none
Area: hub/static/tv.css, hub/static/tv.js, tests/hub/ (TV tests); JY-249: tests/hub/test_tv_shelves_tmdb.py
Needs: none
Options page: none: fixes against the existing picks (JY-188, JY-189, JY-192, JY-196)

## Problem
The grouped TV session on 2026-10-25 (`JoeyTV\scripts\logs\tv_session_1025.log`, checklist at the top of
`JoeyTV\TV_UI_PLAN.md`, shots in `JoeyTV\review\tv-ui-2026-10-25\shots\`) failed five checks:

- **#7** (by eye, `device\by_eye_07_notfound.png`): the 404 page sits left of centre. The section is `sec narrow nf`;
  `.narrow` (control-surface.css, `max-width: 32rem`) is never reset in tv.css.
- **#9 / #36** (`device\dev_movies_tonight_0first.png`): the Tonight row is 884 px (3 x 200 cards, 2 x 40 gaps, a 40 px
  column gap, the 164 px "Deal again"). The safe area is 864 px, so 4 items sit outside it (`outsideSafe 0 -> 4`).
- **#13**: the season page's "Season N of M" eyebrow (`p.epeyebrow`) is 12 px on the TV. The episode page's eyebrow is
  also `tv-eyebrow` (JY-192, 18 px); the season line is not, and tv.css had no `.epeyebrow` rule.
- **#15**: Home -> episode -> Back -> series (correct) -> Back -> the series again (run 1) or `/media/discover`
  (run 2). Never Home.
- **#28** (`device\diary_tv.png`): the Diary month card stacks label, films, episodes and hours in rows. tv.css
  `.tvmonth` sets `display: flex` but `.monthcard` (control-surface.css) sets `flex-direction: column`.

## Cause of #15
`goUp()` (JY-192) replaces the episode's history entry with the series (`location.replace`). That part works: history
is then [..., Home, Series]. The next Back is not the page's, so the shell calls WebView `goBack()`. Chromium's history
intervention marks an entry skippable when its page navigated without a user gesture, and `goBack()` passes over
skippable entries. The session script reached the episode with `location.href = ...` from CDP (no gesture), so Home
was skippable and Back went to the entry before it (the series from the earlier check, or Discover), matching both log
lines exactly. A real remote's OK is a gesture, so a real friend probably did not hit this, but the shell's Back
should not depend on how Home was left. The node model below reproduces the log: the no-gesture case went to the page
before Home.

## Acceptance criteria
1. #7: `html.tv .sec.nf` has `max-width: none` and outranks `.narrow`. The 404 message and button are centred.
2. #9 / #36: the Tonight row, with its focus rings, fits the 864 px safe area: 3 x 200 + 3 x 28 + 164 = 848 px,
   + 2 x 7 px rings = 862 px. The cards stay 200 px (JY-189 posters, h=400). Only the two gaps change (40 -> 28 px).
3. #13: `html.tv .epeyebrow` uses the `tv-eyebrow` look: 18 px, 600, .1em, uppercase, `--tv-t4` (its separators too).
4. #15: Episode (from Home) -> Back -> Series -> Back -> Home -> Back exits, with and without a user gesture on the
   way in. Home's JY-187 remembered poster is focused again. `goUp()` leaves an up-mark `{to: series, from: episode}`
   in the trail; Back on that series, straight after, is `history.back()` from the page (JS history never skips) and
   returns true. The mark is cleared on use and whenever another page loads.
5. #15 guarantees kept: Series -> Episode -> Back is the shell's own Back (the series), and the next Back leaves the
   series for the page before it, never the episode (no loop). An episode opened as the first page (deep link,
   process kill) still goes up to the series, and the next Back is left to the shell (it loads Home).
6. #28: `html.tv .tvmonth` has `flex-direction: row` and outranks `.monthcard`.
7. Off the TV nothing changes: every rule is under `html.tv`, tv.js loads only in TV mode.

## Tests
`tests/hub/test_tv_session_fixes.py` (new): one CSS test each for #7, #9, #13 and #28 (rule, value, specificity over
the base rule); three node tests for #15 with a model of the shell's WebView history (entries, `location.replace`,
`history.back()`, BackPolicy, goBack skipping skippable entries).
Red before the fix: the four CSS tests and `test_episode_from_home_back_series_back_home_under_node[no-gesture]`
(steps went `/media/item/show`, `/media/movies`: the page before Home, as on the TV). The remote, no-loop and
deep-link tests were green before and after (guard rails).

Changed test, 2026-10-25: `tests/hub/test_tv_posters.py::test_tv_css_carries_the_tonight_rules_without_touching_the_shared_sheet`
pinned the Tonight gap at 40 px; it now pins 28 px (criterion 2). Not weakened.
Changed test, 2026-10-25: `tests/hub/test_episode_flow_templates.py::test_season_eyebrow_survives_tv_mode_markup`
asserted the word `epeyebrow` was absent from tv.css, as a proxy for "no TV rule hides it". Criterion 3 adds a rule,
so it now asserts what it meant: the tv.css rules naming `.epeyebrow` exist and none sets `display: none` or
`visibility: hidden`. The markup assertion is unchanged.

## JY-249: flaky `test_tv_page_makes_no_more_upstream_calls_than_the_phone_page`
Failed once on JY-191's CI (run 40164686381, attempt 1): `assert href and "/part/all?p=" in href ...` with
`AssertionError: None` at `tests/hub/test_tv_shelves_tmdb.py:115`. Passed on rerun.

Cause: not the JY-243/244 shape (a read landing too late), the opposite. `build_film` starts the title's background
read first, then does the Jellyfin reads, then peeks the caches. If the background read lands in between, nothing is
pending, the page draws every part inline and has no part request, so `href` is None. `drain_extras()` and `whole()`
cannot help: the read lands inside the page render. Reproduced: a throwaway plugin that sleeps 0.3 s in
`media_film._jellyfin_side` failed the test with the same `AssertionError: None` every time.

Fix (test only): `cold_calls` holds `media_film._load_extras` on an event until the page render has returned, then
releases it before the part request, as on a real cold page where Seerr is slower than Jellyfin. No assertion changed.
Proof: the file with the Jellyfin side slowed 0, 0.3 and 1 s: 19 passed each time; the test alone 10 times slowed
0.3 s: 10 passed.

## Data
None.

## Performance budget
None apply (CSS values and one Back branch in tv.js).

## Out of scope
- The session script's `location.href` navigation in check #15 (`JoeyTV\scripts\tv_session_1025.py` c15). It is what
  marked Home skippable; the fix makes the outcome the same either way. A re-run can keep it.
- #36's `browser/*` tiny / lowContrast rises (overview, movies, tv, person, title_tmdb): these are browser-size
  captures, not TV mode; not part of this brief.
- #32 and #34 (shell 1.0.2 update prompt, sign-in code reuse): shell items, not hub.

## Accept checklist
On the TV (next grouped session):
1. #7: a bad URL shows "404", "No page here" and the button centred on the screen.
2. #9: Movies > Tonight: three cards and "Deal again" inside the safe area (`outsideSafe 0`); Right x3 reaches Deal again.
3. #13: `device --only title_season`: 0 `tiny`; "SEASON 1 OF N" reads at 18 px.
4. #15: from Home, OK on an episode; Back = the series; Back = Home; Back exits.
5. #28: Diary: "This month" and its numbers on one row.

## Questions for B.
None.

## Shipped notes
