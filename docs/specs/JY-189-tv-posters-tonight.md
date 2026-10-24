# JY-189 TV posters at 400 px and the Tonight TV layout

Status: building
Size: M
Live risk: none
Area: hub/templates (_poster, _shelf, _library_row, _library_page, area_shelves, media_tonight), hub/static/tv.css, tests/hub
Needs: none (U2, the card scale, gaps and columns, is separate and waits for B.'s scale pick)
Options page: none: shell 02 of `JoeyTV\mockups\tv-v2` (`02-library.html`, screen "Tonight") is the design; plan row U3 in `JoeyTV\TV_UI_PLAN.md`

## Problem
TV_UI_EVALUATION G2: the grid and Overview shelves fetch `h=240` (160x240 files) and draw them at 260-277 x 392-416 device px, so posters are soft from the couch. T1/T2: on Tonight the three cards are drawn at 560-594 device px from the same 160x240 file, the "Three for tonight" label hides under the sticky sub-tabs, the cards run off the bottom and "Deal again" is clipped.

## Acceptance criteria
1. `poster()` takes a `tv` flag; when true it fetches `h=400`. Callers pass `tv_mode(request)`: Overview shelves (`area_shelves.html`), the Movies / TV grid cards and the Suggestions carousel (`_library_page.html`, `_library_row.html` `card`), the hub shelf macro (`_shelf.html`, flag only), and Tonight.
2. Outside TV mode every one of those URLs is exactly as before (`h=240`). Small row thumbnails (`h=120`, list rows) never change.
3. Tonight: `<section class="sec tn">`, the cards in `.poster-grid.big`, "Deal again" in `.tn-deal`.
4. `tv.css` (TV mode only, `html.tv`): three 200 px cards centred, 40 px gap, "Deal again" beside them in the same row, no focus scale on these cards (ring only), label first in the body. Nothing is added to `control-surface.css`. No change to card scale, gaps or columns elsewhere (U2).
5. Tests: `tests/hub/test_tv_posters.py` (TV markup asks 400, non-TV unchanged, Tonight hooks, macro flag, CSS rules). Hub suite green.

## Data
None. No snapshot, schema or migration change.

## Image cost (CLAUDE.md rule 7)
- Render makes no live call: `<img src="/img/<ref>?h=400">` is a URL only. `/img` (hub/images.py) serves a disk-cache hit (`IMG_CACHE_DIR`, 30 day TTL, key `ref|size`) and only on a miss fetches the upstream art once, stores it and serves it with `Cache-Control: public, max-age=2592000, immutable`. 400 is already an allowed size (`SIZES`), so no new route or env.
- Size: Jellyfin/Radarr art at 400 is about 2.5x the pixels of 240 (267x400 vs 160x240), typically roughly 25-45 KB vs 10-20 KB per JPEG (estimate, not measured here). A TV Overview (3 shelves, ~30 posters) is about 1 MB; a Movies grid page of ~100 cards about 3 MB, once, then browser-cached for 30 days.
- Cold cost: `media_warmup` pre-warms h=240 (and 600) only, so the first TV view of a poster is one cache-miss fetch from Jellyfin/the arr (same read the 240 path already does), then cached. Follow-up if wanted: warm h=400 for the library pass (more disk, more upstream reads); not done here.
- Desktop and phone never request 400 for these cards: no change to their bytes.

## Performance budget
Page render budget unchanged (template change adds one boolean per poster). Not measured here: the machine rule holds timing runs for the orchestrator.

## Out of scope
Card scale, gaps, columns (U2); Discover, Wrapped, Diary and title-page posters; warming h=400; the device probe fold-in beyond the check below.

## Accept checklist
On the TCL TV (one grouped TV run, with the other TV_UI items): `tv_ui_capture.py probe` with the poster probe (`tvq9`-style) on
1. Movies grid, Overview and Tonight: `naturalWidth >= rendered device px` for every visible poster (about 267 px files; 200 css px = 400 device px on Tonight).
2. Tonight: `outsideSafe 0` and `offscreen []`; the "Three for tonight" label is visible below the sub-tabs; "Deal again" is on screen and reachable with Right from card 3, Up from the cards reaches the sub-tab.
3. Desktop (1440) and phone (390) Tonight, grid and Overview look the same as before.

## Questions for B.
None.

## Shipped notes
