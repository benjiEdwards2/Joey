# JY-302 Bug: Requests "search missing / upgrades" adds off-server titles to Jellyfin

Status: shipped (#299, live bf94e98, 2026-11-03)
Size: M
Live risk: arr write (Radarr / Sonarr search commands; the optional clean-up would also edit arr monitoring)
Area: `hub/media_arr_search.py`, `hub/templates/_arr_sweep.html`, `tests/hub/test_media_arr_sweep.py` (+ a read of the `arr` snapshot / Jellyfin library ids)
Needs: none. JY-275 (upgrade UI) and JY-300 (merged page) build on this, not the other way round.
Options page: none (bug fix; the upgrade flag/button design lives under JY-275)

Live risk is not `none`, so this is reviewed as L (see `docs/PROCESS.md`).

## Problem
B., 2026-11-02: "Requests search missing function needs a full rework. When I search for missing or upgrades, it will
process all films or shows even if they are not on the server and add them to Jellyfin. I need this to stop and only
films or shows on there to actually be shown on Jellyfin." Bug first; the "full rework" waits (JY-300).

## Findings
Code path (Activity › Requests / › Downloads, `_arr_sweep.html`):
- `hub/media_arr_search.py:226-227` `SWEEPS` maps the two buttons to the arr's **library-wide** commands:
  missing → Radarr `MissingMoviesSearch`, Sonarr `MissingEpisodeSearch`; upgrades → Radarr `CutoffUnmetMoviesSearch`,
  Sonarr `CutoffUnmetEpisodeSearch`.
- `_sweep_one` (`:249-258`) posts `{"name": SWEEPS[kind][app]}` with **no id list**; `sweep_now` (`:301-316`) runs it for
  both apps in parallel. The confirm text says so: "Search every monitored title that has no file yet?" (`:228`).
- Tests pin this: `tests/hub/test_media_arr_sweep.py:149` `test_post_sends_exactly_the_two_commands`.

Root cause: Joey passes no scope, so Radarr/Sonarr search **every monitored item in the arr**, including titles that
were added/monitored but never downloaded (old Seerr requests, list imports, monitored future seasons). Any release the
arr grabs is imported into the library folder, Jellyfin scans it, and an off-server title appears. So the defect is
Joey's call (wrong scope), made visible by arr state Joey did not create; fixing the call is enough to stop new adds.

Upgrades today: the "below cutoff" hint is `hub/templates/_upgrade_note.html` (light-blue `.upnote`), text from
`hub/media_upgrades.py:39-44`, e.g. "Below cutoff · WEBDL-720p → wants Bluray-1080p". It comes from the arr snapshot's
`data.upgrades` (cutoff unmet), which means "the profile wants better", **not** "a better release exists"
(`media_upgrades.py:4-5` says this). Joey has no data today that proves an upgrade is available; that needs a
per-title release lookup (Radarr `GET /release?movieId=`, Sonarr `GET /release?seriesId=`) and is JY-275's job. The
per-title "Search for upgrade" button (`:347-372`, `MoviesSearch` / `SeriesSearch` on one id) is already scoped and safe.

Clean-up: needed only if B. wants titles already pulled in by past sweeps removed. Joey can list them read-only as
"arr items with a file whose import date is on/after a sweep and that were never requested in Joey/Seerr", or more
simply via arr history (`eventType=grabbed`) since the first sweep (F3, 2026-10-12). See Q2.

## Acceptance criteria
1. A regression test first reproduces today: posting `kind=missing` sends a body with no ids (`MissingMoviesSearch`).
   It must fail after the fix.
2. "Search missing" sends Radarr `MoviesSearch` with `movieIds` and Sonarr `EpisodeSearch`/`SeriesSearch` with ids
   drawn **only** from titles present on Jellyfin (matched by tmdb / tvdb from the Jellyfin snapshot), and only those
   with something missing (Sonarr: missing episodes of a show on Jellyfin).
3. "Search upgrades" sends ids only for cutoff-unmet titles that are also on Jellyfin.
4. A monitored-only arr title (in the arr, not on Jellyfin) is never in any id list Joey sends (test with a fixture
   holding one such film and one such show).
5. The library-wide command names (`MissingMoviesSearch`, `MissingEpisodeSearch`, `CutoffUnmet*Search`) no longer
   appear in `hub/` (grep test).
6. Empty id list for an app → no command sent for that app; flash says "Nothing to search" rather than "started".
7. Confirm text names the scope and count: "Search 4 films and 2 shows on Jellyfin that are missing files?".
8. Existing sweep tests (throttle, same-origin, one-app-down, stuck app, back URL) still pass, updated for id bodies.
9. No arr monitoring is changed by the fix itself (clean-up, if any, is a separate gated step per Q2).

## Data
Reads: `arr` snapshot (`data.upgrades`, arr ids ↔ tmdb/tvdb), Jellyfin library snapshot (tmdb/tvdb provider ids).
If the snapshot lacks arr "missing" rows, add them to `connectors/feeds/arr.py` (Radarr `wanted/missing`, Sonarr
`wanted/missing`, paged). No DB tables or migrations.

## Performance budget
POST stays inside the existing 10 s per app (`SWEEP_TIMEOUT`); id lists are built from snapshots, no extra live
calls on page render. Confirm card render: hub fragment budget from `CLAUDE.md`, measured in the test client.

## Options and the pick
None needed for the fix. Upgrade flag + button design: JY-275 options page.

## Out of scope
- JY-275: blue "upgrade available" flag + Upgrade button, hiding the below-cutoff line, release lookups.
- JY-300: merging Upgrades and Requests into one page; the "full rework".
- Unmonitoring or deleting arr items (only via Q2, as its own gated step).

## Accept checklist
- On the preview, "Search missing" confirm shows a count that matches titles on Jellyfin with missing files.
- Run it; Radarr/Sonarr Activity › Queue shows only titles already on Jellyfin; no new title appears in Jellyfin
  over the next day.
- "Search upgrades" likewise touches only on-server titles.

## Questions for B.
1. What "missing" means for shows.
   A (recommended): missing episodes of shows already on Jellyfin get searched; shows not on Jellyfin never.
   B: films only; shows are skipped by "Search missing".
2. Titles already pulled in by past sweeps.
   A (recommended): Joey lists them once (read-only, from arr history since 2026-10-12) for you to tick; deletion is a
   separate gated item.
   B: leave them; just stop new ones.
   C: unmonitor every arr item not on Jellyfin (stops any future arr-side search too; arr write, one-off script).
3. Keep "Search upgrades" button until JY-275 lands?
   A (recommended): keep it, scoped to on-server titles.
   B: hide it now; JY-275 brings upgrades back as per-title buttons.

## Shipped notes

## Shipped notes (2026-11-03)

Merged #299 on B.'s accept (B. 2026-11-03: "accept all, except 293 does not need 'everything else"), one deploy, live bf94e98.
