# JY-316 round 3: scores strip in the hero on show, season and episode pages; no right sidebar

Status: building (B. 2026-11-06, Sweep 35 on JY-316: "Change — Fine for the phone. Only change I would have is placing the ratings higher up in towards the header to allow the episode page to fully span the page. I think I would prefer that. Make it slightly smaller as well. I am happy if there are only 3 ratings in there. IMDB, TMDB and yours.")
Size: S
Live risk: none (template + CSS; no data change)
Area: `hub/templates/media_film.html` (tvweb branch only), `hub/static/control-surface.css`, `tests/hub/` (pins from JY-317 for `.filmcols.tlcols` / `aside.filmcol-side` on show pages)
Needs: PR #328 merged (ce8e6fb). Film pages (`filmweb`, JY-280 pick A) are NOT touched by this round (Q1).

## Problem
PR #328 gave show, season and episode pages a 300 px right-hand Scores and details sidebar from 1024 px. B. wants the ratings up in the hero instead, smaller, and only three of them, so the episode page (and show/season) spans the full width.

## Change (smallest)
1. On `tvweb` pages (show, season, episode; off the TV), drop the `.filmcols.tlcols` two-column wrap and `aside.filmcol-side`. The main content (Episodes row, part-of banner, cast tiles, crew/makers, where to watch) spans the page at every width.
2. A compact scores strip in the hero, under the title/meta line and above the buttons (desktop and phone): exactly three pills, in this order, each present only when it has a value:
   - IMDb (the show's IMDb pill as `_film_scores.html` draws it today; on a season page the season mean "8.2 avg" if the show value is absent, else the show value: keep it simple, one IMDb pill),
   - TMDB (`ts.own` TMDB pill only; drop RT and MC from the strip),
   - Yours (rated pill, else `avg_pill` as today, else the "Rate" link to `#rate`).
   Same macros, wrapped in a new `.hero-scores` container; pills ~15 % smaller than `.scorepill` (smaller font, logo 14 px, tighter padding), left-aligned on desktop, centred on phone like the rest of the hero text.
3. Details (`detailsec`) and the owner's File drawer move under the main content, full width, in that order, after where-to-watch. Runtime and Rated stats: keep inside Details as two rows (no `.stats.numbers` card on tvweb pages any more). RT / MC / site pills: into the Details "Links" row (`sitepills`) so nothing is lost.
4. TV mode (`html.tv`): unchanged. Film pages: unchanged.

## Acceptance criteria
1. Show, season and episode pages at 1440: no `aside.filmcol-side`; cast tiles and episodes span the content width; `.hero-scores` in the hero with at most three pills (IMDb, TMDB, Yours).
2. Phone 390: the strip centred under the title; nothing overflows.
3. Rate still opens the popover from the Yours pill; a season page's Yours pill rates the season (JY-316 d unchanged).
4. Details and File drawer under the cast; RT/MC appear as links in Details when present.
5. Film page markup unchanged (its JY-280 pins pass unchanged); TV pins (`tests/hub/tv_css.py`) unchanged.
6. `tests/hub` and the full tree pass; update the JY-317 tests that pinned the sidebar on show pages.

## Questions (defaults built)
- Q1 Film pages keep their sidebar (JY-280 pick A) — default yes; say if films should match.
- Q2 The IMDb pill on a season page shows the show's IMDb score, not the season mean — default show score.
