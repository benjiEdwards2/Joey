# Public edge: jellyfin.joeyhome.net

Joey TV WP-A3 (2026-10-18). Friends' TVs reach Jellyfin directly through one nginx (SWAG), not through Cloudflare Access
and not through the hub. This page says what exists in the repo and how to run it. Everything is **dark** until B. sets
`COMPOSE_PROFILES=edge` on the NAS (WP-A4) and the router forwards 443 (WP-A5). Requirements: R4-E1…E9 in the Joey TV
MASTER_PLAN.

## Request path

```
friend TV -> router :443 -> NAS host :443 = joey-swag's nginx (host network) -> 127.0.0.1:8096 -> docker-proxy -> jellyfin
```

- `media.joeyhome.net` is **not** on this path. It is tunnel-routed (Cloudflare) and arrives in Phase B.
- SWAG answers one name, `jellyfin.joeyhome.net` (`deploy/swag/proxy-confs/jellyfin.subdomain.conf`). Every other Host,
  SNI or bare IP hits the catch-all in `deploy/swag/site-confs/default.conf` and gets nginx 444 (connection closed).
- The upstream is `http://127.0.0.1:8096`, Jellyfin's published port on loopback, and the only `proxy_pass` target nginx
  has. It is the one IP-literal upstream the Joey TV plan allows (rule 14's host-mode exception; it changes in "Move
  Jellyfin to another host" anyway). `/metrics` returns 404. There is no port 80 (nothing listens on it) and no
  `listen [::]` or QUIC anywhere.
- AU + NZ only (file name is historical): `deploy/swag/site-confs/00-geo-au.conf` sets `$joey_country` from the db-ip database (downloaded by the
  `swag-dbip` mod) and allows AU and NZ plus 192.168.0.0/16, 10.0.0.0/8 and 127.0.0.1/32 (loopback: `deploy.sh`'s smoke
  curl). Anyone else gets 403, including any 172.x address. The variable names are our own so they cannot collide with
  the mod's own geoip2 block.
- TLS: a Let's Encrypt wildcard `*.joeyhome.net` (DNS-01 through Cloudflare, `ONLY_SUBDOMAINS=true`). No `EMAIL` key:
  Let's Encrypt stopped expiry e-mails in 2025, so Kuma's certificate-expiry notification replaces them.

## Network mode: (a) host

`joey-swag` runs with `network_mode: host` (Q44 mode (a), WP-A4, 2026-10-19). It has no `ports:` and joins no Docker
network: nginx binds the NAS's own port 443 and accepts each connection itself, so `$remote_addr` is the real client IP.
No service in `deploy/docker-compose.yml` publishes a port.

**Why not bridge mode.** WP-A3 was built in bridge mode (`0.0.0.0:443:443` on the `joey-edge` network) after WP0's probe
saw a real LAN address on a published port. WP-A4 found that this only holds sometimes. dockerd runs `--iptables=false`
on this NAS. The nftables DNAT rule that keeps the client IP on a published port (`table ip Asustor_Firewall_V4`, chain
`DOCKER_NAT`) is written by ADM Defender (`defenderd`, which listens to docker events), not by dockerd. A container
started seconds after another container stops gets no rule. It then falls back to userland docker-proxy, which
re-sources every client as the bridge gateway (172.31.250.1). `deploy.sh` recreates hub and connectors in the same
`up`, so `joey-swag` never got its 443 rule, and geo (172.16/12 was allowed) and fail2ban (172.16/12 was ignored) were
silently void. When Defender later re-applied its profile while swag was running, swag did get its rule, so bridge mode
can work, but not deterministically after a deploy. Host mode removes the dependency on Defender entirely.

- **Jellyfin Known proxies = `172.31.250.1, 172.18.0.1`** (Dashboard, Networking; B. sets it). swag reaches Jellyfin
  through `127.0.0.1:8096`, a published port, and docker-proxy carries loopback connections into the container from
  the gateway of the network it targets. While jellyfin stays attached to `joey-edge`, docker-proxy targets its
  `joey-edge` address (172.31.250.2), so Jellyfin sees **172.31.250.1**. If jellyfin is ever detached from `joey-edge`,
  docker-proxy targets its `media-server_default` address and Jellyfin sees **172.18.0.1**. Both are listed so the
  `X-Forwarded-For` nginx sets stays trusted either way. The earlier value `172.31.250.0/29` covers only the first.
- **`joey-edge` stays on the NAS** (`172.31.250.0/29`, created by `nas_scripts/jellyfin_edge_net.sh`), with jellyfin
  attached. Joey's compose no longer declares or uses it, and `deploy.sh` no longer checks it. Leave it as it is: the
  first Known-proxies value depends on it.
- **Port 443 on the host:** ADM reserves 443 for its own web server (`serviceport.conf`, `HttpsPort = 443`), although
  nothing listens there today. **ADM's HTTPS must stay off on 443** (ADM Web Center / web server). If ADM ever binds 443,
  nginx cannot start, and the edge is down until one of them moves.
- **Residual isolation risk (recorded for Phase A):** in the host network namespace swag can reach every bridge address,
  `joey-hub`'s included. Isolation rests on nginx having exactly one upstream (pinned offline by
  `tests/deploy/test_edge.py`), `joey-hub` publishing no host port, and Q25b JWT verification, which only arrives in
  Phase B (WP-B5). An exploited swag sits in the host namespace with `NET_ADMIN`.
- The internet-sourced client IP is re-checked at WP-A5 G4/G5 (geo, fail2ban) before any friend is invited. If
  `docker exec joey-swag tail -n 3 /config/log/nginx/access.log` shows a 172.x or 127.0.0.1 address for a request from
  outside, close the forward at once (see "Kill switch") and reopen the network-mode question.

## Compose profiles

| Profile | Service | Starts when |
|---|---|---|
| `edge` | `joey-swag` (`lscr.io/linuxserver/swag:5.8.0-ls490`) | `COMPOSE_PROFILES=edge` in the NAS `deploy/.env` |
| `ddns` | `joey-ddns` (`favonia/cloudflare-ddns:1.17.1`, only `jellyfin.joeyhome.net`, `PROXIED=false`, `IP6_PROVIDER=none`, every 5 min) | `COMPOSE_PROFILES=edge,ddns`. **Never enabled while the WAN IP is static** (Q3). It is built and tested for a future IP change. |

Compose reads `COMPOSE_PROFILES` from `deploy/.env`. Unset, both stay dark and a deploy behaves exactly as before.
Images are pinned (manual updates only; `joey-*` containers are held from WUD). When swag is running, `deploy.sh`'s
smoke step runs `nginx -t`, `nginx -s reload` and a `/health` curl to `127.0.0.1:443` from a host-network curl container
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
   service, validates, recreates jellyfin (streams drop for about 30 s). Then set Jellyfin's Known proxies
   (`172.31.250.1, 172.18.0.1`, see "Network mode"). swag itself does not use `joey-edge` in host mode.
2. `append_env.sh /volume1/Docker/joey/life-dashboard/deploy/edge.env`: creates `edge.env` (mode 600) and appends the
   `CLOUDFLARE_API_TOKEN` line from `/tmp/joey_env.txt`.
3. `edge_cf_ini.sh --staging`: writes `cloudflare.ini` (1000:1000, mode 600) **before swag's first start** (SWAG's init
   runs after certbot) and adds `STAGING=true` to `edge.env`.
4. Set `COMPOSE_PROFILES=edge` in `deploy/.env`, run `deploy.sh`. Check the staging certificate, drop `STAGING`, restart
   swag for the production certificate.

Checks that only run live (WP-A4): `nginx -t` with our geoip2 block beside the dbip mod's, certbot DNS-01,
`fail2ban-regex` and iptables bans on the ADM kernel (in host mode they land in the host's own network namespace), the
`:ro` file binds against the linuxserver init, and a host-side `/health` curl arriving from 127.0.0.1, which the geo
gate allows. In host mode nginx must be the only listener: `docker exec joey-swag nginx -T 2>/dev/null | grep -E
'^\s*listen'` shows only `443 ssl` lines (nothing on 80). The image's other nginx confs have no listener (SWAG 5.8.0-ls490
`nginx.conf` none; Alpine's `http.d/default.conf` is deleted in the base image; samples end in `.sample` and are not
included), so a stray one could only come from an extra file in `/volume1/Docker/joey/swag/nginx/`.
`/config/nginx/resolver.conf` may still hold Docker's bridge-mode resolver (127.0.0.11), which does not exist on the
host network. Nothing uses it while the upstream is a literal IP; delete the file and restart swag to regenerate it
from the host's `/etc/resolv.conf` if a named upstream is ever added.

## Geo and fail2ban

- **Geo:** see "Request path". The geo gate returns 403 before anything reaches Jellyfin.
- **fail2ban** (`deploy/swag/fail2ban/jail.local`, filter `jellyfin-auth.local`): jail `jellyfin-auth` bans an address
  for 3600 s after 5 failed sign-ins in 600 s. A failed sign-in is a **401 to `POST /Users/AuthenticateByName` or
  `POST /Users/AuthenticateWithQuickConnect`** in SWAG's access log (`/config/log/nginx/access.log`), so it needs the real
  client IP there. A GET 401 or a 200 never matches. The LAN and loopback are never banned (`ignoreip` =
  10.0.0.0/8, 192.168.0.0/16, 127.0.0.1/32, the geo gate's local set).
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

1. **Upstream:** in `deploy/swag/proxy-confs/jellyfin.subdomain.conf` change both `proxy_pass` lines from
   `http://127.0.0.1:8096` to a **LAN DNS name** (router or ADM hostname, **never an IP**). Keep it the only `proxy_pass`
   target. A name needs a resolver that works on the host network (see the `resolver.conf` note under "First
   bring-up"). `tests/deploy/test_edge.py` pins the single upstream, so update that test in the same change with a
   dated DECISIONS line.
2. **Known proxies:** in Jellyfin (Dashboard, Networking) set Known proxies to the NAS LAN address, the host swag now
   connects from, instead of `172.31.250.1, 172.18.0.1`.
3. **URLs:** update `JELLYFIN_URL` in `deploy/.env` **and** in `deploy/media.env` (the NAS-only env file the Phase B
   media service reads; it does not exist yet in WP-A3), then recreate hub and connectors.
4. **`joey-edge`:** drop it on the NAS (undo `jellyfin_edge_net.sh`'s edit of the media compose, then remove the
   network) once swag reaches the new host over the LAN. Joey's compose and `deploy.sh` no longer refer to it.
5. **Kuma:** update the monitors that target Jellyfin and the edge name.
6. Deploy (`deploy.sh`), then re-run WP-A5 G2/G4/G5 (outside reachability, geo, fail2ban with the real client IP).
