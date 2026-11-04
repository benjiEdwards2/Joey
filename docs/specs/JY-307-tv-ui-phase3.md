# JY-307 TV UI overhaul, phase 3: full-bleed Home hero + uniform 16:9 rows

Status: shipped (merged #321 2026-11-04, deploy pending)
Size: M
Live risk: none (TV CSS/templates; no NAS write)
Area: `hub/templates/tv_*.html` (Home), `hub/static/tv.css`, `hub/static/tv.js`, `hub/tv_*.py` (hero play link, tile art), `tests/hub/tv_css.py` + `tests/tv`
Needs: JY-307 P1 #306, P2 #311, P2b #312 (all live 91c73ab). JY-267 logos where present.
Options page: https://claude.ai/artifact/LSg1DfpC5fusr2Mm59kXMC (B.: "TV ui: Prefer option B.")

## Problem
Phase 3 of the JY-307 phasing table (option B): "Full-bleed Home hero with Resume / More info (hub passes the hero item's play link), uniform 16:9 rows (backdrop + JY-267 logo, poster fallback)". Proves: first row on screen at y <= 640 on 1080; image load audit < 2 s.

## Build
1. Home hero full-bleed under the left rail (P2): backdrop at full strength with the scrim only behind the text block; title (JY-267 logo when present, else text), amber eyebrow, two-line synopsis, buttons Resume (or Play when not started; the hub passes the hero item's play link) and More info (title page). Hero = the first Continue watching item, else the first item of the first row.
2. Every Home row uses one 16:9 tile of one width (352 px at 1080 in the P2b-scaled rem): backdrop + logo overlay when the title has a logo, else backdrop + one-line caption, else the poster cropped to 16:9 with the caption. The cast row (person page) stays circles. Discover keeps posters (phase 4).
3. Reviewer leftovers from P2/P2b folded in: the backdrop runs under the rail (no hard edge at the rail), the hero's circular focus element sized in px not rem (so the P2b zoom-out does not shrink it twice), `tests/hub/tv_css.py` module docstring updated to the P3 numbers.
4. Open question Q3 from the options page (every row 16:9, or library rows keep posters) is unanswered: build B as shot (every row 16:9) and put the alternative on the review page as a question.

## Acceptance criteria
1. 1920x1080 shot: hero full-bleed, Resume/More info on one row, first row's top at y <= 640.
2. All Home rows 16:9, one width; a title without a backdrop falls back to the cropped poster, never a blank tile.
3. TV audit passes (no text under the floor, no sideways scroll); image load audit < 2 s on the test rig.
4. D-pad: Down from the hero buttons lands on the first row's first tile; Back behaviour unchanged.
5. `tests/hub/tv_css.py` pins updated; full tree passes.

## Out of scope
Title pages, Discover, player overlay (phases 4 and 5).

## Shipped notes
