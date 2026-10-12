# Connector contract

The one agreement between Track D (connectors, which write) and Track C (the
hub, which reads). Authored at WP23; the envelope it describes was FROZEN at
WP0 (D13). Changing the envelope is a dated DECISIONS.md entry plus a full
suite re-run — never a silent edit.

## TILES READ SNAPSHOTS; THE NUMBERED EXCEPTIONS BELOW ARE THE ONLY LIVE PATHS

A tile never calls a live API. Connectors fetch on their own hourly clock and
leave a file behind; the hub renders whatever file is there, or "Not connected"
if there is none. This is why the dashboard still loads when an upstream is down.

The numbered exceptions below (the second onwards) are the only places the hub reaches out or writes.

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

**Fourth exception (2026-10-05): Discover & Search (`hub/media_discover.py`)** — a live
call path, after `/img`. Routes `/media/discover`,
`/media/discover/search`, `/media/title/{kind}/{tmdb_id}` and its `/request` (GET `?step=confirm`,
POST behind the `same_origin` guard) call Jellyseerr live with `JELLYSEERR_URL` +
`JELLYSEERR_API_KEY`, server-side only. Results are cached in-process for 10 minutes; Jellyseerr's
status codes map to one set of words (Available · Partly available · Processing · Requested ·
Not in library); any failure logs the exception type only and degrades to words, never a 500.
The registry tile `discover` rides the `jellyseerr` snapshot for its stale badge.
Browse by service (media-ux2, 2026-10-08) is part of this exception, not a new one: the Discover "Services" row
reads `/api/v1/watchproviders/{movies|tv}?watchRegion=AU` (24 h, in memory + the disk meta cache) and
`/media/discover/service/{provider_id}` reads `/api/v1/discover/{movies|tv}?watchRegion=AU&watchProviders=<id>&sortBy=…`
(6 h in memory; failed reads are not cached). Same env, same type/status-only logging, words on failure.

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
(`show` | `season` | `episode`, default `show`). By-year rankings removed 2026-10-09 (decision 1).

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
Logs carry exception types only; the page carries no key or upstream URL beyond the Play deep link and "Open in Seerr".
*Caching update (media-speed, 2026-10-07):* the 10-minute rule above still holds for everything carrying request /
availability state, and a 404 answer is now cached for that time too (network failures still are not). Ratings
(`ratingscombined` for films only — TV asks `ratings` alone), the person biography (`person/{id}`) and a season's episode
list (`tv/{id}/season/{n}`) carry no user state and are cached 6 h, in memory and on disk (`META_CACHE_DIR`, default
`<IMG_CACHE_DIR>/meta/`), 404s included. The reads run concurrently (Jellyfin and Jellyseerr side by side). A background
warm-up (`hub/media_warmup.py`, `MEDIA_WARMUP=off` disables) makes the same reads plus `/img` pre-fetches for at most 60
home-shelf titles at startup + 60 s and every 3 h; it is paced, idempotent and makes no call without the keys.

**Ninth exception (2026-10-06): the person page (`hub/media_person.py`, F11).** `/media/person/{tmdb}` reads Jellyseerr
`/api/v1/person/{id}` and `/api/v1/person/{id}/combined_credits` live, server-side, cached 10 minutes via the film page's
cache (a failed fetch is not cached). "On your server" is built from the jellyfin snapshot library lists, not a Jellyfin
call. A non-numeric id 404s before any call is made; Jellyseerr down degrades to words, never a 500. Logs carry exception types only.

**Tenth exception (2026-10-06): Server → Update now (`hub/server_updates.py`, WP-U1).** The hub's first live WRITE to
another app. `GET /server/updates/{name}/run?step=confirm` shows the facts; the `same_origin`-guarded POST calls What's Up
Docker 9.3 `POST {WUD_URL}/api/containers/{id}/triggers/dockercompose/local` (no body; HTTP Basic `WUD_USER`/`WUD_PASS`;
10 s), server-side only. WUD does not apply include/exclude on that endpoint, so the hub refuses — no call — unless the
current `wud` snapshot holds the container with `update_available` and `auto: true`, it has an `id`, and the WUD env is
set. Each call writes a `server_update_runs` row (outcome `requested` / `refused` / `unreachable`, note = status or
exception type only) and redirects to `/server#updates` with a flash word. Ignore/Unignore write only `media.db`.
Amended 2026-10-12: rows with `auto` not true (the notify-only containers) now call the second trigger
`triggers/dockercompose/manual` instead of being refused — set on the NAS with `WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_AUTO=false`,
so WUD only runs it on request. The `wud` container itself is always refused (updated by hand). Amended 2026-10-12: any
`joey-*` container (Joey's own, not in the media-server compose the WUD triggers manage) is refused too — no button, 409,
no call; it updates on the next Joey deploy (`hub.server.update_hold`, one `JOEY_PREFIX` rule). Amended 2026-10-12:
**Update all** (`GET /server/updates/all/run?step=confirm` → `same_origin` POST) makes the same per-row call, in turn
(gluetun first), for every pending, non-ignored row that `refusal()` passes — never wud or `joey-*` — recording a
`server_update_runs` row each; a WUD that doesn't answer ends the run. Flash "N requested · M refused".

**Eighteenth exception (2026-10-12): Server → Restart + update media stack (`hub/server_stack.py`).** A live WRITE to
the `stackctl` helper (`stackctl/`, runs in the media-server compose on the NAS with the Docker socket). `GET
/server/stack/run?step=confirm` says exactly what happens (pull + recreate every media-server container except WUD and
stackctl; manual-only apps update too; pinned tags stay; playback and downloads drop for minutes; Joey untouched); the
`same_origin` POST calls `POST {STACKCTL_URL}/media/pull-up` (`Authorization: Bearer STACKCTL_TOKEN`, 10 s) and redirects
with a flash word (started / busy / refused / unreachable). The `/server` render reads `GET {STACKCTL_URL}/status` (2 s)
for one status line. Server-side only; the token never reaches a page, redirect or log; failures log the HTTP status or
exception type only. Env unset ⇒ no call, no button, "Not connected".

**Eleventh exception (2026-10-06): Server → Discord push (`hub/server_alerts.py`, WP-U2).** An outbound live call: when
`SERVER_DISCORD_WEBHOOK` is set, each NEW `/server` Attention item is POSTed once to that Discord webhook as plain text
("Joey Server: <item>", max 5 per cycle, 10 s timeout), after a `/server` render and on a 5-minute hub loop. Keys live in
media.db `server_attention_seen`. Unset ⇒ nothing. The webhook URL is the credential: never logged or rendered; failures log
the HTTP status or exception type only.
**Not configured is not failing (WP-U3, 2026-10-07).** A connector whose latest error is `MissingCredential: …` (the
exact prefix `Connector.run` records), or whose snapshot no visible area reads (only `hidden` areas, or none), is "not
configured": it is never a `/server` Attention item, never a Discord post and never turns the hub's Server card amber;
the Sweeps (24 h) table shows it as "Not configured". So keep the `MissingCredential` type for "env var unset" — a
connector that raised a generic error for missing setup would page B.

**Twelfth exception (2026-10-07): Follow (`hub/media_follow.py`).** A background reader AND writer of Jellyseerr. For
each row of media.db `media_follows` (a person or a TMDB collection, followed from its page by a `same_origin`-guarded
POST) the check reads, live and server-side, `/api/v1/person/{id}/combined_credits` (films only: crew `job == "Director"`,
or cast — whose top-5 billing it confirms from that film's `/api/v1/movie/{id}` `credits.cast[].order`, because Jellyseerr's
person credits drop TMDB's `order`) or `/api/v1/collection/{id}` (`parts`). A film released before the follow date is never
read further or requested. Each remaining film not yet in Jellyseerr is requested with the SAME `POST /api/v1/request`
(`{"mediaType": "movie", "mediaId": id}`) the Discover Request button sends, at most 10 a run (the rest wait a run), and
recorded in `media_follow_adds` (outcome `requested` / `already` / `failed`; a recorded requested/already title is never
requested again). Runs right after a Follow (a response background task) and on a hub loop ~2 min after start, then every
6 h; `MEDIA_FOLLOW=off` disables the loop; no Jellyseerr keys ⇒ no calls. Each add POSTs one Discord message ("Joey Media:
added …") to `MEDIA_DISCORD_WEBHOOK`, else `SERVER_DISCORD_WEBHOOK` (neither ⇒ silent). Logs carry status / exception type only.
*Shows and TV makers (F5, 2026-10-12).* `media_follows.kind` also takes `show`, and `media_follow_adds` is keyed on
(follow, `media` movie / tv, TMDB id). **Follow show** (`POST /media/follow/show/{tmdb}`, `same_origin`, worker thread):
records the follow, then reads Sonarr `GET /api/v3/series` (full list, matched on `tmdbId`) and, when the show is there,
`PUT /api/v3/series/{id}` with Sonarr's own resource plus `monitored: true, monitorNewItems: "all"` (every other field
kept; no search). A show Sonarr doesn't have is requested first through the seventeenth exception's "All seasons + future"
path: Jellyseerr `POST /api/v1/request` `{"mediaType": "tv", "mediaId": id, "seasons": "all"}`, then
`media_arr_search.follow_all` (≤ 3 Sonarr reads 2 s apart, the same PUT, `SeriesSearch`). The follow is kept whatever
Sonarr / Jellyseerr answer; the flash says what happened (`?sonarr=<code>`). **Unfollow show** deletes the row, reads the
series and PUTs it back with `monitorNewItems: "none"` only (monitored and files untouched) — nothing is ever DELETEd.
The 6-hourly check reads the Sonarr series list once and repeats the follow PUT for any followed show that isn't
monitored with new seasons (Sonarr added it after the Follow, or it was changed by hand); it needs Sonarr only. The show
page's Follow line is a media.db read — no Sonarr or Jellyseerr call on render. **TV makers:** a person followed with
dept `creator` (the show page's "Created by" Follow buttons, or the person page of someone with TV Creator / Director
credits; form field `tv=1`) also has the shows in `combined_credits.crew` with `mediaType: "tv"` and `job` Creator or
Director — or Executive Producer when they are a Creator somewhere — whose `firstAirDate` is after today requested with
`{"mediaType": "tv", "mediaId": id, "seasons": "all"}`, under the same cap, once per follow, Discord "added show …".
Everyone else's TV credits are still ignored.

**Thirteenth exception (2026-10-08): Remove a request (`hub/media_requests.py`).** A `same_origin` POST from the
Requests page's inline confirm. Writes, live and server-side: Jellyseerr `DELETE /api/v1/request/{id}` (X-Api-Key; a 404
counts as removed); then ONLY when nothing is on disk (the snapshot row is not Available / Partly available AND the app
reports no file: Radarr `hasFile` / `sizeOnDisk`, Sonarr `statistics.episodeFileCount` / `sizeOnDisk`) it reads Radarr
`GET /api/v3/movie?tmdbId=` or Sonarr `GET /api/v3/series?tvdbId=` (else the full list matched on `tmdbId`) and PUTs the
app's own resource back with `monitored: false` (`/api/v3/movie/{id}` or `/api/v3/series/{id}`; `RADARR_URL`/`_API_KEY`,
`SONARR_URL`/`_API_KEY`, header X-Api-Key). It never deletes a file, an *arr entry or Jellyseerr media. The removed row is
hidden in memory until a jellyseerr snapshot taken after the removal (`hub/media_hidden.py`). The jellyseerr data block's TV
rows gain `tvdb_id` (integer or null) for this. Flashes and logs carry the HTTP status or exception type only.

**Fourteenth exception (2026-10-08): Move on from Continue watching (`hub/media_resume.py`).** Two `same_origin`
POSTs (`/media/resume/{jf_id}/watched`, `/media/resume/{jf_id}/reset`) write live to Jellyfin as the viewer's user
("you" = `JELLYFIN_USER` / first admin, "her" = exactly `JELLYFIN_USER_HER`, never the admin): `POST
/UserPlayedItems/{id}?userId=` and `POST /UserItems/{id}/UserData?userId=` with `{"PlaybackPositionTicks": 0}` (10.9+);
a 404/405 falls back to `/Users/{uid}/PlayedItems/{id}` and `/Users/{uid}/Items/{id}/UserData`. The item is dropped from
the jellyfin snapshot's `up_next` (B.'s) or `her.up_next` (hers) in memory until a newer sweep (`hub/media_hidden.py`,
applied in `main.get_snapshots`). A watched mark reaches the diary by the usual path (next sweep's history ->
`sync_diary_from_history`). Flashes and logs carry the HTTP status or exception type only.
Extended in media-ux3 (2026-10-08): `POST /media/resume/{jf_id}/unwatched` sends `DELETE /UserPlayedItems/{id}?userId=`
(404/405 → `DELETE /Users/{uid}/PlayedItems/{id}`), and the watched / unwatched routes also take a season id
(`scope=season`), which Jellyfin applies to every episode of the season. Unwatched never deletes a diary row.

**Fifteenth exception (2026-10-08): Metacritic via OMDb (`hub/media_omdb.py`, media-ux4).** A live outbound read, server-side
only, when the optional `OMDB_API_KEY` is set: the film page asks `GET https://www.omdbapi.com/?i={imdb id}&apikey=…` (IMDb
id from Jellyseerr `externalIds.imdbId` / `imdbId`, else Jellyfin `ProviderIds.Imdb`) and shows `Metascore`, else the
`Ratings` "Metacritic" entry, as a pill. Every answer for a title (a score, "N/A", not found, a failed call) is remembered
7 days in memory and on disk beside the Jellyseerr meta cache (`META_CACHE_DIR`, key `omdb:<id>`), so a title costs at most
one call per 7 days, restarts included; a process makes at most 800 calls a UTC day (free tier 1,000); a refused key or
OMDb's own limit stops calls for the rest of the day without marking any title. The warm-up never calls OMDb. No key or any
failure ⇒ no pill, never a 500. The request URL carries the key, so logs carry the HTTP status or exception type only —
never a URL, message or body — and the page never carries the key.

**Trailer player (media-ux4, 2026-10-08) — a recorded privacy exception, like the Windy radar.** The film page's
Trailer button opens an in-page player: a `<dialog>` into which a small inline script inserts
`<iframe src="https://www.youtube-nocookie.com/embed/{key}?autoplay=1&rel=0">` **only when the user presses Trailer**
(nothing in the page loads from YouTube before that; the initial HTML holds no iframe), and closing the dialog removes the
iframe. So the browser — not the hub — talks to youtube-nocookie.com, only after that press. The key is the YouTube id of
Jellyfin's `RemoteTrailers` URL or Jellyseerr's TMDB `relatedVideos` trailer (11 characters, validated server-side and in
the script). Without JS the button is a plain link to the video on YouTube. The hub sends no CSP header today; if one is
added, it must allow `frame-src https://www.youtube-nocookie.com`.

**Sixteenth exception (2026-10-08): Awards sync (`hub/media_awards.py`, AWARDS_PLAN).** A background READ-only pull
from two public, keyless hosts — `query.wikidata.org/sparql` (GET, `Accept: text/csv`; one query per Oscars edition
`?st pq:P805 wd:<edition>`, one discovery query for the six ceremony series, one winners query per Cannes / DGA / PGA / WGA
category list, and one ids query per ≤ 150 new QIDs) and `en.wikipedia.org/w/api.php` (`action=parse&prop=wikitext` of one
ceremony page per call; `action=query&prop=pageprops&ppprop=wikibase_item&redirects=1` for ≤ 50 linked titles per call).
`www.wikidata.org` `wbgetentities` is NOT used: measured 2026-10-08 it answered 530 KB for 8 titles with claims. Sequential,
one session per pass, 2 s between calls, 30 s timeout, ≤ 40 editions per pass, a pass every 6 h while a backlog exists, then
weekly (Sunday from 09:00), never 22:00–07:00 local; a 429 waits `Retry-After` (≤ 120 s) once and a second 429 ends the pass.
Every call sends `User-Agent: Joey/awards (+https://joeyhome.net; <AWARDS_CONTACT>)`; `MEDIA_AWARDS=off` or an unset
`AWARDS_CONTACT` ⇒ no calls. Results land in media.db `award_body`, `award_edition`, `award_category`, `award_nomination`,
`award_entity`, `award_title`, `award_sync` (backed up nightly with the rest of media.db). The Awards pages and the film /
person page sections read only those tables plus the jellyfin snapshot (✓ seen) and the diary; off-server posters come from
the existing Jellyseerr meta cache (`media_discover.meta_get`) on render, ≤ 60 per page view, stored on `award_entity.poster`.
`scripts/awards_sync.py --edition oscars:97` runs one edition by hand through the same code. Logs carry counts and HTTP
status / exception type only — never a URL, a page title or a body.

**Seventeenth exception (2026-10-09): Search now + "All seasons + future" (`hub/media_arr_search.py`, media-ux5).** Live
Radarr / Sonarr reads and writes, server-side only (`RADARR_URL`/`_API_KEY`, `SONARR_URL`/`_API_KEY`, header X-Api-Key;
the title lookup is the thirteenth exception's: Radarr `GET /api/v3/movie?tmdbId=`, Sonarr `GET /api/v3/series?tvdbId=`
else the full list matched on `tmdbId`). *Search now:* the film / series page lazy-loads
`GET /media/title/{kind}/{tmdb}/arr` (one lookup; the form only when the app has the title — the page render itself makes
no *arr call); the `same_origin` POST `/media/title/{kind}/{tmdb}/search` looks the title up again and sends
`POST /api/v3/command` `{"name": "MoviesSearch", "movieIds": [id]}` (Radarr) or `{"name": "SeriesSearch", "seriesId": id}`
(Sonarr). The apps search monitored items only. *All seasons + future:* after a successful Jellyseerr TV request sent with
`"seasons": "all"`, the series is read from Sonarr (≤ 3 reads, 2 s apart — it appears once Jellyseerr hands it over; else
skipped and the flash says so), PUT back as the app's own resource with `monitored: true, monitorNewItems: "all"` (every
other field kept), then SeriesSearch. Nothing is ever deleted. Flashes and logs carry the HTTP status or exception type only.
*Search all monitored (2026-10-12, F3):* the Activity › Requests and › Downloads tabs carry two buttons B. presses himself,
each a two-step confirm then `POST /media/arr/sweep` behind `same_origin` — "Search missing" sends Radarr
`{"name": "MissingMoviesSearch"}` + Sonarr `{"name": "MissingEpisodeSearch"}`, "Search upgrades" sends
`CutoffUnmetMoviesSearch` + `CutoffUnmetEpisodeSearch` (both `POST /api/v3/command`, threadpooled, 10 s each, one app
down is a partial word). Nothing is read; the arrs do the searching and grabbing per their own profiles.
*Search for upgrade (2026-10-12, F4b):* on a film / show page whose title is on the `arr` snapshot's `upgrades` list,
a two-step confirm then `POST /media/title/{kind}/{tmdb}/upgrade` behind `same_origin` repeats the Search-now lookup and
sends the same per-title `MoviesSearch` / `SeriesSearch` command; the app replaces the file only with a release its
profile ranks higher.

**`media.db` additions (2026-10-06).** WP-U1: `server_update_ignores(container, tag, ignored_at)`, key `(container, tag)`
(tag = new tag, or the current tag for a digest update), and `server_update_runs(container, tag, requested_at, outcome,
note)` — the Server page is single-owner, so no owner column. `watchlist(owner, item_key, kind, title, year, poster, tmdb_id, added_at)`, key
`(owner, item_key)` (F6); `play(...)` per watch, with user, item/show/season/episode keys, runtime, `started_at`,
`last_seen_at`, `position_pct`, `finished` (F7); and diary columns `show_key, season_key, season, episode, show_title,
episode_title` (F8, added by `ALTER` on connect). jellyfin-synced diary rows are now per episode; older show-level rows
are kept and render as before.
WP-U4: `server_system_samples(ts, cpu_pct, ram_pct_used, ram_free_gb, load_1m, volumes)` — the hub's history of the
`system` feed for the Server "Last 24 h" band. It is DERIVED from the `system` snapshot envelopes already on disk (one row
per new `updated_at`, `status: ok` only, 8-day retention): no new live call, no connector change.

**Backups.** The hub dumps `media.db` nightly (`hub/media_backup.py`, gzip, integrity-checked,
30 daily + monthly kept) to `MEDIA_BACKUP_DIR`, mounted from
`/volume1/Docker/joey/backups/media`, and warns on the Media area only when the newest dump is
over 36 h old.

**Notion is LINK tier.** A URL in `areas.yaml` and nothing else — no connector,
no snapshot, no expectation of one anywhere in the hub.

## Snapshot path convention

| What | Where |
|---|---|
| Live snapshots (the box) | `/volume1/Docker/joey/data/snapshots/{id}.json`, mounted at `/data/snapshots` |
| Runner heartbeat | `{SNAPSHOT_DIR}/_runner.json` — last sweep only, written atomically (tmp + `os.replace`) |
| Runner history | `{SNAPSHOT_DIR}/_runner_history.jsonl` — one line per sweep, append-only (WP38 soak evidence). Since WP-U2 (2026-10-06) the hub READS its tail (read-only mount; last 2 MB / 1000 lines) for 24 h per-connector sweep failures on `/server` — keep the line shape `{ran_at, results: {id: {status, error, ...}}, only?}`. Since 2026-10-09 each result also carries `duration_ms` and each line `sweep_ms` (the heartbeat does not), and past 5 MB the file is rewritten atomically to its newest lines of the last 14 days, capped at 2.5 MB (≥ 24 h always kept) |
| Committed samples | `config/sample_snapshots/` — the fixture sweep, what hub work is developed against |

Snapshots are **never committed** (D13); `data/` is gitignored. Their offsite
safety is the WP8 encrypted backup.

Writes are atomic: dump to a per-writer `.tmp`, then `os.replace`. A reader can
never see half a snapshot.

## The envelope

`connectors/schema/envelope.schema.json` — every field required, no extras.

| Field | Meaning |
|---|---|
| `connector` | id from the frozen namespace: open_meteo, gcal, clickup, macromates, home_assistant, jellyfin, nas_stats, money, media_status, arr, jellyseerr, qbittorrent, system, wud, uptime_kuma. `clickup` is reserved-but-unused (removed from v1, 2026-08-25). |
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

**Error text never carries a URL (2026-10-09, C-06).** Every live `fetch()` reduces an upstream failure to
type/status (`_safe_reason` and friends) — Open-Meteo included, whose query holds the home coordinates. As
defence in depth `base.run` (and the runner's own isolation path) replaces any `http(s)://…` in the error with
`<url>` before it is logged or stored. Open-Meteo sends `timezone=auto` when `TZ` is unset **or blank**.

## The `data` block

Each feed has its own schema in `connectors/schema/data/{id}.schema.json`, and
every one of them requires the **hub display convention** (D17, WP18):

- `summary` — **required string**, the one composed line the tile shows
- `secondary` — optional string, the single supporting line

Feed-specific fields sit alongside them. Any person-scoped record carries
`owner: you | her | shared` (R12). `both` was a view (the old switcher, gone since 2026-10-06);
it is never a stored value — the schemas reject it.

`home_assistant` is keyed by area (`house`, `car`, `garden`) because one
connector feeds three tiles; that keying is what lets each tile slice its own
entities instead of all three repeating the same summary.

**Home time zone (2026-10-09, C-08).** Everything calendar-shaped is computed in the household's zone,
`base.home_tz()`: `TZ`, else `Australia/Melbourne` (the hub's `HOME_TZ_NAME`), UTC only if no tz database
loads; fixture mode always uses Australia/Melbourne so samples never depend on the machine. That covers
Jellyfin `history.on_this_day` (local month/day), the Arr calendar window and `this_week` dates, and `when`
texts of a day or more ("yesterday", "N days ago" count local calendar days; under 24 h stays "N hours ago").
Durations (last 7/30 days, qBittorrent's 24 h "finished today") are unaffected.

**One duration format (2026-10-09, C-14).** Arr `time_left`, qBittorrent `eta_text` and the `system` uptime in
`secondary` all come from `_duration_words`: `12m`, `1h 05m`, `5h 20m`, `12d 4h` (was "12 min" / "1 h 05 min" /
"12 days" depending on the feed).

**Open-Meteo forecast (2026-10-06, weather upgrade).** The same single GET now also asks for `hourly` and
7 `daily` days (`forecast_days=7`). `open_meteo` data gains optional `hourly` (≤ 24 rows from the current hour:
`time`, `temp_c`, `rain_prob_pct`, `feels_c`) and `days` (≤ 7 rows: `date`, `min_c`, `max_c`, `rain_prob_pct`,
`condition_text`, `sunrise`/`sunset` as local `HH:MM`, `uv_max`, `wind_max_kmh`); numbers may be null. `summary`,
`secondary` and the today fields are unchanged. Snapshots written before this lack both arrays — `/weather` then
renders today only.

**Rain radar (RADAR SUPERSESSION, 2026-10-07).** The `/weather` radar is a Windy embed (`embed.windy.com`, loaded
by the browser — a recorded exception to "the phone talks only to Joey"). The parked BOM radar loop (2026-10-06, gated
off behind `RADAR_LOOP` since 2026-10-07) was removed 2026-10-09 (decision 5): `open_meteo` makes no FTP connection,
emits no `radar` block, and its data schema no longer lists one; the `/weather/radar/{name}` route is gone.

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

Fetched in `connectors/feeds/jellyfin.py` (`Jellyfin`) with `GET /Users/{uid}/Items`,
`IncludeItemTypes=Movie` / `Series`, `Recursive=true`, `SortBy=SortName`, `Limit=2000`
(`LIBRARY_FETCH_LIMIT`) and `Fields` of `DateCreated,ProviderIds,Genres,ProductionYear` plus
`Overview` (and `Status,RecursiveItemCount` for series). That is two extra GETs on the 2-minute
sweep, four with `JELLYFIN_USER_HER`. Snapshots written before this have neither array and stay
valid; the hub library pages then say "Library list not available yet".

**Jellyfin partial-ok (2026-10-09, C-09).** Only the core calls (users, system, sessions, resume, next up,
latest, counts, history) can fail the `jellyfin` feed. The library lists and every `her` call are optional:
one that fails is logged with its sanitised reason (`Jellyfin movies failed (Timeout)`) and the envelope stays
`ok` — `movies` / `shows` absent, or `her` null when her resume, next up or history is missing.

**Server area `system` (2026-10-06, WP-S2).** Live fetch needs no env: CPU % is the busy share of
two `/proc/stat` samples 1 s apart (idle includes iowait), RAM is `/proc/meminfo` MemTotal / MemAvailable,
plus `/proc/uptime` and `/proc/loadavg` (`load_1m` null if unreadable). Volumes are `os.statvfs` on each
container path in `SYSTEM_VOLUMES` (code default `/host/volume1`; compose sets `/data/snapshots`, the snapshots bind,
which lives on `/volume1`, so `statvfs` gives that volume's numbers without mounting the whole NAS volume, C-19, 2026-10-09).
The reported `path` is the container path with a leading `/host` stripped, or its `SYSTEM_VOLUME_LABELS` name
(`path=label[,path=label]`); compose sets `SYSTEM_VOLUME_LABELS=/data/snapshots=/volume1`, so the UI shows `/volume1`. Unreadable `/proc`
or a missing mount is an error envelope (`RuntimeError: cannot read /proc/stat (...)`), never invented numbers.

**`media_status` apps (2026-10-06, WP-S2).** The probe list adds `wud` (3030), `adm` (8000, Asustor ADM —
a 30x to https counts as Up); `homepage` (3000) was dropped 2026-10-09 (decision 9: Homepage retired), so 11 apps. `gluetun` is derived, not probed: Up iff `prowlarr` or
`qbittorrent` answers (both route through it); when Down its note is `no answer via Prowlarr or qBittorrent`.
The hub's Server page groups `gluetun` under Downloads and the rest under System. Since 2026-10-09 (C-12) the
probes run six at a time (5 s timeout each), so a filtered port no longer stretches the 120 s loop by ~55 s.

**Arr counts (WP-S3, 2026-10-06).** `arr` data gains three optional objects, each `null` on failure:
`radarr` (`movies` = all, `missing` = monitored without a file, `wanted` = those also released/available, `queued` =
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
`new_tag: null`. Failure reasons are status/type only, never the URL or login. WP-U1 (2026-10-06) adds two
optional fields per container: `id` (WUD's container id, null when absent) and `auto` (true when WUD's
`dockercompose.local` trigger applies — not in `triggerExclude` and, when `triggerInclude` is set, listed there;
the `wud.trigger.exclude` / `wud.trigger.include` labels are the fallback). Older envelopes without them stay valid.

**Uptime Kuma (WP-S4, 2026-10-06).** `uptime_kuma` (frozen id added 2026-10-06, authorised dated
decision) reads Uptime Kuma 1.23's Prometheus `GET {UPTIME_KUMA_URL}/metrics` with HTTP Basic where the
username is EMPTY and the password is the API key (`UPTIME_KUMA_API_KEY`). Only `monitor_status`
(1 up / 0 down / 2 pending / 3 maintenance) and `monitor_response_time` (ms; -1 → null) are read; data is
`{monitors: [{name, type, status, response_ms}], up, down, total, summary, secondary}`, sorted down → pending →
maintenance → up. `monitor_url`/`monitor_hostname`/`monitor_port` are never carried (LAN addresses, tokens).
Text with no parseable monitor metrics is an error envelope ("unexpected payload", no label echo); HTTP
failures are status/type only. Hourly sweep plus the 120 s fast loop.

**Arr `at` (2026-10-06).** `arrived` and `updated` rows gain an optional `at` — the ISO timestamp
of the newest import. "New this week" on My films / My shows filters on it and falls back to
parsing the `when` text for older snapshots.

**Arr upgrades (F4a, 2026-10-12).** `arr` data gains an optional `upgrades` object — the titles whose file on
disk is below their quality profile's cutoff (Radarr/Sonarr "cutoff unmet"). It says the file is not yet the
quality the profile aims for; it does **not** mean a better release is on the indexers right now (the hub's
"Search for upgrade" button asks the app to look). Read each sweep (on the 120 s loop with `arr`, one cheap page):
Radarr `GET /api/v3/wanted/cutoff?page=1&pageSize=100&monitored=true&sortKey=movieMetadata.sortTitle&sortDirection=ascending`,
Sonarr the same path with `sortKey=series.sortTitle&includeSeries=true&includeEpisodeFile=true`, plus each app's
`GET /api/v3/qualityprofile` to name the cutoff. Shape:
`{radarr: [{item_key, title, year, arr_id, have, want, poster}] | null, sonarr: [{item_key, title, arr_id, episodes,
have, want, sample, poster}] | null, totals: {movies, episodes, series}}`. Radarr: one row per movie, `item_key`
`tmdb:<tmdbId>`, `arr_id` the movie id, `have` = `movieFile.quality.quality.name` from the `GET /api/v3/movie` list the counts already fetch, joined on `id` (Radarr cutoff records carry only `movieFileId`; a record's own `movieFile` wins if present). Sonarr: episodes grouped per
series, `item_key` `tvdb:<tvdbId>` (the queue / this-week scheme), `arr_id` the series id, `episodes` = cutoff-unmet
episodes listed, `have` = the lowest `episodeFile.quality.quality.name` among them (by resolution), `sample` = the
earliest such episode (`S01E02`). `want` = the name of the profile's cutoff (`qualityProfileId` — the movie's, or
the series' — → profile `cutoff` → that quality, or that quality group's name); null when the profile list is
unavailable or lacks the id. Rows sort by title; lists hold at most one page (100). `totals.movies` /
`totals.episodes` are the cutoff calls' `totalRecords` (may exceed the page), `totals.series` the Sonarr rows listed;
the `radarr` / `sonarr` count objects gain the same optional `upgrades` (= `totalRecords`). **Partial-ok:** a failed
cutoff call nulls only that app's list (`partial_errors["<app>_upgrades"]`, no `app_errors` entry, no `upgrades`
count) and skips its profile call; a failed profile call only nulls `want`; an app that is down has a null list.
`summary` / `secondary` are unchanged (the hub renders the label). Older envelopes lack `upgrades` and stay valid.

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

## Parked connectors

Since 2026-10-09 (review C-01/N-12) `macromates`, `home_assistant` and `nas_stats` are **parked**: they
have a transform, fixture and data schema but no live `fetch()`, so in live mode they could only ever write
`MissingCredential` error envelopes. They are registered as parked (`connectors/feeds/__init__.py` `PARKED`):

- **fixture mode** builds them like any other feed — the sample sweep needs no env, so
  `config/sample_snapshots/` keeps all 13 ids;
- **live mode** sweeps a parked connector only when every name in its `requires_env` is set
  (`macromates`: `SUPABASE_URL`, `SUPABASE_KEY`; `home_assistant`: `HA_URL`, `HA_TOKEN`;
  `nas_stats`: `NAS_SHARES_ROOT` — these code names are the ones that count). Re-enabling one is
  "write its `fetch()`, then set the env".

Their ids stay in the frozen D13 envelope enum. `registry.connector_ids()` is what a sweep runs;
`registry.all_ids()` (parked included) is what `areas.yaml` is cross-checked against. A snapshot a parked
connector wrote before 2026-10-09 is simply no longer refreshed.

## Cadence

The connectors container runs `while true; do python -m connectors.run_all; sleep 3600; done`
(D16 — a sleep loop, not crond; phase drift after a restart is accepted). One
connector crashing never stops the sweep.

D16 amended 2026-10-05: a second background loop runs
`python -m connectors.run_all --only jellyfin,media_status,qbittorrent,arr,system,uptime_kuma; sleep 120` for the live Media
feeds (and, since 2026-10-06, the Server area's `system` host-health and `uptime_kuma` monitor feeds). `--only id1,id2` runs a subset and tags the `_runner.json` / history line with
`"only": [...]` so full hourly sweeps can be told apart from fast partial ones.

Amended 2026-10-09 (review C-17): the container entrypoint runs ONE full sweep at start, then the 120 s `--only`
loop above, then an hourly `python -m connectors.run_all --except jellyfin,media_status,qbittorrent,arr,system,uptime_kuma`
loop — so the two loops never run the same connector at once. `--except id1,id2` runs everything but that subset.
Jellyfin's `Limit=2000` library lists (and the her-view lists) are re-fetched at most every `JELLYFIN_LIBRARY_EVERY_S`
seconds (default 900; `0` = every run); between fetches the previous envelope's lists are carried forward and
`data.library_fetched_at` says when they were last pulled.

**Partial failures (2026-10-09, review C-10):** a connector that keeps going after one of its sources fails records
it in `data.partial_errors` (object: source → reason, reason = status / exception type only) via `base.partial_note()`.
`gcal` (`feed_errors`) and `arr` (`app_errors`) keep their older keys as well; Jellyfin's optional library / her-view
calls use only `partial_errors`. The envelope `status` stays `ok`; `run_all` counts such sweeps as `partial` in its
summary line.

## Add-a-connector checklist

Every file a new feed touches. Nothing here needs knowledge outside the repo.

1. `connectors/fixtures/{id}/raw*.json` — a canned upstream payload. Fake names
   and `@example.invalid` emails only; no URLs, no token-shaped strings
   (`tests/connectors/test_fixtures.py` enforces this).
2. `connectors/schema/data/{id}.schema.json` — the data block, requiring
   `summary`, allowing `secondary`, `additionalProperties: false`.
3. `connectors/feeds/{id}.py` — a `Connector` subclass with `id`, `requires_env`,
   `transform(raw)`, and its live `fetch()` (every HTTP call through `connectors/feeds/_http.py`
   `http_json(label, url, ..., session=...)`, which keeps the error reason to status / exception type only and reuses
   one `requests.Session` per run; a connector that enriches rows per item, like `jellyseerr`'s TMDB titles, caps
   lookups and reuses `self._previous()`); add it to `LIVE` in `connectors/feeds/__init__.py` so it registers
   (`PARKED` for one with no live `fetch()` yet). `connectors/stubs.py` is only a compatibility shim re-exporting the
   old names (2026-10-09, review C-04).
4. `config/areas.yaml` — a tile with `tier: embed|ingest`, `snapshot: {id}`,
   `stale_after_minutes`, `owner`. The id must already be in the frozen
   namespace in `connectors/schema/envelope.schema.json` (and in `FROZEN_SNAPSHOT_IDS`
   in `hub/registry.py`; `media_status`, `arr` and `jellyseerr` were added to both on 2026-10-05, `qbittorrent` on 2026-10-06, `system` and `wud` on 2026-10-06 for the Server area, `uptime_kuma` on 2026-10-06 for Server WP-S4).
   An area may carry `hub_rank` (its place among the hub cards; Media is 1). Two tiles may share one snapshot (`jellyfin` feeds now-playing and watch history); each
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

The first engine-verify was the NAS bring-up (2026-08-31); every deploy since goes through `deploy/deploy.sh` (build, offline suite, smoke).
