# JY-194 U8 Discover search on the TV

Status: building
Size: M
Live risk: none
Area: `hub/templates/media_discover_guest.html`, `hub/templates/_guest_discover_grid.html` (one `data-q` attribute), `hub/static/tv.css`, `hub/static/tv.js`, `tests/hub/test_tv_mode.py`
Needs: JY-187 (merged, `35c5217`): the focus rules here sit on its `remember` / `recall` / `first()` / `restore()`
Options page: none: the design is the signed tv-v2 shell `Desktop\Claude\JoeyTV\mockups\tv-v2\04-discover.html` (screens 1 to 3, PNGs `04-discover-search-focus`, `-keyboard`, `-results`).

Source: `Desktop\Claude\JoeyTV\TV_UI_PLAN.md` row U8; finding R2 in `Desktop\Claude\JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md`.

## Problem
R2: on the TV, `html.tv form.toolbar { display: none }` hides the Discover search box, so a friend can only request what the trending grid happens to show. Android TV shows its on-screen keyboard for a focused `<input>`, so a TV search field is feasible.

## Acceptance criteria
1. **Field shown.** On the friends' Discover page in TV mode the search field is shown as a full-width 56 px pill above the grid (shell 04 screen 1: magnifier, "Search films and TV", 21 px). Every other `form.toolbar` stays hidden in TV mode.
2. **First stop above the grid.** First focus on load is unchanged (the first poster, or the JY-187 remembered link). Up from any poster in the grid's first row lands on the field, not the top bar. Up from the field lands on the Discover pill (JY-187 B2/B3). Down from the field lands on the first poster.
3. **OK opens the keyboard.** In TV mode the field is read-only while it is only focused, so moving past it never raises the keyboard. OK (Enter) on it makes it editable and refocuses it, which raises the Android TV keyboard. Leaving the field makes it read-only again.
4. **Typing swaps the results.** Typing uses the field's existing trigger (`keyup changed delay:400ms`) and the existing endpoint `/media/discover/search`, which swaps `#discover-grid` (label "Results · n"). OK / Enter in the editable field does not submit the form: it fires the field's existing `search` trigger only when the grid does not already show that query (`#discover-grid[data-q]`), then moves focus to the first poster (the first result once the swap lands). No new endpoint, no per-keystroke call: at most one call per typing pause, plus none or one on Enter.
5. **Back returns to trending.** With no dialog open and a query in the field or the grid, `window.joeyTV.back()` clears the field, fires its `search` trigger with an empty query (the cached trending shelves, `CACHE_TTL`), focuses the field and returns true. An open request panel is still closed first. With no query, Back behaves as before (false: the shell goes back).
6. **Friends only.** The household Discover page (`media_discover.html`) and its routes are unchanged. Outside TV mode the friends' page behaves as before (the new attributes are inert; no `tv.js` there).
7. Tests: each rule red on the old `tv.js` / markup and green after, in the JY-187 node fake-DOM harness (skips without node), plus gate-run markup and CSS tests. No existing test weakened.
8. **One request per query** (review should-fix, 2026-10-25). Typing fast and pressing Enter within the 400 ms debounce fired Enter's search, then the pending keyup request sent the same query again. `tv.js` cancels (`htmx:beforeRequest`) a keyup request from the field for the query Enter sent or the grid already shows; `search` requests and new queries still go out.

Red-first check (2026-10-25): the four JY-194 node tests, run against origin/main's `tv.js` (`5a0c746`, same `tv.js` as `35c5217`) in a scratch copy (`git archive` + this branch's test file): 4 failed, the 5 JY-187 node tests passed. On this branch: `tests/hub/test_tv_mode.py` 29 passed.

## Data
None. Client-side only; reads `/media/discover/search` as today.

## Performance budget
Discover page <= 3 s, never blocks: unchanged (the page build is untouched; Back to trending reads the shelf cache).

## Options and the pick
None: the shell's screens 1 to 3 are the design (no options in the shell).

## Out of scope
The "OK to type / OK to edit" hint text from the shell (the placeholder carries the words), a "Trending" label (R1 kept "Discover · n"), search-result caching on the server (search was never cached; the debounce limits calls), pushing `?q=` into history, the household Discover, any shell (`tv/`) change.

## Accept checklist
Device journey in the grouped TV session (orchestrator, `JoeyTV\scripts\tv_ui_capture.py`): on Discover, Up from the first poster focuses the field (ring on the pill) → OK raises the keyboard → `adb shell input text apothecary` (or `input keyevent` letters) → "Results · n" grid replaces trending → Enter / Done moves focus to the first result → Back → trending grid with the field focused → Back again leaves Discover.

## Questions for B.
None open.

## Shipped notes
