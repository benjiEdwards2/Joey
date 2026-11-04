# JY-307 TV UI overhaul, phase 4: backdrop-led title pages + Discover search line

Status: shipped (merged 2b4b290 2026-11-05 on B. Sweep 29 "JY-307: Accept"; cast 2:3 tiles follow-up = JY-323; deploy tonight)
Size: M
Live risk: none (TV templates/CSS/JS; no NAS write)
Area: TV branches of `hub/templates/media_film.html` (film, show, season, episode), the person page's TV branch, `_tv_title_extras.html`, `media_discover_guest.html` / `_guest_discover_grid.html` (TV), `hub/static/tv.css`, `hub/static/tv.js`, `hub/tv_home.py` (backdrop/logo helpers reused), `tests/hub/tv_css.py`, `tests/hub/test_tv_*`, `tests/tv`
Needs: JY-307 P3 #321 (main d24c4bb). JY-267 logos where present. JY-321 person backdrop (TMDB key live).
Options page: https://claude.ai/artifact/LSg1DfpC5fusr2Mm59kXMC (B.: "TV ui: Prefer option B.")

## Problem
Phasing table row 4 (option B): "Backdrop-led title pages (film, show, season, episode, person): no poster, one button row, first row on the first screen; Discover search line". Proves: the JY-259 P3 checks (buttons on one line, season chips, Down from Play lands on E1). Option B's title page as mocked: "The poster goes. The backdrop fills the top 65 % of the screen behind the text. Title 112 px (pre-P2b rem; use the P2b-scaled equivalent), then facts, synopsis and buttons (white on focus) in one row. On a show the Episodes row and season pills sit on the first screen." Discover: "The search field shrinks to an 80 px tall pill on one line with the type chips. The Search button and hint go (OK on the field types). The grid is 8 across with a slim foot band."

## Build
1. Film, show, season and episode pages on TV: poster card removed; the backdrop (JY-321 / tile_hero backdrop, logo overlay when the title has a JY-267 logo, else the text title) fills the top ~65 % under the P2 rail, scrim only behind the text block; eyebrow (kind, year, runtime or season facts), title, two-line synopsis, then ONE button row (existing actions: Play/Resume, Rate, Watchlist, Request/Remove where they exist today; nothing new). A title with no backdrop falls back to the P3 cropped-poster treatment, never a blank band.
2. Show page: the Episodes row with season chips (pills) starts on the first screen (its top at y <= 640 at 1080). Season page: same, episodes row first. Episode page: still/backdrop as the hero; TV front only reuses existing data (no new upstream calls).
3. Person page on TV: backdrop-led hero (JY-321 backdrop, else the P3 fallback), name + facts, then the filmography rows as today; the cast circles elsewhere unchanged.
4. Discover on TV: search field + type chips on one line (an 80 px pill at the pre-P2b scale, i.e. the P2b-scaled rem), Search button and hint line removed (OK on the field types), grid 8 across, state word in a slim foot band on the tile (the P1 state words: Request lavender / On Joey green / Requested amber). The request pop-up unchanged.
5. D-pad: Down from the button row lands on the first row's first tile (Episodes E1 on a show, as JY-259 P3 proved); Back behaviour unchanged. The TV audit (text floor, no sideways scroll) passes on every shot.
6. `tests/hub/tv_css.py` pins updated for the new hero/Discover numbers; full tree passes.

## Acceptance criteria
1. 1920x1080 shots of a film, a show (with seasons), a season, an episode and a person page: no poster card, backdrop hero, one button row, text over the scrim readable; show/season: Episodes row top at y <= 640.
2. Discover 1920x1080: one search line with chips, no Search button, no hint; grid 8 across; focused tile shows its state word.
3. D-pad drill (test rig): Down from Play on a show lands on E1 of the open season; Back from each page returns where it came from.
4. A title with no backdrop renders the cropped-poster fallback (shot), never blank.
5. TV audit passes on all shots; image load audit < 2 s.
6. `tests/hub` + `tests/tv` pass; full tree passes. Desktop/phone pages untouched (before/after shots identical at 1440 and 390 for a film and an episode page).

## Out of scope
Player overlay (phase 5, `tv/`), new upstream calls, desktop/phone changes, the Discover panel (option C).

## Shipped notes
