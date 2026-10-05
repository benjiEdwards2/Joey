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
| `connector` | id from the frozen namespace: open_meteo, gcal, clickup, macromates, home_assistant, jellyfin, nas_stats, money, media_status, arr, jellyseerr. `clickup` is reserved-but-unused (removed from v1, 2026-08-25). |
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

**Jellyfin media rows (2026-10-05/06).** Rows in `now_playing`, `up_next`, `recent` and the
resume/history lists carry `jf_id` (the Jellyfin ItemId) and `data` carries `server_id` (from
`/System/Info`); together they build the deep link `/web/#/details?id={jf_id}&serverId={server_id}`
used by the hub hero and every shelf row. Snapshots written before this have neither field — the
hub falls back to the bare server link, so an older snapshot still renders. The optional `her`
block (`user`, `up_next`, `history`) is Georgina's view and is `null` when `JELLYFIN_USER_HER`
is unset or names no user.

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
`python -m connectors.run_all --only jellyfin,media_status,qbittorrent; sleep 120` for the live Media
feeds. `--only id1,id2` runs a subset and tags the `_runner.json` / history line with
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
   in `hub/registry.py`; `media_status`, `arr` and `jellyseerr` were added to both on 2026-10-05).
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
