# config

Area registry, sample snapshots, and other committed configuration.

`areas.yaml` also carries `gated_hrefs:` (2026-10-09): app / tile id → its Cloudflare-gated https hostname.
Server cards and link tiles use it; any other LAN-only link renders as a plain "LAN" card. Hostnames live here, not in
hub code.
