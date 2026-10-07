# Service logos (Server area, WP-U3, 2026-10-07)

Logos for the `/server` Services card grid, keyed in `hub/server.py` `SERVICE_LOGOS` (app id → file).
Served by the hub's `/static` route with `?v={{ static_v }}`. Each SVG was checked on import: starts with
`<svg`, under 200 KB, no `<script>`, no event-handler attributes, no external `href`.

Source: [homarr-labs/dashboard-icons](https://github.com/homarr-labs/dashboard-icons), fetched 2026-10-07 from
`https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/<svg|png>/<name>`. That project's licence is
**Apache-2.0** (its `LICENSE` file — not MIT). The logos themselves remain the trademarks of their owners and are
used here only to identify the services on a private dashboard.

| App id | File | Upstream name |
|---|---|---|
| jellyfin | `jellyfin.svg` | `svg/jellyfin.svg` |
| jellyseerr | `jellyseerr.svg` | `svg/jellyseerr.svg` |
| radarr | `radarr.svg` | `svg/radarr.svg` |
| sonarr | `sonarr.svg` | `svg/sonarr.svg` |
| prowlarr | `prowlarr.svg` | `svg/prowlarr.svg` |
| qbittorrent | `qbittorrent.svg` | `svg/qbittorrent.svg` |
| gluetun | `gluetun.svg` | `svg/gluetun.svg` |
| portainer | `portainer.svg` | `svg/portainer.svg` |
| uptime_kuma | `uptime-kuma.svg` | `svg/uptime-kuma.svg` |
| wud | `wud.svg` | `svg/whats-up-docker.svg` (`wud.svg` does not exist upstream) |
| adm | `adm.svg` | `svg/asustor.svg` (Asustor ADM) |
| homepage | `homepage.png` | `png/homepage.png` (494×512; dashboard-icons has no Homepage SVG) |

Adding an app to `MEDIA_APPS` (connectors/stubs.py): add its logo here + to `SERVICE_LOGOS`, or list it in
`NO_LOGO` (it then renders a neutral initial-letter tile) — `tests/hub/test_server_cards.py` fails otherwise.
