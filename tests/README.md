# tests/ — the cumulative suite

The growth law, verbatim from MASTER_PLAN "Testing & release gates" (binding, §2 rule 13):

> **Growth law (append-only):** a WP that changes code lands its tests in the same session.
> A bugfix session writes the failing regression test FIRST, then fixes until green — the test
> stays forever. A test is never deleted, weakened, or skipped without a dated DECISIONS.md
> line saying why.

Runner, dev machine (fixture-mode, no credentials, no network — must pass anywhere):

    python -m pytest -q tests/

On the box the same suite runs inside the freshly built images
(`docker compose build && docker compose run --rm hub python -m pytest -q tests/`) —
what is tested is exactly what ships. `deploy/deploy.sh` is the only path to production
and aborts on any failure.

| Dir | Owns |
|---|---|
| `tests/hub/` | shell, loader, tile states, owner semantics |
| `tests/connectors/` | envelope + per-feed schemas, fixture tests, read-only greps |
| `tests/money/` | importer, rules, golden month, plaintext-never-in-git guard |
| `tests/deploy/` | smoke.py and deploy-gate checks |

Media suites live in `tests/hub/` (`test_media_*.py`: shelves, discover, her view, backup, frame) and
`tests/connectors/` (`test_jellyfin.py`, `test_arr.py`).

Rail section + brand link (2026-10-06): `test_registry.py` covers `rail_section`; `test_apex_shell.py` covers Home-group rendering and the brand home link.

`tests/conftest.py` has an autouse fixture that points `MEDIA_DB_PATH`, `MEDIA_BACKUP_DIR` and `SNAPSHOT_DIR` at per-test temp paths and sets `PLAY_RECORDER=off` and `MEDIA_BACKUP=off`; without it the default `/data/...` resolves to `C:\data\...` on Windows and tests touch a real directory.

Hidden (parked) areas (2026-10-06): `test_hidden_areas.py` covers the registry `hidden` flag, rail / phone bar / hub row exclusion, `/a/<id>` still serving, the hub KPI order Media · Weather · Calendar with `kpis few` + `span2`, and the Calendar page dropping its Weather KPI tile. Pins reworded for this: `test_apex_hub.py` (visible areas only; money card gone), `test_apex_areas.py` (weather tile excluded where the band renders), `test_hub_hero.py` / `test_styling.py` (last card may carry `span2`), `test_owner_filter.py` (shared tile reads `money`, not `open_meteo`), `test_hub_reads_samples.py` (kitchen has no hub card).

Signed-in user (2026-10-06): `test_identity.py` covers `hub/identity.py` (Access header == `OWNER_EMAIL_YOU` ⇒ you, any other address ⇒ her, no header ⇒ not signed in, env display names), the header-forced owner view (query and cookie ignored, no cookie set), the rail footer + top-bar user chip, the greeting with and without a name, no Both/You/Her switcher on shell or Media pages, the brand reading just "Joey", and media.db writes landing as the signed-in owner. Only placeholder `example.com` addresses appear in tests. Pins reworded for this: `test_apex_shell.py` (rail shows "Not signed in"/"Local preview" and no `joeyhome.net`; greeting has no name without the header; brand has no `joeyhome.net`), `test_media_frame.py::test_switcher_links_to_current_media_path` and `::test_switcher_keeps_the_query_string` (no switcher links; the query still sets the view locally / the sections nav still lights), `test_owner_filter.py::test_switcher_links_render_plain_hrefs` (no switcher links; the plain query still filters).

MediaHub shell (2026-10-06, restyle Phase 2): the rail and theme toggle are gone — `test_apex_shell.py` was rewritten for the top bar (one pill per visible section), the phone tab bar (min(5, sections) items, More only above five, hidden areas absent), `_pagehead.html` on hub/area/server/weather/media_base, the single dark `:root` (no `prefers-color-scheme` / `[data-theme]` blocks, no literal colours outside `:root`) and 200s on the eight shell routes. Mentions of "rail", "rail footer" and "theme toggle" in the paragraphs above are historical. `test_style_foundation.py` (Phase 1) pins the token set, recipe classes and self-hosted Geist.

MediaHub restyle Phase 4 (2026-10-06): `test_style_pages.py` pins the final phase: (a) the Hub / area / Server / Weather templates and the stylesheet carry none of the superseded classes (`.card`, `.kpi*`, `.uplist/.uprow`, `.medialist`, `.appdot`, `.pbar`, `.hubshelf`, `.seeall`, `.badge.stale/.off`, `.poster.sm`, `.chip.score`, `.owner`, ...), `_tile.html` is gone; (b) no `accent` in templates, hub Python (registry validation excepted) or CSS; (c) `/`, `/a/calendar`, `/server`, `/weather` render stats strips / panels / rows with no literal colour; (d) `runtime_text` ("1h 52m", "47m", "2h", "—"); (e) the Server Update now / Ignore forms render as `.btn-primary` / `.btn-ghost`; (f) no fixed width over 360 px or `min-width` over the viewport outside media queries. Pins moved to the new classes (same behaviour asserted): `test_apex_hub.py`, `test_apex_areas.py`, `test_hidden_areas.py`, `test_hub_hero.py`, `test_styling.py`, `test_tiles.py`, `test_media_detail.py`, `test_media_shelves.py`, `test_media.py`, `test_media_history.py`, `test_media_library.py`, `test_media_backup.py`, `test_pwa.py` (bare links `--text-2`), `test_media_diary.py`, `test_media_frame.py` (no `accent` in `nav_context`), `test_weather.py`, `test_weather_radar.py`, `test_server.py`, `test_server_counts.py` (`<dt>/<dd>` rows), `test_server_updates.py`; the runtime pins in `test_media_discover/film/item/library_pages.py` now read "1h 52m" / "2h 16m" / "45m". Tile / row text is asserted with the " · " joins stripped (`txt()` helper) because they sit in `.sep` spans.

Media UX round 4 (media-ux4, 2026-10-08): new suites `test_media_ux4_posters.py` (one list poster size on TV / To rate /
Diary), `test_media_ux4_to_rate_tab.py` (To rate tab), `test_media_ux4_episode.py` + `test_media_ux4_episode_toggle.py`
(no "Episode of" line, one Play, the hero's watch state from the season list — regression first), `test_media_ux4_scores.py`
(score + site pills, logos, Metacritic bands), `test_media_ux4_omdb.py` (OMDb lookup, 7-day cache, daily cap, refused key,
sanitized logs; HTTP faked), `test_media_ux4_makers.py` (Directed by / Created by cards), `test_media_ux4_grid.py` (grid
default, Grid / List cookie) and `test_media_ux4_trailer.py` (word button, empty dialog, no iframe in the initial HTML).
`conftest.py` also unsets `OMDB_API_KEY`. Pins reworded for B.'s changes (same behaviour asserted where it still exists):
`test_media_to_rate_pages.py` (the To rate section moved to the tab pages), `test_media_frame.py` / `test_media_nav_ux2.py`
(four tabs), `test_media_watchlist.py` (the Watchlist link itself carries no count), `test_media_list_posters.py` (History's
Recently watched keeps 44 px; list rows read with `?view=list`), `test_media_item.py` / `test_media_film.py` ("Episode of"
gone — the banner links the show; scores as pills: "7.8" TMDB, "92%" RT; Trailer is a word button; "Created by"),
`test_media_resume.py` (an in-progress episode is in progress in the season list too), `test_film_quality.py`,
`test_media_discover.py`, `test_media_speed.py`, `test_style_media.py` (pills / site pills), `test_media_library_pages.py`
(row markup read with `?view=list`; the New this week strip ends at the toolbar).
