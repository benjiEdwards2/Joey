# JY-316 round 4: show and season pages get the film-style right sidebar, higher and narrower; episodes full width underneath

Status: shipped on PR #330 (5475c8a) with the final swap: Episodes row first, then cast + sidebar (B. Sweep 37)
Size: S
Live risk: none (template + CSS)
Area: `hub/templates/media_film.html` (tvweb branch), `hub/static/control-surface.css`, `tests/hub/` (JY-317 / r3 pins)
Builds on: branch jy-316-r3-hero-scores (PR #330). Round 3's hero strip and "Details under the content" are replaced by this.

## What B. wants (read of his words)
The show and season web pages should look like the film page: a right-hand sidebar with Scores, Details and the File drawer. It sits "higher": directly under the hero, beside the cast (and crew, where-to-watch), as on the film page. The Episodes row (season chips + episodes) is no longer inside the left column; it comes AFTER the two-column block, full width, so episodes never share the width with the sidebar. "Smaller": the sidebar is narrower than the film's 360 px / the r2 300 px, and its pills are the smaller r3 size. Round 3's hero strip goes away (the sidebar is the one place for scores again).

## Change
1. tvweb pages (show + season, web only): body order = hero → `.filmcols.tlcols` two-column block (left `.filmcol-main`: cast tiles, crew/makers, where-to-watch; right `aside.filmcol-side`: Scores card with every pill as before r3 (IMDb, RT, MC, TMDB, sites, Yours/avg/Rate; season IMDb mean on season pages), Details (Runtime with "ends … if you start now", Rated, dates, Links…), owner File drawer) → Episodes row (`section.tl-eps`, chips + episodes) full width under the block → part-of banner, awards, the rest as today. Remove `.hero-scores` and its CSS and the `fp-scores-links` slot added in r3; `_film_scores.html` back to its pre-r3 behaviour on show pages (keep the `episode_page` flag only if still needed).
2. Width: `.tlcols aside.filmcol-side` 260 px from 1024 (film stays 360 px). Below 1024 the aside stacks under the cast, then the Episodes row follows.
3. Pills in the sidebar on tv pages: the r3 small size (26 px high, 14 px logo, 12-13 px text) and a smaller corner radius: `.scorepill` radius 6 px on these pages (today's is the pill/full radius). Apply the same 6 px radius to the film page's sidebar pills too so the two pages match ("make this like the movies"); nothing else on the film page changes.
4. Episode pages: unchanged from r3 (no sidebar, full width, JY-315 hero score line).
5. TV mode unchanged.

## Acceptance criteria
1. Show + season at 1440: `aside.filmcol-side` present, 260 px, directly beside the cast under the hero; `section.tl-eps` comes after `.filmcols` in DOM order and spans the content width; no `.hero-scores`.
2. Season page scores: Yours rates the season; IMDb season mean pill present when loaded (r1-2 behaviour).
3. Phone 390: cast, then sidebar content, then episodes; nothing overflows.
4. Film page: only the pill radius changes (6 px); its JY-280 pins otherwise unchanged.
5. TV pins unchanged. `tests/hub` + full tree pass; r3 pins rewritten.

## Questions (defaults built)
- Q1 Sidebar width 260 px (default) / 300 px as r2.
- Q2 "Radius smaller" read as the score pills' corner radius (default 6 px); say if you meant the cast tiles or the sidebar card.
