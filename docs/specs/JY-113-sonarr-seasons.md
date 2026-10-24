# JY-113 Sonarr-only seasons get no Seasons row

Status: building
Size: S
Live risk: none
Area: `hub/media_season_state.py`, `hub/media_film.py` (the show page's Seasons data), `hub/templates/media_film.html` (the Seasons section), `tests/hub/`
Needs: none
Options page: none: tiny change that follows an existing pattern (the Seasons row's own row recipe and the existing season-state words)

## Problem
HITLIST row, 2026-10-23: "Only a 'Season N announced' word". A show on the server whose next season exists only in Sonarr (announced, or monitored with no episode yet) says "Season 3 announced" at the end of the status line, but the Seasons section lists only the seasons Jellyfin has. The season Sonarr knows of has no row.

## Acceptance criteria
1. On a show page with a Jellyfin Seasons section, each Sonarr season newer than the last Jellyfin season, with no file in Sonarr, that is either Sonarr's placeholder ("announced") or monitored, gets one row at the end of the same Seasons list.
2. The row uses the Seasons row's existing recipe (`.row` > `.row-body` > `.row-title`, the `seasoncount` and `seasonstate` spans) and existing words: "Season 5 · Not on server yet · Announced" (" · airs 5 Dec" when Sonarr has a date), or "Season 6 · Not on server yet · Waiting for the first episode · airs 5 Dec" (Sonarr's season word). It is a plain row, not a `<details>`: there are no episodes to open, so it carries no "+".
3. Not shown: older seasons missing from Jellyfin (library gaps), seasons Sonarr has files of (Jellyfin has not scanned yet), unmonitored seasons that are not placeholders, specials (season 0). Without Sonarr, or before its list is read, the page is unchanged.
4. Read-only on Sonarr (rule 7): the rows come from `media_season_state`'s cached series list (`season_states`, already read for the status line). No new upstream call; nothing before the render.
5. Tests: the pure selection and words; a show page with Sonarr S5 announced and S6 waiting draws both rows after Season 4, inside the Seasons section of `<main>`; an unmonitored aired season and an older gap draw none.

## Data
No tables. Reads `media_season_state`'s in-memory Sonarr series list (GET /api/v3/series, kept 10 min, read in the BackgroundTask after a page render). The season entry's `monitored` flag is now kept in `build()`'s per-season dict.

## Performance budget
Media item page, warm p95 <= 150 ms. The change is a loop over a show's cached seasons (a handful of dicts), no I/O. Measured by the orchestrator's budget run.

## Options and the pick
None: follows the existing Seasons row and words.

## Out of scope
A show Jellyfin has no season of (an empty series, or the off-server title page): it keeps Seerr's season rows or none. Older seasons missing from the library. Episode rows under a Sonarr-only season.

## Accept checklist
- Open a show whose next season is announced in Sonarr: the Seasons list ends with "Season N · Not on server yet · Announced".
- A show with nothing new in Sonarr looks as before.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
