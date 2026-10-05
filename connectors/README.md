# connectors

Hourly data connectors. The hub<->connector contract is `schema/envelope.schema.json` — FROZEN at WP0 (D13).

Media feeds: `jellyfin` (now playing, up next, recent; rows carry `jf_id`, data carries `server_id`,
plus a `her` block for `JELLYFIN_USER_HER`), `media_status`, `arr`, `jellyseerr`. Field detail in
`docs/connector-contract.md`.
