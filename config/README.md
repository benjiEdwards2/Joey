# config

Area registry, sample snapshots, and other committed configuration.

`areas.yaml` also carries `gated_hrefs:` (2026-10-09): app / tile id → its Cloudflare-gated https hostname.
Server cards and link tiles use it; any other LAN-only link renders as a plain "LAN" card. Hostnames live here, not in
hub code.

Tile field `show_media_releases` (E5, 2026-10-13; default `false`): on a tile reading the `gcal` snapshot, its Next 7 days
list also shows the `arr` snapshot's coming releases (monitored films; episodes of shows watched in the last 30 days, in
progress or followed) as their own "Media" rows, while some tile reads `arr`. On for the Calendar's `next-event` tile.
