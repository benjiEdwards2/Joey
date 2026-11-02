# JY-290 Remove the season rating chart, season comparison and bottom seasons list

Status: spec
Size: M (the bottom list carries features the carousel above lacks; see below)
Live risk: none
Area: `hub/templates/media_film.html` (rating-strip section, `ef.compare` call, `Seasons` section), `hub/templates/_episode_flow.html` (`compare`, `strip`), `hub/static/control-surface.css` (`.compare`, `.ratestrip`), `tests/hub/`
Needs: none (JY-269 P2 supplies the carousel above)
Options page: yes, 2 options at desktop / iPad / phone / TV (what happens to the bottom list's extras)

## Problem
B., 2026-11-02: "remove the seasons at the bottom if you are to keep the scrollling carousel like you have above. Remove the season 1 or season overall ranking bar char. It doesn't look good, nor does the season comparison."

## What the code does today
- Season comparison: `ef.compare(ratings)` ("Seasons compared", show page only).
- Season bar chart: the `#rating-strip` section ("Season N" on a show, "Episode ratings" on a season page), drawn by `ef.strip`. Neither is gated by `tv_mode`, so the TV draws both too.
- Bottom list: the `Seasons` section (`<details class="seasonbox epseason">` per season) on web and phone only; the TV already skips it.
- The carousel above is `.tl-eps` (season chips + sideways episode tiles, JY-269 P2). It has per-episode state words and Play, but not the bottom list's "mark season watched" toggle (`wa.season_toggle`), the season state word, or the Sonarr-only seasons (`film.seasons_sonarr`, JY-113).
- The chips and compare rows link to `#season-N`, which only exists in the bottom list.
- Episode pages draw a small `ef.strip(..., mini=true)`; B. did not mention it.

## Acceptance criteria
1. The "Seasons compared" block is gone on show pages, on desktop, phone and TV.
2. The season rating bar chart (`#rating-strip`) is gone on show and season pages, on desktop, phone and TV (Question 2).
3. The bottom `Seasons` section is gone on web and phone; the carousel above is the only seasons list.
4. Per-episode ratings still show in each tile caption (`ef.rowrate`); the ratings read is kept for them.
5. Nothing from the bottom list is lost silently: "mark season watched", the season state word and Sonarr-only seasons are handled as the pick says.
6. No dead anchors: season chips link without `#season-N` (or to the carousel), and no template links to a removed id.
7. Unused CSS and macros (`.compare`, the strip) are removed only if nothing else uses them (the episode mini strip decides; Question 3).
8. Tests: the removed blocks are absent on show, season, episode and TV pages. `test_episode_flow_templates.py`, `test_episode_ratings.py`, `test_media_episodes.py` (Overview < Seasons order) and `test_season_state.py` are updated, each change dated here. The season toggle stays tested wherever it moves.

## Options (page to build)
- A. Trim only: remove the three blocks and keep the carousel as is. "Mark season watched", season state and Sonarr-only seasons disappear from the page.
- B. Trim and move the extras (recommended): a season state line and a "Mark season watched" action beside the season chips; Sonarr-only seasons as dimmed chips. Keeps every feature, more build.

## Data
`film.ratings`, `film.seasons`, `film.seasons_sonarr`, `film.tv.seasons`. No schema change.

## Performance budget
Media item page warm p95 <= 150 ms (fewer nodes, same reads). Measured on the preview.

## Out of scope
Episode page rating line and mini strip (unless Question 3 says so). The JY-269 hero. The Episodes carousel itself.

## Accept checklist
- [ ] Show page: no comparison, no bar chart, no seasons list at the bottom.
- [ ] Season page: no bar chart, no bottom list.
- [ ] TV show and season pages: no chart or comparison.
- [ ] Marking a season watched is still possible (if B).

## Questions for B.
1. Season "mark all watched", season state word and Sonarr-only seasons: A. drop them with the list, B. keep them beside the chips (recommended; nothing you use disappears).
2. TV: remove the chart and comparison there too? A. yes (recommended), B. web and phone only.
3. Episode page mini rating strip: A. keep (recommended, you did not mention it), B. remove.

## Shipped notes
