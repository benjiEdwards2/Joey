# JY-116 Season page head: "Season N" eyebrow + S-switch check

Status: spec
Size: S
Live risk: none
Area: `hub/templates/media_film.html`, `hub/templates/_episode_flow.html`, `hub/media_film.py`, `tests/hub/` (only if B. picks A or B below)
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
Only if B. picks A or B:
1. A season page's head shows the chosen eyebrow above the show title, in the episode page's existing eyebrow style (`.epeyebrow`; no new CSS, no new colour).
2. It uses the page's real season number. A show page, a film and an episode page are unchanged (the episode page keeps "Show · S2 · E3 of 12").
3. A season page of a one-season show (no switch) still shows the eyebrow.
4. Red test first: render a season page through the app's Jinja env (as `tests/hub/test_episode_flow_templates.py` does) and assert the eyebrow is present; it fails on today's code. Plus one test for each unchanged page above.

## Data
None. `nav.seasons` already holds the season numbers and the season's episode list is already read.

## Performance budget
Media item page, warm p95 <= 150 ms. No new reads.

## Options and the pick
None picked yet. See Questions.

## Out of scope
Crumbs on the season page. Changing the h1, the status line or the switch itself. The episode page.

## Accept checklist
On a live season page: the eyebrow says which season at the top of the head; the switch is unchanged; an episode page is unchanged.

## Questions for B.
1. What should a season page's head say above the show title?
   - **A (recommended): "Season 2 of 4".** Same quiet style as the episode eyebrow ("Ted Lasso · S2 · E3 of 12"). Says where you are, and still reads right on a one-season show.
   - **B: "Season 2 · 12 episodes".** Says what is on the page, but not how many seasons there are.
   - **C: nothing.** Keep today's head; the highlighted S2 in the switch is the only season word (a one-season show would have none). Closes as "verified, no change".

   Answer like "1A".

## Shipped notes
Not shipped. Waiting on question 1.
