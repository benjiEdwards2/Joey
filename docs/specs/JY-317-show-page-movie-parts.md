# JY-317 TV shows 2.5: show pages take the movie hero chips, cast tiles, scores column and File drawer

Status: building (B. 2026-11-04 on Plan 2 phase 2.5: "Yes, I like the scores column for the ratings."; B. 2026-11-06, Sweep 34: run JY-317 now, with JY-316 round 2 and JY-283)
Size: M
Live risk: none (templates + CSS; no new data, no new call)
Area: `hub/templates/media_film.html`, `hub/templates/_film_makers.html`, `hub/templates/_film_cast.html`, `hub/static/control-surface.css` (title-page rules, not the tokens), `tests/hub/`
Needs: JY-316 round 1 (same PR #328, built together with JY-316 round 2 and JY-283)
Options page: none (reuses the film page's picked parts: JY-280 P1 chips + cast tiles, JY-280 P2 / JY-281 column, JY-284 File drawer)

## Problem
Plan 2 phase 2.5 (JY-287): web and phone show pages should match the film page: hero chips, 2:3 cast tiles, the scores column and the File drawer. B. 2026-11-06 (Sweep 34): "Remember the rating column sitting on the right hand side as a smaller side bar. Can you please implement that. Instead of having it as a row of things." and "Please change all headshots of cast members to 2:3. Stop placing them in circles. For shows and movies." JY-283 (B. 2026-11-02): "Please use a similar box or 2:3 ratio as the poster scetions. Reducing the corner radius and making it a little boxier."

## Change
1. Hero chips: off the TV a show or season page draws its makers as the film's chips (`.makerchips`, `.makerchip`) under the facts line: "Creator <name>" from Created by, "Director <name>" from the show's directors, in place of the headshot circle cards. The creators' Follow buttons stay under them. Network / status chips: the page holds no network or status data today, so skipped.
2. Cast tiles: the film's 2:3 `.casttiles` row on shows and seasons (JY-316 round 2, R2b).
3. Scores column: from 1024 px the show / season body is two columns like the film's (`.filmcols` + `.tlcols`): main = the Episodes row (chips, episodes), the part-of banner, the cast, crew and where to watch; a 300 px right-hand column (`.filmcol-side`) = Scores (every pill and Rate as before), Details and the File drawer. Below 1024 px the column stacks under the main content.
4. File drawer: the owner's existing closed drawer (`_title_file.html`, owner-gated server-side) moves into that column. Off-server shows have no file data: nothing drawn.

## Acceptance criteria
1. Show and season pages at 1440: the Scores card is in a right column about 300 px wide beside the Episodes row and cast; at 390 it sits under them.
2. Every score pill and the Rate / Yours pill still render on show and season pages (round 1 tests green).
3. Show page hero: Creator / Director chips, no `.makerpic` circles off the TV.
4. Cast on show and season pages: `.castsec.casttiles` 2:3 tiles.
5. File drawer in the right column for the owner; never for her view, friends or the guest front.
6. TV (html.tv) unchanged: no TV template or tv.css change, `tests/hub/tv_css.py` pins green.
7. `tests/hub` and the full tree pass.

## Tests
New `tests/hub/test_show_page_jy317.py`. Changed 2026-11-06 (the old look was the one B. asked to replace, so each pin now asserts the new one): `test_media_film.py` (show creator cards -> chips, the circle-cast CSS pin -> 2:3 tile pin, the cast-tiles template pin), `test_media_tv_crew.py` (show "Directed by" cards -> Director chips), `test_film_page_e4.py` (show hero order: chips under the facts line), `test_guest_follow_scope.py` and `test_media_follow_shows.py` (the Created by row is found by its chips; Follow buttons unchanged).

## Data
None new: `film.makers`, `film.directors`, `film.cast`, `film.numbers`, `film.file`.

## Performance budget
Media item page warm p95 <= 150 ms: markup moves only, no new read.

## Out of scope
The TV look (JY-307); the person page; episode pages (JY-315 keeps its carousel head and guest tiles); network / status / year chips (no data on the page); new upstream reads.

## Accept checklist
- [ ] Show page: chips under the title, 2:3 cast, Scores as a right-hand column, File drawer in it.
- [ ] Season page: the same, with one seasons row (the chips).
- [ ] Phone: the column stacks under the main content.

## Shipped notes
