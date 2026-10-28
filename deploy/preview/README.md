# deploy/preview: the `joey-preview` slot (JY-012)

One preview hub on the NAS, so B. can try a branch on his phone or TV before it merges. Live data is read only.
Spec: `docs/specs/JY-012-preview.md`. Code: `scripts/joey_preview.py`.

## Commands (laptop, repo root)

Set `JOEY_NAS=root@<nas>` (and `JOEY_NAS_KEY` if the key is not `~/.ssh/joey_nas`). Every command takes `--dry-run`.

- `python scripts/joey.py preview up <branch | PR number>`: refuses outside 07:00-21:30 Melbourne time, while a deploy
  holds `/tmp/joey-deploy.lock`, or when NAS available memory is under 1,400 MB. A running slot is replaced (down, then
  up; the old commit is printed). First it takes `/tmp/joey-deploy.lock` itself, in `deploy.sh`'s format (a directory
  with the pid of a detached holder on the NAS, plus this run's token in `owner`), so a `deploy.sh` started meanwhile
  exits 2 and `close-out` waits: one `docker build` at a time on the NAS (JY-228). The lock is released on success, on
  failure and after a teardown; the holder removes it by itself after 88 min if the laptop goes away (longer than all
  of a run's step timeouts put together, shorter than close-out's 90 min wait; JY-234). The release signals only a
  holder whose command line carries this run's token, so a reused pid is never killed (JY-234). Then: exact commit
  into `/volume1/Docker/joey/preview/src` (alpine/git + the read-only deploy key, as `deploy.sh`), `docker build` to
  `life-hub-preview`, newest daily media.db backup restored as a copy, `preview.env` built from the allow-list below,
  `up -d`, poll `/healthz` inside the container (up to 120 s). It prints the commit, the URL and the memory readings.
  The deploy lock is checked again just before `up -d` (it must still be this preview's). From the media.db restore on,
  any FAIL (no `/healthz`, under 1,200 MB available after the start, a held lock, an ssh error, a failed `up`) tears the
  slot down, so no container, media.db copy or `preview.env` is left. `--dry-run` records a check that would stop a real
  run (window, lock, memory, NAS unreachable) and goes on, so every step and NAS script prints.
- `python scripts/joey.py preview down`: `docker compose -p joey-preview down`, removes the image, the media.db copy and
  `preview.env`, then checks and prints that no container, network or image named for the preview, no media.db copy and
  no `preview.env` is left.
- `python scripts/joey.py preview status`: running or not, commit, uptime, memory use, NAS available memory.

## What runs on the NAS

| Path | What |
|---|---|
| `/volume1/Docker/joey/preview/docker-compose.yml` | this folder's compose file, copied by `preview up` (the previewed branch may not have it) |
| `/volume1/Docker/joey/preview/preview.env` | allow-listed keys only, chmod 600, NAS only; removed by `preview down` |
| `/volume1/Docker/joey/preview/src` | the previewed commit (detached checkout, kept for the next fetch) |
| `/volume1/Docker/joey/preview/sqlite/media.db` | the copy, from the newest `backups/media/media-YYYY-MM-DD_HHMM.db.gz`; removed by `preview down` |
| `/volume1/Docker/joey/preview/meta` | preview-only meta cache (`META_CACHE_DIR`) |

- Mounts: live snapshots `:ro`, the live poster cache `/volume1/Docker/joey/data/cache/img` `:ro`, the media.db copy, the
  preview meta dir. Never the live sqlite dir, never the backups dir.
- Network: the main stack's default network `deploy_default` (external), so the tunnel reaches `http://joey-preview:8000`.
  No ports. The service is named `joey-preview`, never a main service name: on a shared network the service name is a
  DNS alias, and `hub` would make cloudflared's `hub:8000` resolve to the preview too.
- Access (JY-014): the preview checks the Access JWT against the live `ACCESS_AUD`. Add `preview.joeyhome.net` to the
  existing joeyhome.net Access application (same audience tag); a separate application has another tag and the preview
  would refuse every request until that tag is in `ACCESS_AUD`.
- `restart: "no"`: the NAS powers off overnight and the slot does not come back by itself. Run `preview up` again.
- Memory: `mem_limit` 256m; budget joey-preview <= 200 MiB, NAS available >= 1,200 MB with the slot up.

## A main deploy while the slot runs

Safe. `deploy.sh` runs compose in `deploy/` with no `-p`, so its project is `deploy`; `up -d --remove-orphans` only
removes containers labelled `com.docker.compose.project=deploy`, and the preview carries `joey-preview`.
`docker image prune -f` removes only dangling images, not the tagged `life-hub-preview`.
Two cautions: a `docker compose down` of the MAIN stack cannot remove `deploy_default` while the preview is attached (run
`preview down` first), and a deploy that recreates `deploy_default` drops the preview off it (run `preview up` again).
`tests/deploy/test_preview_compose.py` checks the project names, the alias clash and the mounts.

## Background loops

All off. `MEDIA_BACKUP`, `PLAY_RECORDER`, `MEDIA_WARMUP`, `MEDIA_FOLLOW`, `MEDIA_AWARDS` and `DIGEST` are pinned `"off"` in
the compose `environment:` (which wins over `env_file`). The server alerts loop (`hub/tasks.py`) has no switch: without
`SERVER_DISCORD_WEBHOOK` it posts nothing, and its history samples land in the media.db copy.

## Not usable on the preview (by design)

- Requests, Discover's request button, Follow, Log-a-watch title search and request removal (no Seerr key).
- Search, upgrade, quality and Why?/Grab (no Radarr/Sonarr keys).
- Quiet mode, Restart + update media stack, WUD updates (no qBittorrent, stackctl or WUD keys).
- Jellyfin-backed reads: up next, resume, Continue watching and its buttons (no Jellyfin key: its writes, mark watched /
  unwatched / reset, reach the live Jellyfin, rule 7). Posters show for live-cache hits only; a miss falls back and is
  never stored (the cache is `:ro`). A hub read-only switch that would let the key back in is a separate item.
- Each fails visibly ("not configured" or "Couldn't reach"), never against the live system.

## Env keys: in or out

Every key in `deploy/.env.example`, plus `JELLYFIN_USER_ALIASES`. Source of truth: `ENV_IN` / `ENV_OUT` in
`scripts/joey_preview.py`; `tests/scripts/test_joey_preview.py` checks this table against them.

| Key | Preview | Why |
|---|---|---|
| `TZ` | in | container timezone |
| `OWNER_EMAIL_YOU` | in | maps B.'s Access login to 'you'; read only |
| `OWNER_NAME_YOU` | in | display name |
| `OWNER_NAME_HER` | in | display name |
| `ACCESS_JWT_VERIFY` | in | the preview checks the Access JWT like joey-hub |
| `ACCESS_AUD` | in | the Access audience the hub checks |
| `ACCESS_TEAM` | in | the Access team domain for the JWT keys |
| `WEATHER_LAT` | in | Open-Meteo, keyless read |
| `WEATHER_LON` | in | Open-Meteo, keyless read |
| `WEATHER_PLACE` | in | place name in the weather labels |
| `JELLYFIN_URL` | in | a LAN address, no credential; with no key the Jellyfin-backed reads fail visibly, and guest sign-in is off (the preview runs the private front) |
| `JELLYFIN_USER` | in | a display name (owner mapping), no credential |
| `JELLYFIN_USER_HER` | in | a display name (owner mapping), no credential |
| `JELLYFIN_USER_ALIASES` | in | display names (not in .env.example), no credential |
| `OMDB_API_KEY` | in | Metacritic pill, read-only lookups |
| `QUIET_MBPS` | in | a number on the Quiet mode row; nothing is sent without QBIT_* |
| `FULL_MBPS` | in | a number on the Full speed confirm; nothing is sent without QBIT_* |
| `NAS_SLEEP_WINDOW` | in | words on the Quiet mode row |
| `TUNNEL_TOKEN` | out | routes the domain; cloudflared only |
| `COMPOSE_PROFILES` | out | the main stack's profiles; nothing for the preview |
| `CLOUDFLARE_API_TOKEN` | out | DNS write (edge.env, swag and ddns only) |
| `STAGING` | out | certificate flag (edge.env, swag only) |
| `ICS_URL_YOU` | out | connectors only; the URL is the credential |
| `ICS_URL_HER` | out | connectors only; the URL is the credential |
| `JELLYFIN_API_KEY` | out | write: Continue watching marks watched / unwatched / reset on the live Jellyfin (rule 7) |
| `JELLYFIN_POSTER_API_KEY` | out | write: the JY-260 poster write-back (uploads, locks, reverts Jellyfin images); a secret |
| `MEDIA_STATUS_HOST` | out | connectors only |
| `RADARR_URL` | out | write: search, quality, unmonitor, grab |
| `RADARR_API_KEY` | out | write: search, quality, unmonitor, grab |
| `SONARR_URL` | out | write: search, quality, unmonitor, grab |
| `SONARR_API_KEY` | out | write: search, quality, unmonitor, grab |
| `JELLYSEERR_URL` | out | write: requests, Follow, remove request |
| `JELLYSEERR_API_KEY` | out | write: requests, Follow, remove request |
| `QBIT_URL` | out | write: Quiet mode sets the download cap |
| `QBIT_USER` | out | write: Quiet mode sets the download cap |
| `QBIT_PASS` | out | write: Quiet mode sets the download cap |
| `WUD_URL` | out | write: update triggers |
| `WUD_USER` | out | write: update triggers |
| `WUD_PASS` | out | write: update triggers |
| `STACKCTL_URL` | out | write: restarts the media stack |
| `STACKCTL_TOKEN` | out | write: restarts the media stack (root-equivalent) |
| `PROWLARR_URL` | out | connectors only; admin key |
| `PROWLARR_API_KEY` | out | connectors only; admin key |
| `UPTIME_KUMA_URL` | out | connectors only |
| `UPTIME_KUMA_API_KEY` | out | connectors only |
| `SERVER_DISCORD_WEBHOOK` | out | write: posts to Discord |
| `MEDIA_DISCORD_WEBHOOK` | out | write: posts to Discord |
| `DIGEST_AT` | out | the digest is off in the preview |
| `DIGEST` | out | forced off in compose (Discord digest) |
| `MEDIA_FOLLOW` | out | forced off in compose (Follow requests through Seerr) |
| `MEDIA_AWARDS` | out | forced off in compose (Awards loop) |
| `AWARDS_CONTACT` | out | B.'s e-mail; the Awards loop is off |
| `MEDIA_BACKUP` | out | forced off in compose (joey-hub stays the one backup writer) |
| `MEDIA_WARMUP` | out | forced off in compose (warm-up loop) |
| `PLAY_RECORDER` | out | forced off in compose (play-history poller) |
| `PLAY_POLL_SECONDS` | out | the play recorder is off |
| `META_CACHE_DIR` | out | set in compose to a preview-only dir |
| `JELLYFIN_LIBRARY_EVERY_S` | out | connectors only |
| `MEDIA_STATUS_HOSTS` | out | connectors only |
| `AREAS_PATH` | out | the image default; a host path would not exist in the preview |
| `HUB_DEV` | out | local dev only |
| `SUPABASE_URL` | out | parked connector |
| `SUPABASE_KEY` | out | parked connector |
| `HA_URL` | out | parked connector |
| `HA_TOKEN` | out | parked connector |
| `NAS_SHARES_ROOT` | out | parked connector |
| `PLAYER_API` | out | JY-053 player API stays off in the preview (it writes Jellyfin playback progress) |
| `JELLYFIN_PLAYER_TOKEN_YOU` | out | write: a household member's own Jellyfin token (player progress); JY-053 |
| `JELLYFIN_PLAYER_TOKEN_HER` | out | write: a household member's own Jellyfin token (player progress); JY-053 |
| `JELLYFIN_PUBLIC_URL` | out | the player's stream host; the player API is off in the preview |
