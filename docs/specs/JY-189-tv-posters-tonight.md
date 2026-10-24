# JY-189 TV posters at 600 px and the Tonight TV layout

Status: shipped 2026-10-25
Size: M
Live risk: none
Area: hub/templates (_poster, _shelf, _library_row, _library_page, area_shelves, media_tonight), hub/static/tv.css, tests/hub
Needs: none (U2, the card scale, gaps and columns, is separate and waits for B.'s scale pick)
Options page: none: shell 02 of `JoeyTV\mockups\tv-v2` (`02-library.html`, screen "Tonight") is the design; plan row U3 in `JoeyTV\TV_UI_PLAN.md`

## Problem
TV_UI_EVALUATION G2: the grid and Overview shelves fetch `h=240` (160x240 files) and draw them at 260-277 x 392-416 device px, so posters are soft from the couch. T1/T2: on Tonight the three cards are drawn at 560-594 device px from the same 160x240 file, the "Three for tonight" label hides under the sticky sub-tabs, the cards run off the bottom and "Deal again" is clipped.

## Acceptance criteria
1. `poster()` takes a `tv` flag; when true it fetches `h=600`. Callers pass `tv_mode(request)`: Overview shelves (`area_shelves.html`), the Movies / TV grid cards and the Suggestions carousel (`_library_page.html`, `_library_row.html` `card`), the hub shelf macro (`_shelf.html`, flag only), and Tonight.
2. Outside TV mode every poster URL is as before (`h=240`). The markup is not byte-identical: Tonight gains the inert classes `sec tn` and `tn-deal`, which only `html.tv` rules style. Small row thumbnails (`h=120`, list rows) never change.
3. Tonight: `<section class="sec tn">`, the cards in `.poster-grid.big`, "Deal again" in `.tn-deal`.
4. `tv.css` (TV mode only, `html.tv`): three 200 px cards centred, 40 px gap, "Deal again" beside them in the same row, no focus scale on these cards (ring only), label first in the body. Nothing is added to `control-surface.css`. No change to card scale, gaps or columns elsewhere (U2).
5. Tests: `tests/hub/test_tv_posters.py` (TV markup asks 600, non-TV unchanged, Tonight hooks, macro flag, CSS rules). Hub suite green.

## Data
None. No snapshot, schema or migration change.

## Image cost (CLAUDE.md rule 7)
- 2026-10-25, review: the flag fetches h=600, not 400 - reuse the warm 600 cache; 267 device px shown. `media_warmup` already warms h=600 (POSTER_H) for every library title, so a first TV view is a disk-cache hit.
- Render makes no live call: `<img src="/img/<ref>?h=600">` is a URL only. `/img` (hub/images.py) serves the disk cache (`IMG_CACHE_DIR`, 30 day TTL, key `ref|size`, `Cache-Control: public, max-age=2592000, immutable`). 600 is an allowed size (`SIZES`); no new route or env.
- Size: a 600 poster (400x600, TMDB w780 / Jellyfin full) is about 6x the pixels of 240 and about 2.25x of 400, roughly 40-80 KB per JPEG (estimate, not measured). A TV Overview (~30 posters) is about 2 MB; a Movies grid page of ~100 cards about 5-6 MB, once, then browser-cached 30 days. It is more bytes on the LAN than 400 would be, in exchange for no cold fetch and no new warm-up.
- Titles outside the warm-up set (Suggestions, shelves from other snapshots) still cost one cached upstream fetch on first view.
- Desktop and phone never request 600 for these cards.

## Performance budget
Page render budget unchanged (template change adds one boolean per poster). Not measured here: the machine rule holds timing runs for the orchestrator.

## Out of scope
Card scale, gaps, columns (U2); Discover, Wrapped, Diary and title-page posters; warming extra sizes; the device probe fold-in beyond the check below.

## Accept checklist
On the TCL TV (one grouped TV run, with the other TV_UI items): `tv_ui_capture.py probe` with the poster probe (`tvq9`-style) on
1. Movies grid, Overview and Tonight: `naturalWidth >= rendered device px` for every visible poster (400x600 files; Tonight cards draw at 200 css px = 400 device px).
2. Tonight: `outsideSafe 0` and `offscreen []`; the "Three for tonight" label is visible below the sub-tabs; "Deal again" is on screen and reachable with Right from card 3, Up from the cards reaches the sub-tab.
3. Desktop (1440) and phone (390) Tonight, grid and Overview look the same as before.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #148, squash-merged as `81524f3` (81524f35e33be0daff20dae52d0b3d0dbac0a128).
- Deploy: `2026-10-24T22:07:39Z PASS prev=dfaf871 new=81524f3 suite green, smoke ok tv=current gate=-n2 avail=1944 end=2026-10-24T22:14:52Z dur=433s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
