# JY-303 phase 2 — Discover: browse by genre and related-topic chips

Status: on sweep (PR #338 4f212dd, reviewer PASS; Sweep 39 2026-11-07)
Size: M
Area: `hub/media_discover.py`, Discover templates (`media_discover.html`, `media_discover_all.html`, `_discover_*.html`, guest Discover templates), `hub/static/control-surface.css`, `hub/static/tv.css`, `hub/static/tv.js` (focus only), `tests/hub`. NOT the title-page templates (`media_film.html`, `_film_*.html`): JY-285 owns those right now; the film-page genre links and Similar/Recommended "See all" are phase 2b, later.

## Problem
Phase 1 (#333, live 1c8b37e) gave every shelf a "See all" grid with filters and Load more. B.'s ask was also to "go into similar topics like I can on Seerr". Today the only way to a genre is the Genre picker inside the grid's filter bar; there are no topic entry points on Discover itself.

## Change
1. **Browse by genre** on Discover (web, phone, TV; owner and friends): a "Browse" section under the shelves with two rows of tiles, Films and TV, one tile per TMDB genre (names from Seerr's genre lists, the same source phase 1's Genre picker uses, cached as it is). A tile opens the phase 1 grid `GET /media/discover/all` with `type` and `genre` preset and Sort = Popular. Tiles are text pills on web (wrapping rows); on the TV a focusable row per medium, Left/Right across, Down between rows, text at the 18 px floor.
2. **Genre page** = the phase 1 grid with the genre name as the heading ("Action films", "Drama TV") when the request carries a single genre; the filter bar keeps working. No new route.
3. **Related topics**: on the grid page, when the result set comes from a shelf or genre preset, a chip row under the heading "Related topics" with up to 8 TMDB keywords gathered from the first page's titles (keyword counts across the page, most frequent first; one Seerr/TMDB keywords read per title, cached 24 h, loaded after the grid draws with the phase 1 deferred pattern and a 12 s deadline; row hidden when empty or Seerr is down). A chip opens the grid filtered by that keyword (`keyword=<id>`, Seerr discover supports `keywords`); the chip row then shows the active keyword with a clear (x).
4. Friends' Discover (web + TV) gets the same Browse section and the same grid behaviour with their request chips; no new allow-list row beyond what `keyword=` on the existing grid route needs.
5. Seerr down: Browse section hidden, grid shows the phase 1 "Discover unavailable" state. Never a 500.

## Tests
- Browse section renders both rows from the cached genre lists; tile hrefs carry type + genre + sort; hidden when the genre lists are empty.
- Grid heading reads "<Genre> films" / "<Genre> TV" for a single-genre request; unchanged otherwise.
- Keyword row: deferred endpoint aggregates keywords over the page, caps at 8, excludes nothing but duplicates; empty / down → empty 200; `keyword=` filters the Seerr call; active chip + clear present.
- Friends: Browse present on their Discover (web + TV); keyword grid shows request chips.
- TV: focus order Browse rows after the last shelf; tv.css pins for any new rule.
- Full tree green: `python -m pytest tests -n 4 -p no:cacheprovider -q 2>&1 | tail -3`.

## Out of scope (phase 2b, after JY-285 lands)
Film-page genres and keywords as links; "See all" on the film page's Similar / Recommended shelves; studios & networks; See all on search results.

## Done
PR on `jy-303-p2-browse` from main; reviewer PASS with shots: Discover with the Browse section (1440, 390, TV 1920 with a tile focused), a genre grid page, the Related topics row and a keyword-filtered grid, friends' TV Browse row.
