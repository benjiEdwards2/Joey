# Connector contract

The one agreement between Track D (connectors, which write) and Track C (the
hub, which reads). Authored at WP23; the envelope it describes was FROZEN at
WP0 (D13). Changing the envelope is a dated DECISIONS.md entry plus a full
suite re-run — never a silent edit.

## THE HUB'S TILES READ SNAPSHOTS ONLY

A tile never calls a live API. Connectors fetch on their own hourly clock and
leave a file behind; the hub renders whatever file is there, or "Not connected"
if there is none. This is why the dashboard still loads when an upstream is down.

The single sanctioned exception is the **/money room page**, which reads SQLite
directly (D14). It is a room page, not a tile.

**Second exception (2026-10-05): the `/img/{ref}` poster proxy.** Media rows carry an
optional `poster` ref (string or null; `backdrop` too on Jellyfin now_playing/up_next),
an opaque pointer to art, never a URL: `jf:<id>` / `jfb:<id>` (Jellyfin; an episode uses
its series id), `radarr:<movieId>` / `sonarr:<seriesId>`, `tmdb:<posterPath>`. The hub
resolves it live with the same media env keys, caches to `IMG_CACHE_DIR` for 30 days and
serves a generated fallback card on any miss — so a down upstream never breaks a page.

**Third exception (2026-10-05): ratings + watch diary (`hub/media_db.py`).** The hub's
first WRITE path: `MEDIA_DB_PATH` (default `/data/sqlite/media.db`), a small SQLite file,
owner `you` on every row, created on first write (the pages render with no file). Media
rows therefore carry an optional `item_key` (string or null) — the stable identity ratings
and diary entries hang off: `tmdb:<id>` (Jellyfin movies with a Tmdb provider id, Radarr
movies, Jellyseerr requests), `tvdb:<id>` (Sonarr series), or `jf:<ItemId>`; a Jellyfin
episode uses its SERIES (`jf:<SeriesId>`, as its payload carries no series provider id).
Grammar `^(tmdb|tvdb|jf):[A-Za-z0-9-]+$`. The hub also proxies one live Jellyseerr search
for the diary's "Log a watch" form; with no keys it says "Search unavailable".

**Fourth exception (2026-10-05): Discover & Search (`hub/media_discover.py`)** — the third
live call path, after `/money` SQLite and `/img`. Routes `/media/discover`,
`/media/discover/search`, `/media/title/{kind}/{tmdb_id}` and its `/request` (GET `?step=confirm`,
POST behind the `same_origin` guard) call Jellyseerr live with `JELLYSEERR_URL` +
`JELLYSEERR_API_KEY`, server-side only. Results are cached in-process for 10 minutes; Jellyseerr's
status codes map to one set of words (Available · Partly available · Processing · Requested ·
Not in library); any failure logs the exception type only and degrades to words, never a 500.
The registry tile `discover` rides the `jellyseerr` snapshot for its stale badge.

**Fifth exception (2026-10-05): her view.** `media.db` ratings and diary are per owner —
primary key `(item_key, owner)`, owner `you` or `her` — and an older single-owner file is
migrated on connect with every row kept as `you`. Her data comes from a second Jellyfin user
(`JELLYFIN_USER_HER`, the exact display name; created by B. in Jellyfin, no fallback to the admin
account) read into the jellyfin `her` block below.

**Sixth exception (2026-10-06): the title-page file strip (`hub/media_files.py`).** A fifth live
call path: Jellyfin `/Users` (uid cached 1 h) then `/Users/{uid}/Items` with MediaStreams/MediaSources, using
`JELLYFIN_URL` + `JELLYFIN_API_KEY` server-side. Matching is a client-side `ProviderIds.Tmdb` filter, because
Jellyfin 12 ignores `AnyProviderIdEquals`. Cached 10 minutes; shown only for Available / Partly available titles;
any failure degrades to no strip. `media.db` also gained `setting(owner, key, value)` and `rating.level`
(`show` | `season` | `episode`, default `show`); rankings and by-year counts use show + season ratings only.

**Seventh exception (2026-10-06): the play recorder (`hub/media_plays.py`).** A sixth live call path, and the hub's
first background writer: every `PLAY_POLL_SECONDS` (60) it polls Jellyfin `/Sessions` (`JELLYFIN_URL` + `JELLYFIN_API_KEY`,
server-side only) and records each Movie/Episode being played into `media.db` table `play`. Off with `PLAY_RECORDER=off`
(or when the Jellyfin keys are missing). "A watch, not a sitting": the same user + item continues an open play unless it
reached >= 90 % or the gap is > 2 h, in which case a new play starts. Failures log the exception type only.

**Eighth exception (2026-10-06): the film page (`hub/media_film.py`, F9 + F10).** One page for every title: both
`/media/title/{kind}/{tmdb}` and `/media/item/{jf_id}` build the same `film` dict. Its live reads, all server-side and
all cached 10 minutes per path (a failed fetch is not cached), are Jellyfin item + seasons/episodes (`media_item.py`, with
the sixth exception's file strip) and Jellyseerr title (`/api/v1/{movie|tv}/{tmdb}`), `ratingscombined` (else `ratings`),
`similar`, `recommendations` and `collection/{id}`. Jellyseerr shares `media_discover`'s cache, so its `clear_cache()` (run
on Request) clears these too. Every call degrades per section to words, never a 500; Jellyseerr not connected makes none.
Logs carry exception types only; the page carries no key or upstream URL beyond the Play deep link and "Open in Jellyseerr".

**Ninth exception (2026-10-06): the person page (`hub/media_person.py`, F11).** `/media/person/{tmdb}` reads Jellyseerr
`/api/v1/person/{id}` and `/api/v1/person/{id}/combined_credits` live, server-side, cached 10 minutes via the film page's
cache (a failed fetch is not cached). "On your server" is built from the jellyfin snapshot library lists, not a Jellyfin
call. A non-numeric id 404s before any call is made; Jellyseerr down degrades to words, never a 500. Logs carry exception types only.

**`media.db` additions (2026-10-06).** `watchlist(owner, item_key, kind, title, year, poster, tmdb_id, added_at)`, key
`(owner, item_key)` (F6); `play(...)` per watch, with user, item/show/season/episode keys, runtime, `started_at`,
`last_seen_at`, `position_pct`, `finished` (F7); and diary columns `show_key, season_key, season, episode, show_title,
episode_title` (F8, added by `ALTER` on connect). jellyfin-synced diary rows are now per episode; older show-level rows
are kept and render as before.

**Backups.** The hub dumps `media.db` nightly (`hub/media_backup.py`, gzip, integrity-checked,
30 daily + monthly kept) to `MEDIA_BACKUP_DIR`, mounted from
`/volume1/Docker/joey/backups/media`, and warns on the Media area only when the newest dump is
over 36 h old.

**Notion is LINK tier.** A URL in `areas.yaml` and nothing else — no connector,
no snapshot, no expectation of one anywhere in the hub.

## Snapshot path convention

| What | Where |
|---|---|
| Live snapshots (the box) | `/opt/life-dashboard-data/snapshots/{id}.json`, mounted at `/data/snapshots` |
| Runner heartbeat | `{SNAPSHOT_DIR}/_runner.json` — last sweep only |
| Runner history | `{SNAPSHOT_DIR}/_runner_history.jsonl` — one line per sweep, append-only (WP38 soak evidence) |
| Committed samples | `config/sample_snapshots/` — the fixture sweep, what hub work is developed against |

Snapshots are **never committed** (D13); `data/` is gitignored. Their offsite
safety is the WP8 encrypted backup.

Writes are atomic: dump to a per-writer `.tmp`, then `os.replace`. A reader can
never see half a snapshot.

## The envelope

`connectors/schema/envelope.schema.json` — every field required, no extras.

| Field | Meaning |
|---|---|
| `connector` | id from the frozen namespace: open_meteo, gcal, clickup, macromates, home_assistant, jellyfin, nas_stats, money, media_status, arr, jellyseerr, qbittorrent, system, wud. `clickup` is reserved-but-unused (removed from v1, 2026-08-25). |
| `schema_version` | always `1` |
| `fetched_at` | last fetch **attempt** |
| `updated_at` | last **success** — this is what the hub's stale badge reads |
| `status` | `ok` or `error`. There is no `stale` status: staleness is computed by the hub from `updated_at` against the tile's `stale_after_minutes`. |
| `consecutive_failures` | 0 on success; **≥ 3 triggers the notifier** (WP28) |
| `error` | human-readable reason when status=error, else null |
| `data` | the per-feed payload — see below |

**Failure behaviour.** A failing run does not delete or blank anything: it
re-writes the envelope keeping the previous `data` and `updated_at` byte-for-byte,
sets status=error, bumps `consecutive_failures`, and refreshes `fetched_at` only.
The tile therefore keeps showing the last known value with a stale badge, which
is exactly the agreed failure handling (2026-08-25).

## The `data` block

Each feed has its own schema in `connectors/schema/data/{id}.schema.json`, and
every one of them requires the **hub display convention** (D17, WP18):

- `summary` — **required string**, the one composed line the tile shows
- `secondary` — optional string, the single supporting line

Feed-specific fields sit alongside them. Any person-scoped record carries
`owner: you | her | shared` (R12). `both` is a **view** (the hub's switcher),
never a stored value — the schemas reject it.

`home_assistant` is keyed by area (`house`, `car`, `garden`) because one
connector feeds three tiles; that keying is what lets each tile slice its own
entities instead of all three repeating the same summary.

**Open-Meteo forecast (2026-10-06, weather upgrade).** The same single GET now also asks for `hourly` and
7 `daily` days (`forecast_days=7`). `open_meteo` data gains optional `hourly` (≤ 24 rows from the current hour:
`time`, `temp_c`, `rain_prob_pct`, `feels_c`) and `days` (≤ 7 rows: `date`, `min_c`, `max_c`, `rain_prob_pct`,
`condition_text`, `sunrise`/`sunset` as local `HH:MM`, `uv_max`, `wind_max_kmh`); numbers may be null. `summary`,
`secondary` and the today fields are unchanged. Snapshots written before this lack both arrays — `/weather` then
renders today only.

**BOM radar loop (2026-10-06, Option 1 approved by B.).** Radar rides the existing `open_meteo` connector —
no new id (D13). After the forecast GET succeeds, `fetch()` pulls Melbourne 128 km (`IDR023`; `IDR022` is the
256 km view) from BOM anonymous FTP (`ftp.bom.gov.au`, passive, 10 s timeout): the latest 6 rain frames
`/anon/gen/radar/IDR023.T.<YYYYMMDDHHMM UTC>.png` (5-minutely as found 2026-10-06) and the static layers
`/anon/gen/radar_transparencies/IDR023.{background,topography,locations,range}.png`. **File-sidecar pattern:**
the PNGs are stored raw (no compositing) under `SNAPSHOT_DIR/radar/` as `layer_<name>.png` and
`frame_<stamp>.png`, each written atomically (tmp + `os.replace`), only after every file downloaded; files
named by neither the new set nor the current envelope are pruned. `open_meteo` data gains optional `radar`
`{station, fetched_ok, layers: [file], frames: [{file, time_iso (UTC)}] (oldest first, ≤ 6)}`. A radar failure
never fails the envelope: status stays `ok`, `radar` is the previous block with `fetched_ok: false` (its files are
still on disk) or absent if there never was one. Fixture mode never runs the step, so the committed sample has no
`radar`. The hub serves the files read-only at `/weather/radar/{name}` behind a filename allowlist.

**Jellyfin media rows (2026-10-05/06).** Rows in `now_playing`, `up_next`, `recent` and the
resume/history lists carry `jf_id` (the Jellyfin ItemId) and `data` carries `server_id` (from
`/System/Info`); together they build the deep link `/web/#/details?id={jf_id}&serverId={server_id}`
used by the hub hero and every shelf row. Snapshots written before this have neither field — the
hub falls back to the bare server link, so an older snapshot still renders. The optional `her`
block (`user`, `up_next`, `history`) is Georgina's view and is `null` when `JELLYFIN_USER_HER`
is unset or names no user.

**Episode keys (2026-10-06, F5).** Jellyfin episode rows (`history.recent`, `up_next`, `now_playing`, and the
`her` block) carry optional `show_key`, `season_key`, `episode_key` (`jf:<id>` or null), `season`, `episode` and
`show_title`; `item_key` is unchanged (the show). Rows without them still render at show level.

**Jellyfin library lists (2026-10-06, F3a).** `jellyfin` data gains optional top-level arrays
`movies` and `shows`, and the same two inside `her` (read as Georgina). Row shape (schema:
`connectors/schema/data/jellyfin.schema.json`, `additionalProperties: false`):

- movies: `title`, `year` (int|null), `jf_id`, `item_key` (`tmdb|tvdb|jf:`…|null), `poster`,
  `backdrop` (refs, nullable), `runtime_min` (int|null), `played` (bool), `last_played_at`,
  `added_at` (ISO|null), `community_rating` (number|null), `genres` (≤ 3 strings).
- shows: the same fields plus `status_word` (`Continuing` | `Ended` | `Unknown`), `episodes`
  (int ≥ 0) and `unplayed` (int ≥ 0).

Fetched in `connectors/stubs.py` (`Jellyfin`) with `GET /Users/{uid}/Items`,
`IncludeItemTypes=Movie` / `Series`, `Recursive=true`, `SortBy=SortName`, `Limit=2000`
(`LIBRARY_FETCH_LIMIT`) and `Fields` of `DateCreated,ProviderIds,Genres,ProductionYear` plus
`Overview` (and `Status,RecursiveItemCount` for series). That is two extra GETs on the 2-minute
sweep, four with `JELLYFIN_USER_HER`. Snapshots written before this have neither array and stay
valid; the hub library pages then say "Library list not available yet".

**Server area `system` (2026-10-06, WP-S2).** Live fetch needs no env: CPU % is the busy share of
two `/proc/stat` samples 1 s apart (idle includes iowait), RAM is `/proc/meminfo` MemTotal / MemAvailable,
plus `/proc/uptime` and `/proc/loadavg` (`load_1m` null if unreadable). Volumes are `os.statvfs` on each
container path in `SYSTEM_VOLUMES` (compose sets `/host/volume1`, bound `/volume1:/host/volume1:ro` on the
`connectors` service); `path` is reported with the `/host` prefix stripped (`/volume1`). Unreadable `/proc`
or a missing mount is an error envelope (`RuntimeError: cannot read /proc/stat (...)`), never invented numbers.

**`media_status` apps (2026-10-06, WP-S2).** The probe list adds `wud` (3030), `adm` (8000, Asustor ADM —
a 30x to https counts as Up) and `homepage` (3000). `gluetun` is derived, not probed: Up iff `prowlarr` or
`qbittorrent` answers (both route through it); when Down its note is `no answer via Prowlarr or qBittorrent`.
The hub's Server page groups `gluetun` under Downloads and the rest under System.

**Arr counts (WP-S3, 2026-10-06).** `arr` data gains three optional objects, each `null` on failure:
`radarr` (`movies` = all, `wanted` = monitored without a file, `missing` = those also available, `queued` =
the queue's `totalRecords`) from `GET /api/v3/movie`; `sonarr` (`series`, `wanted` = `/api/v3/wanted/missing`
`totalRecords`, `queued`) from `GET /api/v3/series` + that paged call; and `prowlarr` (`grabs`, `queries`,
`failed_grabs`, `failed_queries` summed over `GET /api/v1/indexerstats` indexers, plus `indexers` = count).
`queued` reuses the queue the feed already fetches. **Partial-ok, like gcal's one-feed-down rule:** a failed
count call nulls only that app's object (logged with a sanitised reason, no `app_errors` entry), an app that is
down has no counts, and `PROWLARR_URL`/`PROWLARR_API_KEY` unset means `prowlarr: null` — none of these fails
the run. These calls ride the 120 s fast loop with `arr`. Older envelopes lack all three and stay valid.

**WUD live (WP-S3, 2026-10-06).** `wud` reads `GET {WUD_URL}/api/containers` with HTTP Basic
(`WUD_USER`/`WUD_PASS`), hourly only (WUD itself checks daily). The list is returned unchanged; a WUD 9
digest-only update (`updateKind.kind == "digest"`, `result.tag` = current tag) gives `kind: "digest"`,
`new_tag: null`. Failure reasons are status/type only, never the URL or login.

**Arr `at` (2026-10-06).** `arrived` and `updated` rows gain an optional `at` — the ISO timestamp
of the newest import. "New this week" on My films / My shows filters on it and falls back to
parsing the `when` text for older snapshots.

The **money** data schema is Track E's — WP32 authors it under
`connectors/money/`. The money envelope is written by the importer, a
runner-registered task rather than a `Connector` subclass (D14), and an empty
CSV inbox is `status=ok`, never an error.

## Fixture vs live mode

`CONNECTOR_MODE` is `live` on the box (the default — forgetting the variable can
never silently serve fake data) and `fixture` in the suite and for local work.

- **fixture** — `fetch()` is never called; canned bytes are read from
  `connectors/fixtures/{id}/raw*`, no socket is opened, and BOTH timestamps are
  pinned to `2026-01-01T00:00:00+00:00` so output is byte-reproducible. That
  pinning is what lets `config/sample_snapshots/` be diffed in a test.
- **live** — missing credentials fail fast, and the error names the exact
  environment variable. Credentials live only in `deploy/.env` on the box.

## Cadence

The connectors container runs `while true; do python -m connectors.run_all; sleep 3600; done`
(D16 — a sleep loop, not crond; phase drift after a restart is accepted). One
connector crashing never stops the sweep.

D16 amended 2026-10-05: a second background loop runs
`python -m connectors.run_all --only jellyfin,media_status,qbittorrent,arr,system; sleep 120` for the live Media
feeds (and, since 2026-10-06, the Server area's `system` host-health feed). `--only id1,id2` runs a subset and tags the `_runner.json` / history line with
`"only": [...]` so full hourly sweeps can be told apart from fast partial ones.

## Add-a-connector checklist

Every file a new feed touches. Nothing here needs knowledge outside the repo.

1. `connectors/fixtures/{id}/raw*.json` — a canned upstream payload. Fake names
   and `@example.invalid` emails only; no URLs, no token-shaped strings
   (`tests/connectors/test_fixtures.py` enforces this).
2. `connectors/schema/data/{id}.schema.json` — the data block, requiring
   `summary`, allowing `secondary`, `additionalProperties: false`.
3. `connectors/stubs.py` — a `Connector` subclass with `id`, `requires_env`,
   `transform(raw)`, and its live `fetch()` (sanitised errors via `_safe_reason`; a connector that
   enriches rows per item, like `jellyseerr`'s TMDB titles, caps lookups and reuses `self._previous()`); append it to `STUBS` so it registers.
4. `config/areas.yaml` — a tile with `tier: embed|ingest`, `snapshot: {id}`,
   `stale_after_minutes`, `owner`. The id must already be in the frozen
   namespace in `connectors/schema/envelope.schema.json` (and in `FROZEN_SNAPSHOT_IDS`
   in `hub/registry.py`; `media_status`, `arr` and `jellyseerr` were added to both on 2026-10-05, `qbittorrent` on 2026-10-06, `system` and `wud` on 2026-10-06 for the Server area).
   An area may carry `hub_rank` (its place among the hub cards; Media is 1) and `hub_size`
   (`s22` is the hero card). Two tiles may share one snapshot (`jellyfin` feeds now-playing and watch history); each
   page is then picked by its tile's `detail` route.
5. `config/sample_snapshots/{id}.json` — regenerate the sweep per that folder's
   README and commit the result.
6. `deploy/.env.example` — name any new credential (never its value).
7. `tests/connectors/` — grow the cumulative suite in the SAME session (rule 13).
   The existing `tests/connectors/test_data_schemas.py`,
   `tests/connectors/test_sample_snapshots.py` and
   `tests/connectors/test_id_crosscheck.py` pick a new registered connector up automatically once
   its schema, fixture and sample are in place.
8. `docs/connector-contract.md` — this file, if the contract itself moved.

## Where the container proof stands

`connectors/Dockerfile` and `deploy/docker-compose.yml` were authored blind at
WP22 (the dev machine has no container engine). The first engine-verify: WP24 step 1.
