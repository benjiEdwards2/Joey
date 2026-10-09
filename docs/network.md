# Joey ↔ media stack: the shared Docker network

Review items N-09, C-13 and N-52 (2026-10-09). This page says what changed in
`deploy/docker-compose.yml`, what to change in the NAS `.env` after it deploys, and which
media-stack ports could then be closed. The port list is a checklist for B., not a change
Joey makes.

## What changed

- `hub` and `connectors` now join the media stack's compose network,
  `media-server_default`, declared in Joey's compose as `external: true`. They stay on Joey's
  own `default` network too, so `cloudflared` still reaches the hub as `http://hub:8000`.
  `cloudflared` and `macromates` are on `default` only.
- `deploy.sh` checks for the network before it builds anything. If the media stack isn't up,
  the deploy stops at the gate with `network media-server_default missing`, the tree goes
  back to the previous SHA and the live stack is left alone. Start the media stack, then run
  `deploy.sh` again.
- Because Joey's containers are attached, `docker compose down` on the media stack can't
  remove `media-server_default`. Compose warns that the network has active endpoints. A
  media-stack `up` reuses the existing network. To fully recreate it, stop Joey first.

Until the `.env` changes below, nothing behaves differently: the `*_URL` keys still point at
the LAN IP, and that path keeps working.

## NAS `.env` after the deploy

Switch these to service names. Each one is used only for server-side calls, so no link a
phone opens is built from it.

| Key | Service-name value | Note |
|---|---|---|
| `JELLYFIN_URL` | `http://jellyfin:8096` | Server-side only. The Jellyfin launcher link comes from `config/areas.yaml`. |
| `RADARR_URL` | `http://radarr:7878` | |
| `SONARR_URL` | `http://sonarr:8989` | |
| `UPTIME_KUMA_URL` | `http://uptime-kuma:3001` | |
| `WUD_URL` | `http://wud:3000` | This is the container port. On the LAN, WUD is published on 3030. |
| `QBIT_URL` | `http://gluetun:8080` | qBittorrent runs in gluetun's network namespace, so its name is gluetun's. |
| `PROWLARR_URL` | `http://gluetun:9696` | Same as qBittorrent. |
| `JELLYSEERR_URL` | `http://jellyseerr:5055`, **but hold for now** | See below. |

**Hold `JELLYSEERR_URL`.** It also builds two links people click: the "Open in Jellyseerr"
button on a film page (`hub/media_discover.py`, `jellyseerr_href`) and each request row's
`href` in the `jellyseerr` snapshot. With a service name, those links stop working from a
browser. Keep it on the LAN IP until the link base is split from the API base. That is a
follow-up for the hub and connector code.

The app probes (`media_status`) work the same way. `MEDIA_STATUS_HOST` keeps the LAN host,
because every card link is built from it plus the published port. Add `MEDIA_STATUS_HOSTS`
to change only where each app is probed:

```
MEDIA_STATUS_HOSTS=jellyfin=jellyfin,radarr=radarr,sonarr=sonarr,jellyseerr=jellyseerr,qbittorrent=gluetun,prowlarr=gluetun,uptime_kuma=uptime-kuma,wud=wud:3000
```

The format is `app=host[:port]`, comma-separated. The port defaults to the app's published
port, so it is needed only when the container port differs, as WUD's does. Apps left out
(`portainer`, `adm`, `homepage`) are still probed on the LAN host. ADM is the NAS itself.
Portainer and Homepage can be added only if they are on `media-server_default`.

To check after the change: the Server page shows every app Up, and
`docker compose logs connectors` shows `sweep ok=… err=0`.

## Media-stack ports that could then be closed (checklist for B.)

The media stack's own compose publishes these ports on `0.0.0.0`. Once Joey uses service
names, Joey no longer needs any of them. Close a port only if you don't open that app from
the LAN or Tailscale yourself:

- [ ] `jellyseerr 5055`: only after `JELLYSEERR_URL` is switched (see above).
- [ ] `uptime-kuma 3001`
- [ ] `radarr 7878`
- [ ] `sonarr 8989`
- [ ] `gluetun 8080` (qBittorrent web UI) and `9696` (Prowlarr)
- [ ] `portainer 9000`: plain HTTP, with read-write `docker.sock`. Keep `9443` (HTTPS) only.
  The Portainer link in `config/areas.yaml` and on the Server card is `http://…:9000`, so it
  breaks too and would need to move to `https://…:9443`.

Keep `jellyfin 8096`: the Jellyfin launcher and TV apps use it. Closing a port breaks every
LAN bookmark to it, and the `media_status` card link for that app (built from
`MEDIA_STATUS_HOST`) goes dead too. For admin UIs you keep, consider binding them to the
LAN or Tailscale IP rather than `0.0.0.0` (N-52).
