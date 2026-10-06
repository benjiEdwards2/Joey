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
