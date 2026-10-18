# Public edge: jellyfin.joeyhome.net

Joey TV WP-A3 (2026-10-18). Friends' TVs reach Jellyfin directly through one nginx (SWAG), not through Cloudflare Access
and not through the hub. This page says what exists in the repo and how to run it. Everything is **dark** until B. sets
`COMPOSE_PROFILES=edge` on the NAS (WP-A4) and the router forwards 443 (WP-A5). Requirements: R4-E1…E9 in the Joey TV
MASTER_PLAN.

## Request path

```
friend TV -> router :443 -> NAS 0.0.0.0:443 -> joey-swag -> jellyfin:8096   (joey-edge network)
```

- `media.joeyhome.net` is **not** on this path. It is tunnel-routed (Cloudflare) and arrives in Phase B.
- SWAG answers one name, `jellyfin.joeyhome.net` (`deploy/swag/proxy-confs/jellyfin.subdomain.conf`). Every other Host,
  SNI or bare IP hits the catch-all in `deploy/swag/site-confs/default.conf` and gets nginx 444 (connection closed).
- The upstream is `jellyfin:8096` **by name**, the only `proxy_pass` target nginx has. `/metrics` returns 404. There is
  no port 80 (not published, not listened on) and no `listen [::]` or QUIC anywhere.
- AU + NZ only (file name is historical): `deploy/swag/site-confs/00-geo-au.conf` sets `$joey_country` from the db-ip database (downloaded by the
  `swag-dbip` mod) and allows AU and NZ plus the private ranges 192.168.0.0/16, 10.0.0.0/8 and 172.16.0.0/12. Anyone else gets
  403. The variable names are our own so they cannot collide with the mod's own geoip2 block.
- TLS: a Let's Encrypt wildcard `*.joeyhome.net` (DNS-01 through Cloudflare, `ONLY_SUBDOMAINS=true`). No `EMAIL` key:
  Let's Encrypt stopped expiry e-mails in 2025, so Kuma's certificate-expiry notification replaces them.

## Network mode: (b) bridge

WP0 probe (k) (2026-10-18): a published port on this NAS logged the client's real LAN address, not a 172.x address, so
the real client IP survives docker-proxy. That chose bridge mode: `joey-swag` publishes `0.0.0.0:443:443` (the only
published port in `deploy/docker-compose.yml`) and joins one network, `joey-edge`, shared with `jellyfin` and nothing
else (not the hub, not Kuma, not `media-server_default`).

- `joey-edge` is `172.31.250.0/29`. It is **external**: created by `nas_scripts/jellyfin_edge_net.sh`, never by Joey's
  compose (a project-owned network would be `deploy_joey-edge`, and `down` or a rollback would fail while jellyfin is
  attached).
- Jellyfin Dashboard, Networking, **Known proxies = 172.31.250.0/29**, so the `X-Forwarded-For` nginx sets is trusted
  and Jellyfin logs the real client. B. sets this at WP-A4.
- The probe was LAN-sourced. The internet-sourced client IP is re-checked at WP-A5 G4/G5 (geo, fail2ban) before any
  friend is invited. If `docker exec joey-swag tail -n 3 /config/log/nginx/access.log` shows a 172.x address for a
  request from outside, close the forward at once (see "Kill switch") and reopen the network-mode question.

## Compose profiles

| Profile | Service | Starts when |
|---|---|---|
| `edge` | `joey-swag` (`lscr.io/linuxserver/swag:5.8.0-ls490`) | `COMPOSE_PROFILES=edge` in the NAS `deploy/.env` |
| `ddns` | `joey-ddns` (`favonia/cloudflare-ddns:1.17.1`, only `jellyfin.joeyhome.net`, `PROXIED=false`, `IP6_PROVIDER=none`, every 5 min) | `COMPOSE_PROFILES=edge,ddns`. **Never enabled while the WAN IP is static** (Q3). It is built and tested for a future IP change. |

Compose reads `COMPOSE_PROFILES` from `deploy/.env`. Unset, both stay dark and a deploy behaves exactly as before.
Images are pinned (manual updates only; `joey-*` containers are held from WUD). `deploy.sh` checks `joey-edge` exists
when the edge profile is on, and its smoke step runs `nginx -t`, `nginx -s reload` and a `/health` curl against swag
(see `deploy/README.md`). **Never take `edge` out of `COMPOSE_PROFILES` without the "Kill switch" runbook below:** a
deploy with the profile off may remove `joey-swag` mid-stream.

## edge.env keys

`deploy/edge.env` is NAS-only, `chmod 600`, git- and docker-ignored (`*.env`). Only `swag` and `ddns` read it (compose
`env_file`, `required: false`). The token is **not** in `deploy/.env`. Never write a value into the repo or this page.

| Key | Meaning |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token for DNS-01 (swag) and the record update (ddns). Name only here; the value lives on the NAS. |
| `STAGING` | `true` for the first certificate only (Let's Encrypt staging). Remove the line, then restart swag, for the production certificate. |

`deploy/.env.example` carries the same names as comments. SWAG's certbot reads the token from
`/volume1/Docker/joey/swag/dns-conf/cloudflare.ini`, which `edge_cf_ini.sh` writes from `edge.env`.

## First bring-up (order matters)

Scripts are in `nas_scripts/` (outside git; see its README). B. runs each on the NAS, as in WP-A4.

1. `jellyfin_edge_net.sh`: creates `joey-edge` (`172.31.250.0/29`, idempotent), adds it to the media compose's `jellyfin`
   service, validates, recreates jellyfin (streams drop for about 30 s). Then set Jellyfin's Known proxies.
2. `append_env.sh /volume1/Docker/joey/life-dashboard/deploy/edge.env`: creates `edge.env` (mode 600) and appends the
   `CLOUDFLARE_API_TOKEN` line from `/tmp/joey_env.txt`.
3. `edge_cf_ini.sh --staging`: writes `cloudflare.ini` (1000:1000, mode 600) **before swag's first start** (SWAG's init
   runs after certbot) and adds `STAGING=true` to `edge.env`.
4. Set `COMPOSE_PROFILES=edge` in `deploy/.env`, run `deploy.sh`. Check the staging certificate, drop `STAGING`, restart
   swag for the production certificate.

Checks that only run live (WP-A4): `nginx -t` with our geoip2 block beside the dbip mod's, certbot DNS-01,
`fail2ban-regex` and iptables bans on the ADM kernel, the `:ro` file binds against the linuxserver init, outbound
internet from `172.31.250.0/29` under `dockerd --iptables=false` (certbot, mods and the db-ip download need it), and a
host-side `/health` curl arriving from the `joey-edge` gateway (172.31.250.1), which is inside the allowed 172.16/12.

## Geo and fail2ban

- **Geo:** see "Request path". The geo gate returns 403 before anything reaches Jellyfin.
- **fail2ban** (`deploy/swag/fail2ban/jail.local`, filter `jellyfin-auth.local`): jail `jellyfin-auth` bans an address
  for 3600 s after 5 failed sign-ins in 600 s. A failed sign-in is a **401 to `POST /Users/AuthenticateByName` or
  `POST /Users/AuthenticateWithQuickConnect`** in SWAG's access log (`/config/log/nginx/access.log`), so it needs the real
  client IP there. A GET 401 or a 200 never matches. The LAN and Docker ranges are never banned (`ignoreip`).
- SWAG's stock **`nginx-unauthorized` jail is disabled**: it bans on any 401, and Jellyfin answers every request from a TV
  holding a stale token with 401, so it would ban friends' households.
- Live check: `docker exec joey-swag fail2ban-regex /config/log/nginx/access.log /etc/fail2ban/filter.d/jellyfin-auth.local`.

## Verify from outside

Run from a phone hotspot (not the home network, which can hairpin to the LAN address):

```
nslookup jellyfin.joeyhome.net. 1.1.1.1
curl -sI --doh-url https://cloudflare-dns.com/dns-query https://jellyfin.joeyhome.net/health
```

`nslookup` must return the home WAN address (a grey-cloud A record, no AAAA). The curl resolves through Cloudflare's
DNS-over-HTTPS, so a stale local resolver cannot mislead it; from an AU address it answers 200 `Healthy`, from anywhere
else 403. A bare-IP or wrong-Host request must close with no response (444).

## Token rotation

1. Create the new token in Cloudflare, then replace the `CLOUDFLARE_API_TOKEN` line in `deploy/edge.env` on the NAS (edit
   by hand, or remove the old line and re-run `append_env.sh <edge.env>`; keep the file `chmod 600`).
2. `edge_cf_ini.sh` (no argument): rewrites `cloudflare.ini` from `edge.env`.
3. `docker compose restart swag` in `/volume1/Docker/joey/life-dashboard/deploy`.
4. Revoke the old token in Cloudflare. If ddns is ever enabled, `docker compose restart ddns` too.

A leaked token can edit DNS for the zone: rotate at once and treat the certificate as unaffected.

## Restore

The repo confs are bind-mounted read-only, so `git` and `deploy.sh` restore them. SWAG's own state is
`/volume1/Docker/joey/swag` (certificates, `dns-conf/cloudflare.ini`, the db-ip database, logs, fail2ban's ban list). If
that folder is lost: re-run `edge_cf_ini.sh`, start swag, and certbot re-issues the wildcard from `edge.env`. Use
`STAGING=true` while testing, because production issuance is rate-limited. `edge.env` itself is NAS-only and not in git:
keep the token in B.'s password manager. (Whether `/volume1/Docker/joey/swag` is covered by any NAS backup is not
set up by WP-A3.)

## Kill switch

Runbook R3. Either step closes the public door within a minute; B. knows both before any port opens.

- **(a) Router:** B. disables the 443 port forward on the router.
- **(b) NAS:** `docker compose stop swag` in `/volume1/Docker/joey/life-dashboard/deploy`.
- **For `media.joeyhome.net`** (Phase B): delete the tunnel public hostname in Cloudflare.

Afterwards, find out why before reopening. To bring it back: `docker compose up -d swag` (or re-enable the forward).
**Never toggle `COMPOSE_PROFILES` off as a kill switch**, and never as a tidy-up: a `deploy.sh` run with the profile off
may remove `joey-swag` mid-stream (Compose handling of inactive-profile containers under `--remove-orphans` is checked
live at the first edge deploy, WP-A4 step 6). Stop swag first, then decide.

## Move Jellyfin to another host

Use when Jellyfin leaves this NAS (new box, VM). Do it in this order, and re-verify the edge after.

1. **Upstream:** in `deploy/swag/proxy-confs/jellyfin.subdomain.conf` change `$upstream_app` from `jellyfin` to a **LAN
   DNS name** (router or ADM hostname, **never an IP**). Keep it the only `proxy_pass` target. `tests/deploy/test_edge.py`
   pins the single upstream, so update that test in the same change with a dated DECISIONS line.
2. **Known proxies:** in Jellyfin (Dashboard, Networking) set Known proxies to the NAS address, the host swag now
   connects from, instead of `172.31.250.0/29`.
3. **URLs:** update `JELLYFIN_URL` in `deploy/.env` **and** in `deploy/media.env` (the NAS-only env file the Phase B
   media service reads; it does not exist yet in WP-A3), then recreate hub and connectors.
4. **`joey-edge`:** drop it (compose network, the `networks:` entry in `docker-compose.yml`, `jellyfin_edge_net.sh`'s
   edit of the media compose, and the `deploy.sh` network check), once swag reaches the new host over the LAN.
5. **Kuma:** update the monitors that target Jellyfin and the edge name.
6. Deploy (`deploy.sh`), then re-run WP-A5 G2/G4/G5 (outside reachability, geo, fail2ban with the real client IP).
