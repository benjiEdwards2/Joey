# JY-116 Season page head: "Season N" eyebrow + S-switch check

Status: building
Size: S
Live risk: none
Area: `hub/templates/media_film.html`, `hub/templates/_episode_flow.html`, `tests/hub/test_episode_flow_templates.py`
Needs: none
Options page: none: the options are one line of wording each and follow the episode page's existing eyebrow

## Problem
"Season page head: 'Season N' eyebrow + S-switch check (switch did not show in the preview)." Two checks: does the season page draw the S1 / S2 switch, and does its head carry a "Season N" eyebrow.

## What the live check found (2026-10-24)
Read-only GET of a season page from inside `joey-hub` on the NAS (no identity header, household view; nothing written or configured; no secrets printed):

1. **S-switch: works.** The Ted Lasso S2 page draws `<nav class="seg seasonseg" aria-label="Seasons">` with S1, S2 (the current one, `class="on"`, `aria-current="page"`), S3, S4. The Slow Horses S4 page draws S1 to S6. Each link goes to that season's page.
2. **"Season N" eyebrow: not there, and the code never draws one.** The head is: the show title as h1 ("Ted Lasso (2020)"), the tagline, the switch, "TV · 4 seasons · 44 episodes · Drama · Comedy", then the status line ("On server · 44 episodes · all watched ..." for the whole show). No head text says "Season 2". The page title is "Ted Lasso · Joey". The only word for the season is the highlighted S2 in the switch, and the "Episode ratings" / "Seasons" sections below.
3. **Why:** `ef.eyebrow(epnav)` is called only inside `{% if film.episode %}` in `media_film.html`, and `eyebrow()` needs `nav.season`, which `episode_nav()` sets to None on a season page by design. The 2026-10-16 contract (`review/2026-10-16-episodes-ux/EPISODES_CONTRACT.md`) lists the eyebrow for the episode page only; for the season page it says "head gets the `nav.seasons` segmented switch". The mock's season page had a "Show · Season N" line, but it never made the contract. So this is a missing piece of the design, not a broken condition.
4. **Why the switch did not show in the preview:** the switch needs the show's seasons from a Jellyfin read and more than one season (`seasonswitch()` draws nothing for one season). The demo snapshots (`hub.seed_demo`) hold only a Jellyfin summary line (no shows) and a demo hub has no `JELLYFIN_URL`, so there were no seasons to switch between. Preview data, not a condition bug. Not reproduced in a preview hub (machine rule), so this is read from code plus the live result.

Result: S-switch verified, no change. The eyebrow is a new line of wording on a screen, so it waits for B.

## Acceptance criteria
B. picked A (2026-10-24):
1. A season page's head shows "Season 2 of 4" above the show title, in the episode page's existing eyebrow style (`.epeyebrow`; no new CSS, no new colour).
2. It uses the page's real season number. A show page, a film and an episode page are unchanged (the episode page keeps "Show · S2 · E3 of 12").
3. A season page of a one-season show (no switch) shows "Season 1 of 1". The "of" number is the highest season number in `nav.seasons` (the list length when numbering has no gaps). Nothing is drawn for Specials (season 0), when no season is marked as the page's, or when the season list is empty.
4. Red test first: render a season page through the app's Jinja env (as `tests/hub/test_episode_flow_templates.py` does) and assert the eyebrow is present; it fails on today's code. Plus one test for each unchanged page above.

## Data
None. `nav.seasons` already holds the season numbers and the season's episode list is already read.

## Performance budget
Media item page, warm p95 <= 150 ms. No new reads.

## Options and the pick
Picked 2026-10-24. B.: "JY-116: A" (A: "Season 2 of 4", the same quiet style as the episode eyebrow).

## Out of scope
Crumbs on the season page. Changing the h1, the status line or the switch itself. The episode page.

## Accept checklist
On a live season page: the eyebrow says which season at the top of the head; the switch is unchanged; an episode page is unchanged.

## Shipped notes
Not shipped. Draft, built on `feat/JY-116-season-head-verify`:
- New macro `seasonline` in `_episode_flow.html`, called from the head of `media_film.html` when the page has `nav` and no episode. Reuses `.epeyebrow`: no new CSS, no new colour. TV mode (`html.tv`) has no rule that hides `.epeyebrow`, so the line shows there as on the episode page.
- No new read and no new data: it reads `nav.seasons`, which the page already holds (rule 7 not touched).
- The existing season-head test asserted "no `epeyebrow`"; it now asserts "no episode eyebrow" (2026-10-24, because the season page now has its own eyebrow).
- Edge rules the spec did not name, for the reviewer: "of" counts to the highest season number, not the list length (a show listed as S4, S5 reads "Season 5 of 5", never "Season 5 of 2"); Specials (season 0) get no eyebrow rather than "Season 0 of N".
