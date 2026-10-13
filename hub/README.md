# hub

The Joey web app: FastAPI + Jinja + HTMX, one container (`joey-hub`, port 8000). It is the READ side of the connector
contract (it never fetches a feed itself, with the numbered live-call exceptions in `docs/connector-contract.md`) plus
a small write side kept in one SQLite file (`media.db`: ratings, diary, watchlist, follows, awards, plays, server
history). Areas are config, not code: `config/areas.yaml` drives the top bar, hub tiles and `/a/<id>` pages. The dated
history of how each part got its shape is in `docs/hub-changelog.md`; the look is `docs/style-guide.md`.

## Module map

| Module | Owns |
|---|---|
| `main.py` | App creation, middleware, `/static` mount, router includes, Hub page (`/`), Area pages (`/a/{id}`, `/server`), `/healthz`, `/whoami`; re-exports the moved names so old `hub.main.X` paths keep working |
| `shell.py` | What every router imports instead of `hub.main`: THE one `Jinja2Templates` instance and its globals (`static_v`, `weather_place()`, `img_letters`, `identity`), the registry holder (`load_areas`, `registry`), `get_snapshots` (once per request), the owner view, `build_status`, `find_detail_source`, `render_page` / `not_found_page` (the one base context and 404), `ShellMiddleware` (Cache-Control + request log), `Compress` (gzip) |
| `tasks.py` | The app lifespan (loads the registry) and the background loops, all through `_every` |
| `weather.py`, `upcoming.py` | Weather glimpse, `/weather` forecast + Windy radar embed; the Next 7 days list and hub card |
| `media_home.py` | Shared Media helpers: one ratings read (`_ratings`, `score_for`), `view_jelly`, Media home shelves, rating inbox and waiting counts, the Media frame (`media_nav`), the hub's Media card |
| `media_pages.py` | The `/media/*` detail pages behind registry tiles (`_detail_page`): Live, Library, Downloads, Requests, Health, To rate, Diary, Movies / TV grid, Tonight |
| `ids.py` | Snapshot ids, `home_tz()` / `home_now()` (Australia/Melbourne), `areas_path()` |
| `store.py` | Snapshot reader: parse once per `(mtime_ns, size)`, `connected()`, `parse_utc()`, `ago_text()` |
| `registry.py`, `identity.py` | `areas.yaml` loader (fails fast, lists every violation); who is signed in (Cloudflare Access header) |
| `images.py` | `GET /img/{ref}` poster proxy with a 30-day disk cache and generated fallback cards |
| `server.py`, `server_updates.py`, `server_stack.py`, `server_alerts.py`, `server_history.py` | Server area bands; Update now / Update all / Ignore (live What's Up Docker call); Restart + update media stack (live stackctl call); Discord push of new Attention items; 24 h health history |
| `media_nav.py`, `media_library.py`, `media_downloads.py`, `media_files.py`, `media_rank.py`, `media_upgrades.py` | Media section map; library list helpers; downloads join; file-quality strip; library rank; Upgrade available (arr cutoff unmet) |
| `media_film.py`, `media_item.py`, `media_person.py`, `media_omdb.py`, `media_arr_search.py` | The Cinema film page, item data, person pages, Metacritic pill, Search now |
| `media_discover.py`, `media_follow.py`, `media_requests.py`, `media_watchlist*.py` | Discover and request, Follow, Remove request, watchlist |
| `media_db.py`, `media_write.py`, `media_plays*.py`, `media_resume.py`, `media_hidden.py` | media.db schema, rate / log / search routes, play recorder and History, resume actions, hide-until-next-sweep |
| `media_awards*.py` | Awards: sync, parsers, seeds, store, pages, badges and icons |
| `media_warmup.py`, `media_backup.py` | Film-page cache warm-up; nightly media.db backups |
| `seed_demo.py` | Writes demo snapshots for local runs |

Templates are in `templates/` (`base.html` is the frame; `media_*.html` and `_*.html` partials), assets in `static/`
(`static/joey.js` is the frame's script: boost guard, history replace, flash strip, pinch guard, docked Media row).
Routers are included in `main.py`; every write route carries `Depends(same_origin)` (403 unless htmx or same Origin).

## Routes

| Route | Module | Notes |
|---|---|---|
| `GET /` | main | Hub: summary tiles, Next 7 days, weather glimpse, Recently watched |
| `GET /a/{area_id}` | main | Area page (`layout` grid, shelves or server; grid = tiles + Next 7 days, its Media sections removed 2026-10-09, decision 2); hidden areas still serve |
| `GET /server` | main | Server area (same page as `/a/server`) |
| `GET /weather` | weather | Weather page (Windy radar embed; the parked BOM radar was removed 2026-10-09, decision 5) |
| `GET /media/playing`, `/history`, `/library`, `/downloads`, `/requests`, `/apps` | media_pages | Media Activity section (was "Server", renamed 2026-10-09, decision 4): Live, To rate (`/media/history`), Library, Downloads, Requests, Health |
| `GET /media/diary` | media_pages | Activity > History: the watch diary (the Diary section folded into Activity 2026-10-13; By-year rankings removed 2026-10-09, decision 1) |
| `GET /media/{movies,tv}`, `/tonight`, `/to-rate`, `/watchlist`, `/awards` | main, watchlist, awards_pages | Library (grid / list), To rate, Awards tabs; Tonight and Watchlist serve by URL with no tab (2026-10-13) |
| `GET /media/server/history` | media_plays | Play stats: plays recorded from Jellyfin sessions (no tab since 2026-10-13; linked from the diary) |
| `GET /media/discover`, `/discover/search`, `/discover/service/{provider_id}`, `/media/following` | media_discover, media_follow | Discover shelves, search box, a streaming service's shelves, Following |
| `GET /media/search` | media_write | Title search behind the Log form |
| `GET /media/title/{kind}/{tmdb_id}`, `/media/item/{jf_id}`, `/media/person/{person_id}` | media_film, media_person | Film / series page by TMDB id or Jellyfin id; person page |
| `GET /media/title/{kind}/{tmdb_id}/part/{name}`, `/media/item/{jf_id}/part/{name}` | media_film | The film page's deferred sections (`all?p=…` = every pending one, out-of-band swaps) |
| `GET /media/title/{kind}/{tmdb_id}/request`, `/arr`; `/media/title/tv/{tmdb_id}/season/{n}` | media_discover, media_arr_search | Request form, Radarr / Sonarr search form, season list |
| `POST /media/title/{kind}/{tmdb_id}/request`, `/search` | media_discover, media_arr_search | Jellyseerr request; Search now (Radarr / Sonarr command) |
| `GET/POST /media/arr/sweep` | media_arr_search | Search missing / Search upgrades across Radarr + Sonarr (GET `?step=confirm` = the inline confirm card) |
| `POST /media/title/{kind}/{tmdb_id}/upgrade` | media_arr_search, media_upgrades | Search for upgrade: the title's Radarr `MoviesSearch` / Sonarr `SeriesSearch` (the button sits in the `/arr` fragment) |
| `POST /media/rate`, `/media/rate/{key}/delete`, `DELETE /media/rate/{key}`, `POST /media/log` | media_write | Rate, un-rate, log a watch |
| `POST /media/settings/rating_level` | media_write | Rating scale |
| `POST /media/watchlist/{add,remove}` | media_watchlist | Watchlist |
| `POST /media/follow/{kind}/{tmdb_id}[/unfollow]` | media_follow | Follow a person, a film series or a show (`kind` person / collection / show) |
| `POST /media/requests/{rid}/remove` | media_requests | Remove a Jellyseerr request |
| `POST /media/resume/{jf_id}/{watched,unwatched,reset,hide}` | media_resume | Move on from Continue watching |
| `GET/POST /server/updates/{name}/run`, `POST .../ignore`, `.../unignore` | server_updates | Update now (GET = confirm page), Ignore |
| `GET/POST /server/updates/all/run` | server_updates | Update all: every eligible pending row in turn, gluetun first (GET `?step=confirm` = the list) |
| `GET/POST /server/stack/run` | server_stack | Restart + update media stack through stackctl (GET `?step=confirm` = what happens) |
| `GET /img/{ref:path}` | images | Poster / backdrop / cast proxy, sizes 120 / 240 / 400 / 600 / 1280 |
| `GET /healthz`, `/whoami` | main | Health JSON (container healthcheck, `deploy.sh` smoke); the Access email or `-` |
| `/static/*` | StaticFiles | `?v=` content hash: `immutable` for a year; un-versioned: one hour |

## Environment (all read by the hub; secrets live in the NAS `deploy/.env`, see `deploy/.env.example`)

| Variable | Default | Does |
|---|---|---|
| `SNAPSHOT_DIR` | `/data/snapshots` | Where connector envelopes are read |
| `MEDIA_DB_PATH` / `MEDIA_BACKUP_DIR` | `/data/sqlite/media.db` / `/data/backups/media` | media.db and its gzip backups |
| `IMG_CACHE_DIR` / `META_CACHE_DIR` | `/data/cache/img` / `<IMG_CACHE_DIR>/meta` | Poster cache; 6 h Jellyseerr / title meta cache |
| `AREAS_PATH` | `config/areas.yaml` | Registry file |
| `OWNER_EMAIL_YOU`, `OWNER_NAME_YOU`, `OWNER_NAME_HER` | unset, Benji, Georgina | Access email that is "you" (any other is "her"); chip and greeting names |
| `WEATHER_LAT`, `WEATHER_LON`, `WEATHER_PLACE` | Windy radar falls back to Newport, `Newport VIC` | Windy radar centre (the weather connector reads the same pair) and the place name in weather labels |
| `HUB_DEV` | off | `1` re-reads templates on every render (local template editing) |
| `JELLYFIN_URL`, `_API_KEY`, `_USER`, `JELLYFIN_USER_HER` | unset | Live item reads, play recorder, her profile |
| `JELLYSEERR_*`, `RADARR_*`, `SONARR_*` (`_URL`, `_API_KEY`), `OMDB_API_KEY` | unset | Requests, Search now, Request remove; Metacritic pill (7-day cache, 800 calls a day) |
| `WUD_URL`, `WUD_USER`, `WUD_PASS`, `SERVER_DISCORD_WEBHOOK` | unset | Update now / Ignore; Attention push |
| `STACKCTL_URL`, `STACKCTL_TOKEN` | unset | Restart + update media stack and its status line (`stackctl/NAS_INSTALL.md`); unset = button hidden, "Not connected" |
| `MEDIA_BACKUP`, `PLAY_RECORDER`, `MEDIA_WARMUP`, `MEDIA_FOLLOW`, `MEDIA_AWARDS` | on | `off` stops that background job (`MEDIA_WARMUP=shelves` keeps only the shelf pass) |
| `PLAY_POLL_SECONDS`, `AWARDS_CONTACT` | 60, unset | Recorder poll; awards sync makes no call without a contact |

## Background loops (started in `tasks.lifespan` through `_every(label, first_s, every_s, fn)`; errors log by type only)

| Loop | First run | Every |
|---|---|---|
| media.db backup (`media_backup`) | 30 s | 1 h (skips while a backup under 20 h old exists) |
| Play recorder (`media_plays`) | 15 s | `PLAY_POLL_SECONDS` |
| Server alerts + history sample (`_server_tick`) | 60 s | 5 min |
| Film warm-up (`media_warmup`) | 60 s | 3 h (full-library pass at most once per 24 h) |
| Follow (`media_follow`) | 2 min | 6 h |
| Awards (`media_awards`) | 3 min | hourly check, a pass only when one is due |

`scripts/awards_sync.py` is the manual CLI for the same awards code path (it calls `media_awards._insert_new` directly).
The connectors run in their own container: Media / Server feeds every 2 min, everything else hourly (`deploy/docker-compose.yml`).

## Caches

Snapshots: parsed once per `(mtime_ns, size)`, read once per request (`request.state.snaps`). Hub Server card: 60 s.
Discover lists: 10 min; Jellyseerr meta (bodies, ratings, season lists): 6 h in memory and on disk; providers 24 h.
Posters: 30 days on disk. HTML pages are `no-store` so Back and Forward never show a stale page.

**Film pages render first, upstream sections after (F2, 2026-10-12).** `media_film.build_film(..., defer=True)` (the
routes) never waits on Jellyseerr or OMDb: it renders from Jellyfin + the caches (`peek_extras`), and each section whose
answer is not cached is in `film.pending` — drawn by `_film_wait.html` as a `<div class="fpart" id="fp-<name>">`
(display: contents) holding the Jellyfin fallback or "Loading". ONE element (`.fpart-load`, `hx-trigger="load"`,
`hx-swap="none"`) asks `GET /media/{item/{jf_id}|title/{kind}/{tmdb}}/part/all?p=<names>`; `build_parts` answers with
each part wrapped in its placeholder's id and `hx-swap-oob="true"`. Parts are `media_film.PARTS` (makers, actions,
scores, collection, crew, dates, cast, providers, shelves), each one template `_film_<name>.html` that the page includes
inline when cached; `/part/<name>` serves one. The upstream read runs in a bounded background pool (`warm_extras`, one
job per title, started as soon as the TMDB id is known); part requests wait for it (`EXTRAS_WAIT`) and never read
Jellyfin (`media_item.peek`). Scripts and tests calling `build_film` without `defer` get the whole page, waiting as
before. **Prefetch:** `static/joey.js` sends `X-Joey-Prefetch: 1` to a film / show link on touch or a 60 ms hover (once
per link, one at a time); the route runs the reads and answers 204 with no body, no cookie and a log line without the
path.

## Decisions pinned by tests

**No zoom (media-ux5, B.'s explicit choice 2026-10-09):** Joey cannot be pinch- or focus-zoomed on a phone (viewport
`maximum-scale=1`, 16 px inputs, Safari gesture events cancelled in `static/joey.js`). The accessibility trade-off (WCAG 1.4.4)
is accepted for this private two-person app; undo by restoring the old viewport meta and removing the gesture guard.

**Follow shows + show creators (F5, 2026-10-12):** `media_follow.py`. A show page (not an episode) carries one line under
the hero's makers (`_follow_show.html` via the `follow_show(request, film)` global — a media.db read, no upstream call):
"Follow show" keeps it monitored in Sonarr with every new season (`monitored: true, monitorNewItems: "all"`; requested
"All seasons + future" through Jellyseerr first when Sonarr lacks it), Unfollow sets `monitorNewItems: "none"` and never
deletes. A show's "Created by" cards get a small "Follow <name>" button each (`_film_makers.html`, via the `followed(kind)`
global); that, or Follow on the person page of someone with TV Creator / Director credits, follows them as a TV maker
(dept `creator`), so the 6-hourly check requests their new shows too. Following lists shows in their own group with
Unfollow. media.db `user_version` 3 (`migrate_shows`). Calls: the twelfth exception in `docs/connector-contract.md`.

**Search now (media-ux5, 2026-10-09):** `media_arr_search.py` sends a Radarr `MoviesSearch` / Sonarr `SeriesSearch` for
monitored items only, plus the "All seasons + future" request option; full behaviour in `docs/hub-changelog.md` and the
seventeenth exception in `docs/connector-contract.md`.

**Search all monitored (F3, 2026-10-12):** Activity › Requests and › Downloads open with one row (`_arr_sweep.html`, via
the `arr_sweep(request)` global): "Search missing" and "Search upgrades", each an inline confirm (htmx
`GET /media/arr/sweep?step=confirm`; without JS the page draws it from `?sweep_ask=`) then a `same_origin` POST that
sends Radarr `MissingMoviesSearch` + Sonarr `MissingEpisodeSearch`, or `CutoffUnmetMoviesSearch` +
`CutoffUnmetEpisodeSearch` — one worker thread and a 10 s timeout per app, so one app down never stops the other
(`?sweep=started|partial|failed`). A second sweep of the same kind inside 10 min is allowed; the card says "Started N min
ago · run again?" (in-process timestamp). Neither app configured: "Not connected", no buttons.

**Upgrade available (F4b, 2026-10-12):** `media_upgrades.py` reads the `arr` snapshot's `data.upgrades` (Radarr / Sonarr
cutoff unmet) — no call. A small light-blue line (`.upnote`, token `--upgrade`; macro `_upgrade_note.html`) says
"Upgrade available · WEBDL-720p → Bluray-1080p" ("· 3 episodes ·" for a show; no arrow when the cutoff is unknown) under
Movies / TV rows and cards, Requests rows and the film / show hero's status line (inline in the core, never an episode
page); Activity › Downloads gains an "Upgrades" block ("3 films · 2 shows", each title linked; "Not connected" when both
lists are null, absent for an older envelope). Films match on `tmdb:`; Sonarr rows are `tvdb:`, so a show matches its
own `tvdb:` key, else a known TheTVDB id (the Jellyfin item's ProviderIds.Tvdb — cached by its page, `media_item.peek` —
or a request's `tvdb_id`), else its normalised title when unique on both sides. "Search for upgrade" joins the lazy
Search-now fragment when the app's own id is on the list: an inline confirm, then `POST …/upgrade` (`same_origin`,
threadpooled) sends `MoviesSearch` / `SeriesSearch`; `?upgrade=started|failed` flashes "Upgrade search started" /
"Couldn't start the search". The app grabs the best release its profile allows; picking a release is not offered (v2).

## Run locally

```
python -m hub.seed_demo
set SNAPSHOT_DIR=data/demo-snapshots && python -m uvicorn hub.main:app --port 8800
```

Local-only: with no Access header, `?owner_view=you|her|both` picks the owner view. Tests: `python -m pytest -q tests/`
from the repo root (see `tests/README.md`). Deploy: `deploy/README.md`.
