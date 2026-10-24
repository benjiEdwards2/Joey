# JY-114 Season state on Recently added + hub progress words

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/media_home.py` (Media home shelves), `hub/main.py` (the shelves route's BackgroundTask), `hub/templates/area_shelves.html` (the shelf card), `tests/hub/`
Needs: none
Options page: none: tiny change that follows an existing pattern (the My shows grid card's Sonarr line, `row-meta card-progress` in `_library_row.html`, and the existing season-state words)

## Problem
HITLIST row: "Rows have no episode count". From the WP-T1 gaps (archived BACKLOG, 2026-10-19): "'Recently added' rows and hub progress words carry no season state (no episode count on those rows)". My shows, the show page and Requests already say "5 to come · next airs 2 Nov" or "2 aired, not downloaded" from Sonarr; the Media home's poster shelves do not. Read here as the Media home (Overview, `/a/<shelves area>`): its Recently added shelf and the progress words on its Continue watching shelf ("4 left · ~3h 10m", E5).

## Acceptance criteria
1. On the Media home, a Recently added card for a show (a Jellyfin episode or series row, or a Sonarr arrival) whose show has episodes still to come or aired but not downloaded gets one more line under its "added" words: the show's season-state word, for example "5 to come · next airs 2 Nov" or "2 aired, not downloaded".
2. A Continue watching card for such a show keeps its progress words ("S2E5 · 31 min left · 4 left · ~3h 10m") and gets the same extra line.
3. The line is the grid card's existing recipe: `<span class="row-meta card-progress">` with `media_season_state`'s series word, shown on the same rule as My shows (`apply_season_state`: only while `to_come` or `missing`). A complete or up-to-date show, a film, a row Sonarr does not know, and every row without Sonarr or before its list is read look as before.
4. Rows map to the show without guessing: an episode row by its series (`jf:<SeriesId>` item key or `show_key`) through the library's show list, a series or arrival row by its own `tvdb:` / `tmdb:` key; the TheTVDB id comes from `_show_keys` (item key, else the cached item read). Never by title; a film's TMDB id is never looked up in Sonarr.
5. Cache-only on render (rule 7, read-only): the words come from `media_season_state.season_states` (no call). The page hands `media_season_state.later` its shows' keys as the response's BackgroundTask, so a stale series list is re-read after the render (one GET /api/v3/series, kept 10 min; no episode-list reads). No Sonarr: no task.
6. Tests: the card lines on a warm cache; nothing on a cold first render and no Sonarr call before the response; films and complete shows unchanged; no task without Sonarr.

## Data
No tables. Reads `media_season_state`'s cached series list; the Jellyfin snapshot's `shows` (and her `shows`) list to map an episode row's series id to its provider keys; `media_item.peek` through `_show_keys`.

## Performance budget
Media home (hub page render, warm p95 <= 50 ms). The change is a dict lookup per shelf row (at most 2 × 15 cards) over cached data, no I/O. Measured by the orchestrator's budget run.

## Options and the pick
None: follows the grid card's Sonarr line and the existing words.

## Out of scope
The hub page's own Media card and Recently watched band; the guest Overview; episode counts beyond Sonarr's words ("3 of 8 episodes"); episode-list reads from the Media home.

## Accept checklist
- Media home: a show with an episode due shows "N to come · next airs …" under its card in Recently added and Continue watching.
- A finished or up-to-date show, and films, look as before.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #123, squash-merged as `d65ad7f` (d65ad7fd1680c6e246cf56c46704934cb6234de6).
- Deploy: `2026-10-24T09:31:55Z PASS prev=d9284ec new=d65ad7f suite green, smoke ok tv=current end=2026-10-24T09:37:00Z dur=305s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
