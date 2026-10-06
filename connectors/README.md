# connectors

Hourly data connectors. The hub<->connector contract is `schema/envelope.schema.json` — FROZEN at WP0 (D13).

Media feeds: `jellyfin` (now playing, up next, recent; rows carry `jf_id`, data carries `server_id`,
plus a `her` block for `JELLYFIN_USER_HER`; optional `movies`/`shows` library arrays, 2026-10-06), `media_status`, `arr` (rows carry optional `at`), `jellyseerr`. Field detail in
`docs/connector-contract.md`.
Jellyfin episode rows also carry optional `show_key`/`season_key`/`episode_key`, `season`, `episode`, `show_title` (2026-10-06).
`qbittorrent` (2026-10-06): read-only torrent list (active, finished today, seeding, totals) on the 2-minute fast loop with `jellyfin`, `media_status` and `arr`; env `QBIT_URL`, `QBIT_USER`, `QBIT_PASS`.

Server feeds (2026-10-06, WP-S1): `system` (NAS CPU, RAM, uptime, per-volume space; on the 2-minute fast loop) and
`wud` (What's Up Docker container image updates; hourly). WP-S1 ships ids, schemas, fixtures and transforms only — the
live `fetch()` of each raises `NotImplementedError` (an error envelope, "Not connected" in the hub) until WP-S2 (`system`)
and WP-S3 (`wud`) land. Raw shapes they must return are documented above each class in `stubs.py`.

`system` live fetch (WP-S2, 2026-10-06): no env vars, no secrets. CPU % from two `/proc/stat` reads 1 s apart; RAM from
`/proc/meminfo` (MemTotal / MemAvailable); `/proc/uptime`; `/proc/loadavg` (null if unreadable) — all host-wide from inside
the container. Volume space is `os.statvfs` on each path in `SYSTEM_VOLUMES` (comma-separated, default `/host/volume1`),
set in `deploy/docker-compose.yml` with the read-only bind `/volume1:/host/volume1:ro`; the `/host` prefix is stripped
for display. Unreadable `/proc` or an unstattable volume is an error envelope naming the file/path — never made-up numbers.

`media_status` probe list (WP-S2, 2026-10-06) adds `wud` (3030), `adm` (8000, Asustor ADM; a 30x redirect to https
counts as Up — redirects are never followed) and `homepage` (3000). `gluetun` is never probed (its control port is not
published): it is Up iff `prowlarr` or `qbittorrent` answers, since both route through it.

`wud` live (WP-S3): one HTTP Basic `GET {WUD_URL}/api/containers` (10 s), the list returned unchanged; env `WUD_URL`,
`WUD_USER`, `WUD_PASS`. A digest-only update reads `kind: "digest"`, `new_tag: null`.
`arr` counts (WP-S3): optional `radarr {movies, wanted, missing, queued}`, `sonarr {series, wanted, queued}` and
`prowlarr {grabs, queries, failed_grabs, failed_queries, indexers}` (optional env `PROWLARR_URL`, `PROWLARR_API_KEY`).
Each is partial-ok — null when its call fails or (Prowlarr) its env is unset; the rest of `arr` stays `ok`.
