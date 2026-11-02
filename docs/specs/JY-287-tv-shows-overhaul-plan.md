# JY-287 TV shows overhaul: audit and next plans

Status: options
Size: L (umbrella: the output is a plan that splits into rows)
Live risk: none (plan only)
Area: `hub/templates/media_film.html`, `_season_episodes.html`, `_episode_flow.html`, `_tv_tile.html`, `media_tv.html`, `hub/media_pages.py` (My shows), `hub/media_home.py` (shelves), `hub/static/control-surface.css`, `hub/static/tv.css`, `tests/hub/`
Needs: JY-282, 288, 289, 290 built (in flight 2026-11-03, treated as done below); JY-280 P2 for the movie reference
Options page: yes, one page per phase that has a screen choice (not for this plan)

## Problem
B., 2026-11-02: "Shows needs a good overhaul. Can you please review all of these and put together a few next plans for covering it all."
Related asks: JY-269 follow-ups, JY-278 (one tile per show), JY-288, JY-289, JY-290, JY-282, and Q8 ("If going into a singular episode. Could you please" is unfinished).

## Treated as done (built today, 2026-11-03)
- JY-282 + JY-288: one overview per page; season ratings averaged, highest first, like movies.
- JY-289 + JY-290: season poster improved; directors only on a single episode; season bar chart, season comparison and bottom seasons list removed.
Check these against the preview before any phase below starts.

## 1. Audit (what the code does today)
Reference: movie page round 2 (JY-280): bigger poster and backdrop, chips, 2:3 cast tiles, scores column, File drawer.

### Show page
- Shares one template (`media_film.html`) with films, seasons and episodes. The hero and Episodes row (JY-269) are good, and B. likes the chips and episode selection ("keep the episode adn season selection as you have them").
- Inconsistent with movies: the hero poster is the old size; no chips for genre, network, status or year; cast is the older circle style (JY-269 P3), not the movie's 2:3 tiles; scores sit under the hero as site pills, not in the movie's scores column (JY-281); file info is its own section, not the File drawer (JY-284).
- B. asked for cast "to the top ... proper sections again": cast still sits low, after Details.
- Clumsy: "Mark season watched", the season state word and Sonarr-only seasons lived in the removed bottom list; the JY-290 pick decides where they went. The "this / all seasons" pill and an all-seasons view are still open follow-ups of JY-269.
- Missing data: no show-level progress ("14 of 40 watched, next S2E3") beyond the chip line; no "last aired / next airs" in the hero; no creator (only directors drawn from episodes).

### Season page
- Same template, season chosen by chip. The poster was thin (JY-289 fixes it). B. wants the season to fill episodes, scores and cast.
- Season scores now show the average (JY-288), but there is no season-level cast (guest stars appear only per episode) and no season overview fallback when TMDB has none.
- Missing: progress at a glance ("5 of 8 watched"), season air-date range.

### Episode page
- Web and phone: crumbs, small hero with the episode line and score, guests, crew, "Where this sits in Season N" (mini chart), previous / next. TV: 16:9 still hero, Play, Mark watched, Season button.
- Inconsistent: web and phone show the show's poster, not the episode still; no chips; guests and crew are separate blocks, unlike the movie cast tiles; the mini strip may be orphaned by JY-290 (its Question 3).
- Q8 is unanswered, so nothing was built for "singular episode".
- Missing: a "Next episode" button; my own rating beside Play on web.

### Shows shelves and My shows
- Recently added shows two tiles for one show (Billions) and only the full-season one has the correct poster and font (JY-278). Tiles are per season, not per show.
- No "new episode" tag, and no choice between "show" and "show with new episode".
- Shelves are not on the new poster style everywhere (JY-277); My shows rows lack the extra columns B. asked for (JY-279).
- The carousel scroll cue is Discover-first only (JY-304).

### By device
- Desktop: strongest; the Episodes row has arrows and wheel.
- Phone: the Episodes row works by swipe and the hero stacks well; the episode status line clips without an ellipsis (parked nit from JY-269).
- TV: separate hero and rows (`tvm`), D-pad only, a different look from web. B., 2026-11-03: it "looks and feels awful" (JY-307). Any web change to shows needs a TV decision, so each phase below says whether it touches TV.

## 2. Plans (B. picks one; each phase is one PR in one area)

### Plan 1: "Align with movies" (cheapest, web and phone only)
Make show, season and episode pages look like round 2 movies. TV is untouched until JY-307.
| Phase | What | Size | Needs |
| --- | --- | --- | --- |
| 1.1 | Show hero: bigger poster and backdrop, chips (network, status, genres, year, seasons) | M | JY-280 P2 shipped |
| 1.2 | Show cast as 2:3 tiles, moved up under the hero; creator and directors in the same row (JY-283, 285 pattern) | M | 1.1 |
| 1.3 | Scores column and File drawer on shows (reuse the JY-281 and JY-284 picks) | M | JY-281, 284 decided |
| 1.4 | One tile per show on Recently added, optional "new episode" tag (JY-278) | M | none |
| 1.5 | Season page: season cast and progress line; remove the "this / all seasons" pill | S | 1.1 |
About 5 PRs. B. decides: the JY-278 tag choice, and whether shows take the movie scores and File picks as they are.
Leaves out: a better episode page, any TV change.

### Plan 2: "Episode-first" (rework around watching progress)
Treat the show as "what do I watch next"; season and episode pages serve that.
| Phase | What | Size | Needs |
| --- | --- | --- | --- |
| 2.1 | Show hero leads with progress and one big button ("Continue S2E3" or "Start S1E1"), plus last aired and next airs | M | none |
| 2.2 | Episode page rebuilt (Q8): still hero, rating, Play, "Next episode", guests as 2:3 tiles, previous / next | M | Q8 answered |
| 2.3 | Season page: progress in words, "Mark season watched", season cast and scores | M | JY-290 pick |
| 2.4 | One tile per show with a "new episode" tag; Continue watching shows the next episode, not the season | M | JY-278 pick |
| 2.5 | Web and phone hero chips and cast tiles matched to movies (Plan 1.1 and 1.2, cut to the minimum) | M | 2.1 |
About 5 to 6 PRs. B. decides: Q8, the Continue wording, whether the Continue shelf changes.
Leaves out: TV look and feel (the TV episode hero already leads with the episode).

### Plan 3: "Full redesign with the TV UI overhaul (JY-307)"
One design for shows across desktop, phone and TV, built after B. picks the JY-307 direction (options page 2026-11-03, recommendation B with A first).
| Phase | What | Size | Needs |
| --- | --- | --- | --- |
| 3.1 | Shared show, season and episode components (hero, chips, cast tiles, scores, file) used by web, phone and TV | L, split into S/M | JY-307 pick |
| 3.2 | Show page on the new components, web and phone | M | 3.1 |
| 3.3 | Season and episode pages (Q8, Plan 2.1 and 2.2 ideas) | M | 3.2, Q8 |
| 3.4 | TV show, season and episode screens on the new TV shell | M | JY-307 phase 1 |
| 3.5 | Shelves and My shows: one tile per show, tag, extra columns (JY-278, 279) | M | 3.1 |
About 6 to 8 PRs; the longest, and the only plan that fixes TV and web together.
B. decides: the JY-307 direction first, then Q8 and JY-278.
Risk: blocked until JY-307 is picked. If Plan 1 or 2 ships first, web and TV drift apart until Plan 3 lands.

## 3. Recommendation
Plan 2 now, folded into Plan 3 later. B. said he likes the current episode and season selection, so the biggest gap is the watching flow (Continue, next episode, the unanswered episode page), not looks. Plan 1's look changes repeat what Plan 3 will redo for TV. Order, in parallel where areas differ:
1. JY-278 (one tile per show): independent, fixes a visible bug today.
2. Plan 2.1 and 2.2 (progress hero, episode page) once Q8 is answered.
3. Plan 1.1 and 1.2 (hero chips, cast tiles), done as 2.5, so web matches movies.
4. TV show screens (3.4) only after the JY-307 pick.
Plan 1 alone is the fallback if B. wants a quick visual match and nothing more.

## 4. Questions for B.
1. Which plan: 1, 2 (recommended), or 3?
2. Q8: what should a single episode page do? Proposed default: still hero, rating, Play, "Next episode", guests as cast tiles, previous / next. Say what to drop or add.
3. JY-278: should a show tile carry a "new episode" tag by default, or a switch between "shows" and "shows with a new episode"?
4. Should the show hero lead with "Continue S2E3" (Plan 2.1), or keep Play as it is?
5. Should shows take the movie scores column and File drawer exactly as picked for movies?
6. Should the show page keep a "this season / all seasons" view, or only the chips?
7. TV: wait for JY-307 before any TV show change (recommended), or fix the TV show page now?
8. Anything on the shows pages you want that is not listed above?

## Acceptance criteria (for this plan)
1. B. picks one plan and answers Questions 2 to 7 (or says "defaults").
2. The orchestrator turns the picked plan's phases into HITLIST rows (each S or M, one area), each with its own spec.
3. JY-287 closes on that split; the unchosen plans stay in this file as the record.

## Data and performance
No schema change in this plan. Later phases: media item page warm p95 <= 150 ms, no new blocking requests.
