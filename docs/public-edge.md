# Public edge: jellyfin.joeyhome.net

Joey TV WP-A3 (2026-10-18). Friends' TVs reach Jellyfin directly through one nginx (SWAG), not through Cloudflare Access
and not through the hub. This page says what exists in the repo and how to run it. Everything is **dark** until B. sets
`COMPOSE_PROFILES=edge` on the NAS (WP-A4) and the router forwards external 8443 to NAS 443 (WP-A5). Requirements: R4-E1…E9 in the Joey TV
MASTER_PLAN.

## Request path

```
friend TV -> router external :8443 -> NAS host :443 = joey-swag's nginx (host network) -> 127.0.0.1:8096 -> docker-proxy -> jellyfin
```

- **Why 8443 outside.** The public address is `https://jellyfin.joeyhome.net:8443`, not :443. The TP-Link Deco X50 router
  drops external TCP 80 and 443 before they reach the NAS (they are the Deco's own web/API ports), while external 8443
  forwards fine, so the router's only forward is external 8443 -> NAS 443. Nothing on the NAS changes: SWAG still
  listens on 443, and the LAN and loopback checks keep using 443. Two consequences: a TLS grader must be port-capable
  (SSL Labs only tests 443), and client apps (the official Jellyfin app, the TV shell) need the `:8443` in the server
  address.
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
  `tests/deploy/test_edge.py`), `joey-hub` publishing no host port, and Q25b JWT verification (live since WP-A6a, 2026-10-21; forged-header probes get 401).
  Residual: replay of a captured token within its lifetime, and compromise of the hub container. An exploited swag sits in the host namespace with `NET_ADMIN`.
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
(see `deploy/README.md`). The six repo confs are single-file `:ro` binds, so a running swag sees new conf only after a
recreate: while the edge profile is on, `deploy.sh` force-recreates swag only when the deploy changed a file under
`deploy/swag/` (or on `--force`; the rollback uses the same diff), and a manual conf change outside `deploy.sh` needs `docker compose up -d --force-recreate swag`, not `nginx -s reload`. **Never take `edge` out of `COMPOSE_PROFILES` without the "Kill switch" runbook below:** a
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
In host mode SWAG's bundled php-fpm (stock pool `listen = 127.0.0.1:9000`) clashed with Portainer's published host 9000
("Address in use (98)" every second, WP-A5): `deploy/swag/php/www2.conf`, bound `:ro` to `/config/php/www2.conf` (the base
image's pool override, included after `php-fpm.d/*.conf`), moves the `[www]` pool to the unix socket `/var/run/php-fpm.sock`.

## Geo and fail2ban

- **Geo:** see "Request path". The geo gate returns 403 before anything reaches Jellyfin.
- **fail2ban** (`deploy/swag/fail2ban/jail.local`, filter `jellyfin-auth.local`): jail `jellyfin-auth` bans an address
  for 3600 s after 5 failed sign-ins in 600 s. A failed sign-in is a **401 to `POST /Users/AuthenticateByName` or
  `POST /Users/AuthenticateWithQuickConnect`** in SWAG's access log (`/config/log/nginx/access.log`), so it needs the real
  client IP there. A GET 401 or a 200 never matches. The LAN and loopback are never banned (`ignoreip` =
  10.0.0.0/8, 192.168.0.0/16, 127.0.0.1/32, the geo gate's local set).
- SWAG's stock **`nginx-unauthorized` jail is disabled**: it bans on any 401, and Jellyfin answers every request from a TV
  holding a stale token with 401, so it would ban friends' households.
- Bans are **DROP** rules in the host's nft `ip filter` table (`nft list chain ip filter f2b-jellyfin-auth` shows them);
  REJECT is unsupported on the ADM kernel (iptables-nft "Extension REJECT revision 0 not supported").
- Live check: `docker exec joey-swag fail2ban-regex /config/log/nginx/access.log /etc/fail2ban/filter.d/jellyfin-auth.local`.

## Verify from outside

Run from a phone hotspot (not the home network, which can hairpin to the LAN address):

```
nslookup jellyfin.joeyhome.net. 1.1.1.1
curl -sI --doh-url https://cloudflare-dns.com/dns-query https://jellyfin.joeyhome.net:8443/health
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

## Restore media.db

Joey TV WP-A6b (2026-10-20). Friends' plays live in `media.db`, so one copy leaves the house: `deploy/media_offsite.sh`
encrypts the newest `media-*.db.gz` from `/volume1/Docker/joey/backups/media/` (and nothing else) to a public age key
and pushes it to the private repo `benjiEdwards2/joey-offsite-backup` as `media/<dump>.age`, keeping the newest 14.
It runs on the NAS host as root (`sh deploy/media_offsite.sh`, or `--dry-run` to see the one file it would send);
the optional cron hook is `nas_scripts/media_offsite_cron.sh`. The age private key is in B.'s password manager ("Joey
media.db offsite key") and in `/volume1/Docker/joey/secrets/` on the NAS; the script never reads it. The drill uses the
password-manager copy, because that is the one left if the NAS dies. Any Docker host works; this is the NAS form.

1. Laptop (Git Bash): fetch the newest ciphertext, and save the password-manager key file as `$TEMP/offsite.key`.
   ```
   N=$(gh api repos/benjiEdwards2/joey-offsite-backup/contents/media --jq '.[].name' | sort | tail -n 1)
   gh api -H 'Accept: application/vnd.github.raw' "repos/benjiEdwards2/joey-offsite-backup/contents/media/$N" > "$TEMP/$N"
   ssh root@192.168.68.59 'mkdir -m 700 /tmp/mediarestore'
   scp "$TEMP/$N" "$TEMP/offsite.key" root@192.168.68.59:/tmp/mediarestore/
   ```
2. NAS: decrypt and unpack in a throwaway container, then check it read-only.
   ```
   docker run --rm -v /tmp/mediarestore:/r alpine:3.24.2 sh -c \
     'apk add -q --no-cache age; age -d -i /r/offsite.key -o /r/media.db.gz /r/media-*.age && gunzip /r/media.db.gz'
   docker run --rm -v /tmp/mediarestore:/r:ro python:3.12-alpine python -c "import sqlite3; c=sqlite3.connect('file:/r/media.db?mode=ro', uri=True); print(c.execute('pragma integrity_check').fetchone()[0]); print(c.execute('select owner, count(*) from play group by owner').fetchall())"
   ```
   Pass: `ok`, and the owner counts include the `jf:` rows (compare with the live `media.db`).
3. Delete every temp copy: `ssh root@192.168.68.59 'rm -rf /tmp/mediarestore'` and `rm "$TEMP/$N" "$TEMP/offsite.key"`.

Lessons from the 2026-10-20 drills (the on-NAS restore drill and this off-box decrypt drill both passed, `integrity_check = ok`):

- The terminal is Windows PowerShell 5.1: the Git Bash lines above (`&&`, `$TEMP`, `$(...)`) do not paste there, and `$env:TEMP` can be empty in the Claude terminal panel, so use full paths.
- In the container, `apk add age; age -d ...` needs the `;`, not `&&`: the apk busybox trigger can print `killed by signal 9`, which is harmless, but `&&` would stop the chain before decrypting.
- The key file must be the real key (its first line is `AGE-SECRET-KEY-1...`, or `#` comment lines above it). A stray clipboard value, such as the deploy public key, gives `unknown identity type`.
- Notepad adds `.txt` to a saved file: name the key file explicitly (`offsite.key`) and check the saved name.
- Clean up strictly AFTER the integrity check (step 3 last). Deleting first, as happened once, loses the copy being checked.
- The first run pulls `alpine:3.24.2` (about 8 MB) and `python:3.12-alpine` (about 50 MB) from Docker Hub: needs B.'s go (rule 15).
- Compare the owner counts with the live `JfPlays` (R0): the dump is hours old, so live is equal or a little higher. A restored count HIGHER than live means something deleted rows since: stop and tell Claude.
- A real restore stops `hub` and `connectors` first (they write `media.db`), moves the damaged file aside rather than deleting it, and brings them straight back up: `joeyhome.net` is down while hub is stopped.

For a real restore, put the decrypted `media.db` back the same way as an on-NAS dump (runbook R5).

## Kill switch

Runbook R3. Either step closes the public door within a minute; B. knows both before any port opens.

- **(a) Router:** B. disables the router's 8443 forward (external 8443 -> NAS 443).
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

## R0 helpers

Joey TV WP-A6 (2026-10-20). Operations runbooks R0, R1, R2, R4 and F7 follow, in that order. R3 is "Kill switch" above and R5 is "Restore media.db" above.
Every runbook uses the three PowerShell functions below. They exist because the reads need quotes that PowerShell 5.1 mangles when typed inline.
Each pipes a small Python script over SSH into `joey-hub` (which holds the Jellyfin API key and reaches `jellyfin:8096` by name). They are **read-only**: only booleans, counts and ids are printed,
never names, IPs or keys. They use the header `Authorization: MediaBrowser Token="..."`; Jellyfin 12.2.0 answers 401 to `X-Emby-Token` (MASTER_PLAN rule 21).

**Tested live 2026-10-20 in PowerShell 5.1: all three paste and run cleanly; `JfSessions` and `JfPlays` printed the expected output.** `JfUser` needs the **full 32-hex user id**; a truncated id gives an HTTP 400 traceback.

### Conventions used by R1 to F7

- Public URL is always `https://jellyfin.joeyhome.net:8443`. The router forwards external 8443 to NAS 443; external 80/443 are dead. LAN and `--resolve` checks use 443.
- **The terminal is Windows PowerShell 5.1.** No `&&` (use `;`, or separate lines), no `$(...)` in a double-quoted `ssh` string (use single quotes so the NAS expands it), and `$env:TEMP` can be empty in the Claude terminal panel, so use full paths.
  Commands wrapped as `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "<cmd>"` work; docker exists only on the NAS.
- Copy files to the NAS with `scp`, not a `tr | ssh` pipe (PowerShell 5.1 pipes mangle the bytes). Delete a temp copy only AFTER the integrity check passes.
- Friend template: `MaxActiveSessions = 2`, lockout 10, 20 Mbps cap. The household **alias** user is `MaxActiveSessions = 0` (unlimited), set by hand (or `nas_scripts\jellyfin_set_max_sessions.py <id> 0`); **never run `joeytest_policy.py` on the alias.**
- **The admin user is refused on the public `:8443` address, even from home** (admin remote access is off, and hairpin NAT presents a home client as the router's WAN IP). The admin uses the LAN address `http://192.168.68.59:8096`.
  Every friend-path test (Quick Connect, playback, sessions, revoke) uses **joeytest** on the public address, never the admin.
- TV platforms: Android TV / Google TV only. Fire TV is untested. Samsung households use a Google TV stick.
- **The first real friend invite is blocked until the dated line "Q25b LIVE in Phase A (WP-A6a)" exists in the Joey TV DECISIONS.md** (it has existed since 2026-10-21).
- Privacy (rule 20): no usernames, emails, passwords, tokens or real names in any file, log or chat. Friends are recorded by Jellyfin user id only.
- Who does what: every NAS write, Cloudflare click and Jellyfin dashboard click is B.'s (rule 10). Claude does read-only checks.
- "UNTESTED — prove at WP-A6 step N" marks anything not yet run end to end.

Notes on the helper block:
- The closing `'@` of each here-string must stay at the very start of its line (column 0). Paste the whole block at once.
- `joey-hub` must be running (`ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker ps --filter name=joey-hub"`).

### Paste this block

```powershell
# JfUser <user id>  -> prints the friend-template policy fields for one Jellyfin user (rule 21 read of GET /Users/<id>)
function JfUser($id) {
@'
import os, sys, json, urllib.request as u
H = {'Authorization': 'MediaBrowser Token="' + os.environ['JELLYFIN_API_KEY'] + '"'}
p = json.load(u.urlopen(u.Request('http://jellyfin:8096/Users/' + sys.argv[1], headers=H), timeout=5))['Policy']
for k in ('IsDisabled', 'IsHidden', 'IsAdministrator', 'EnableRemoteAccess', 'EnableAllFolders', 'EnableContentDownloading', 'EnableSharedDeviceControl', 'RemoteClientBitrateLimit', 'MaxActiveSessions', 'LoginAttemptsBeforeLockout'):
    print(k, '=', p.get(k))
print('EnabledFolders =', len(p.get('EnabledFolders', [])))
'@ | ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec -i joey-hub python - $id"
}

# JfSessions  -> prints one line per live Jellyfin session: user id, app, LAN or public, playing?, transcoding?
function JfSessions {
@'
import os, json, urllib.request as u
H = {'Authorization': 'MediaBrowser Token="' + os.environ['JELLYFIN_API_KEY'] + '"'}
s = json.load(u.urlopen(u.Request('http://jellyfin:8096/Sessions', headers=H), timeout=5))
print('sessions =', len(s))
for x in s:
    ip = x.get('RemoteEndPoint') or ''
    where = 'LAN' if ip.startswith(('192.168.', '10.', '127.', '172.')) else 'public'
    t = x.get('TranscodingInfo')
    print(x.get('UserId'), '|', x.get('Client'), '|', where, '| playing =', bool(x.get('NowPlayingItem')), '| transcoding =', bool(t and not t.get('IsVideoDirect', True)))
'@ | ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec -i joey-hub python -"
}

# JfPlays  -> prints play-row counts per owner key from media.db (read-only). Friends appear as jf:<32 hex>.
function JfPlays {
@'
import sqlite3
c = sqlite3.connect('file:/data/sqlite/media.db?mode=ro', uri=True)
for owner, n in c.execute('select owner, count(*) from play group by owner order by 2 desc'):
    print(owner, '|', n)
'@ | ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec -i joey-hub python -"
}
```

### Use them

```powershell
JfUser '<32-hex jellyfin user id>'
JfSessions
JfPlays
```

**Verify:** `JfSessions` prints `sessions = N` (N may be 0). `JfUser` for the admin id prints `IsAdministrator = True`. If either prints a 401 traceback, the API key header is wrong or the key was rotated; stop and tell Claude.

### Where to find a user's id

Jellyfin web: Dashboard, Users, click the user. The address bar ends `...userId=<32 hex characters>`. That string is the only identifier that goes into DECISIONS.md, HANDOVER.md or chat (rule 20: ids, never names).
The joeytest id and the friend ids are recorded in the Joey TV DECISIONS.md, not in this file.

## R1 Friend onboarding (Phase A)

**What this does:** gives one friend household access to your Jellyfin through the official Jellyfin app on their TV, over `https://jellyfin.joeyhome.net:8443`.
Phase A only: no Joey Media app yet (the "R1-B Phase B additions" stub at the end of this runbook).

**Before you start (all must be true):**
- **The line "Q25b LIVE in Phase A (WP-A6a)" is in the Joey TV DECISIONS.md** (dated 2026-10-21; WP-A6 step 8 was blocked until it existed).
- WP-A5 is DONE and WP-A6 steps 1 to 3 and 6 passed (Quick Connect drill, revoke drill, lockout note, restore drill). NAS 24/7 (step 7, F7) is done on the invite day itself.
- You have pasted the helpers from R0 into this PowerShell window.
- The household has a **Google TV / Android TV** device. Samsung (Tizen) households need a Google TV stick first (step 0). Fire TV is untested.
- The numbers: the household upload is 32.5 Mbps, so the whole friend group is sized for **1 stream at a time at the 20 Mbps cap**; up to 5 households only after the Phase A go-gate PASS line. Do not onboard a 2nd household until that line exists.

Every NAS command below is yours to run (MASTER_PLAN rule 10). Claude reads the results.

### Step 0: Check the household's TV (2 minutes, before creating anything)

1. Ask which TV or streaming device they use, and the model and Android version if they know it (Settings, About). Do not record their names.
2. **Samsung or LG TV (no Android):** the official Jellyfin app cannot be installed from the Samsung store. Plan answer (Q49 = both): each Samsung household plugs in a **Google TV stick**
   (for example Chromecast with Google TV 4K, or a TCL/Xiaomi equivalent, about A$60 to 100, their purchase or your gift). A later work package ("WP-tizen") will add a Tizen route; do not promise it.
3. **Fire TV:** untested. Tell them it may work but you have not tried it. Prefer a Google TV device.
4. **Not in Australia or New Zealand:** stop. The edge answers only AU and NZ addresses; anywhere else gets a 403.

**Verify:** you have written down (no names) the device type and, for the pilot, the model and Android or Fire OS version (this feeds Q42).

### Step 1: Create the Jellyfin user

1. Open Jellyfin as admin on the **LAN address**: `http://192.168.68.59:8096`. (The admin is refused on the public `:8443` address, even from home; see R0 "Conventions".)
2. Dashboard, **Users**, the **+** button. Name = a short login name you choose, Password = a **temporary** password (use your password manager's generator). Leave "Enable access to all libraries" as it is; the script in step 2 fixes it. Save.
3. Click the new user in the list. Copy the 32-character `userId=` value from the address bar. Call it `<id>` below.

**Verify:** `JfUser '<id>'` prints a policy (the untemplated defaults for now). A 400 or traceback means the id was copied wrongly or truncated.

### Step 2: Apply the friend template by script (do NOT use the web UI for this)

The Jellyfin 12.2.0 web UI **reverts library access** when the Access tab is saved, so the template is applied through the API by `nas_scripts\joeytest_policy.py`
(`C:\Users\b.edwards\Desktop\Claude\LifeDashboard\nas_scripts\joeytest_policy.py`; it stays outside git by decision 2026-10-19, so keep this laptop copy safe).
It sets: not admin, hidden from the login screen, remote access on, 20 Mbps cap, **max active sessions 2**, **lockout after 10 failed sign-ins**, no downloads, no deletion,
no shared-device control, no Live TV, and only the Movies and TV Shows libraries. It was run on joeytest and on the first friend user on 2026-10-20 (both read back `MaxActiveSessions = 2`).

> **Never run this script on the household alias user.** It applies the friend template; the alias is `MaxActiveSessions = 0` and is set by hand in the dashboard (or with `jellyfin_set_max_sessions.py`).

1. Copy the script to the NAS and **check the copy is the new one** (on 2026-10-19 an old copy was left in `/tmp` and the run silently did nothing):

```powershell
scp -i $env:USERPROFILE\.ssh\joey_nas C:\Users\b.edwards\Desktop\Claude\LifeDashboard\nas_scripts\joeytest_policy.py root@192.168.68.59:/tmp/joeytest_policy.py
(Get-Item C:\Users\b.edwards\Desktop\Claude\LifeDashboard\nas_scripts\joeytest_policy.py).Length
ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "wc -c /tmp/joeytest_policy.py"
```

   **Verify:** the two byte counts are **equal** (compare them yourself; the number itself does not matter).

2. Run it against the new user. Leave the account **enabled** if you are inviting today. Add `--disable` at the end if you are only preparing the account ahead of the invite:

```powershell
ssh -t -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec -i joey-hub python - <id> < /tmp/joeytest_policy.py"
```

   (Replace `<id>` with the real 32 characters. For "prepare only": `... python - <id> --disable < /tmp/joeytest_policy.py`.)

   **Verify:** the last line printed is `verify: PASS`. Then `JfUser '<id>'` shows: `IsAdministrator = False`, `IsHidden = True`, `EnableRemoteAccess = True`,
   `EnableAllFolders = False`, `EnableContentDownloading = False`, `EnableSharedDeviceControl = False`, `RemoteClientBitrateLimit = 20000000`,
   `MaxActiveSessions = 2`, `LoginAttemptsBeforeLockout = 10`, `EnabledFolders = 2`, and `IsDisabled = False` (or True if you used `--disable`).
   If the script printed FAIL, do not invite; run it again, and if it fails a second time stop and tell Claude (circuit breaker).
   *UNTESTED as a documented sequence — prove at WP-A6 step 8 (step 1 tested 2026-10-20: template re-applied on joeytest, Quick Connect drill passed).*

3. If you are enabling a previously prepared (disabled) account: Dashboard, Users, the user, **Profile**, untick **Disable this user**, Save.
   The Profile tab keeps the template, but never save the **Access** tab.

   **Verify:** `JfUser '<id>'` again: `IsDisabled = False` and everything above unchanged (`EnabledFolders = 2`, `EnableAllFolders = False`, `MaxActiveSessions = 2`).

### Step 3: Check the server settings the TV depends on (once, not per friend)

1. **Public HTTPS port = 8443** (what Jellyfin advertises to apps; without it some clients fall back to :443 or the default, which is dead at the router).
   **The Jellyfin 12.2 Networking page has no public-port field.** `PublicHttpsPort` is set through the API by `nas_scripts\jellyfin_public_port.py`
   (`C:\Users\b.edwards\Desktop\Claude\LifeDashboard\nas_scripts\jellyfin_public_port.py`; outside git, like `joeytest_policy.py`). It changes only the two port fields and was run on 2026-10-20.
   Run it again only if the value reads wrong (for example after a Jellyfin reinstall):

   ```powershell
   scp -i $env:USERPROFILE\.ssh\joey_nas C:\Users\b.edwards\Desktop\Claude\LifeDashboard\nas_scripts\jellyfin_public_port.py root@192.168.68.59:/tmp/jellyfin_public_port.py
   ssh -t -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec -i joey-hub python - < /tmp/jellyfin_public_port.py"
   ```

   **Verify:** the last line is `verify: PASS`, with `after:  PublicHttpsPort = 8443 | InternalHttpsPort = 8920`. **Do not type 8443 into the "Local HTTPS port number" field** (Jellyfin's own HTTPS is off, so it is inert, but it is the wrong field).
2. Dashboard, **Networking**: **Known proxies = `172.31.250.1, 172.18.0.1`**, "Allow remote connections" on, and do not tick "Enable automatic port mapping" (the router forward is a manual one). Quick Connect is enabled (Dashboard, General).

**Verify:** from a phone on mobile data (not home Wi-Fi): `https://jellyfin.joeyhome.net:8443/System/Info/Public` loads JSON containing `"ServerName"`. If it times out, the forward or swag is down:
check "Kill switch" (R3) above and `docker ps --filter name=joey-swag` before blaming the friend.

### Step 4: Seerr

Nothing to do in Phase A. Seerr is not on the public hostname. From Phase B the friend's Seerr user is **auto-imported on their first request** (Q29/D-P19: `joey-media` calls the import for that friend only).
If WP-B4 finds the import endpoint fails on Seerr 3.5.0, the fallback is a manual import at grant time (Seerr, Settings, Users, Import Jellyfin Users); that would be a dated DECISIONS line and a new step here.

**Verify:** none needed now.

### Step 5: Send the friend their details (private message, two parts)

Send by a private message app, not email. Send the **login name and the address first, the temporary password in a second, separate message.** Never send the name and the password together.
Draft text (edit freely, no real names in files):

> Hi! Your Jellyfin login is ready.
> 1. On your TV, install **Jellyfin** from the Google Play Store (it is the official app, a purple icon).
> 2. First, on your **phone or laptop browser**, go to `https://jellyfin.joeyhome.net:8443` and sign in with the login name below and the temporary password I'll send in the next message. **Please change your password straight away** (profile picture, then Settings, then Password).
> 3. Then open Jellyfin on the TV. Add a server: `https://jellyfin.joeyhome.net:8443` (**the :8443 on the end is needed**). Choose **Quick Connect**; a code appears on the TV. On your phone (still signed in), tap your profile picture, then **Quick Connect**, enter the code, and approve.
> 4. Things to know: it works from **Australia and New Zealand only** (it will stop working if you travel overseas); please **watch on one device at a time**; no downloading; quality is capped at about 20 Mbps, so a normal home connection is fine. If it stops working, message me, don't keep retrying the password (too many wrong tries locks the account).
> Login name: `<name>`

**Verify:** you sent two messages, address plus name first and password second. Nothing with a password is in a file, DECISIONS.md or chat with Claude.

### Step 6: Watch the first sign-in

1. Ask the friend to say when they start. Then: Jellyfin Dashboard (home), **Active devices**. You should see the friend's device with a **public client IP**, not 172.x or 192.168.x.
2. Dashboard, **Devices**: the friend's TV and phone browser listed under their user.
3. Confirm with the helper:

```powershell
JfSessions
```

**Verify:** one line with the friend's `<id>`, `public`, and `playing = True` once they press play; `transcoding = True` only if the title needed it (Active devices then shows "(HW)" for Quick Sync).
Bitrate on the dashboard is 20 Mbps or lower. After they have watched a few minutes, `JfPlays` shows a new `jf:<id>` row count.
The same path was proven on 2026-10-20 with joeytest on the official Android TV app (Quick Connect sign-in, public client, direct play, a `jf:` play row written).
*A real household is UNTESTED — prove at WP-A6 step 8.*

**If the TV cannot connect:**
- "Unable to connect": check the address has `https://` **and** `:8443`, with no trailing slash and no `/web`.
- "Server not found" only at their house: their router or DNS may block it; ask them to try the phone browser address first. If the phone works but the TV does not, check the Jellyfin app is current and note the TV's Android version (the later Joey Media app needs Android 9; the official app's own minimum is not recorded in the plan).
- Sign-in refused: the account may be disabled by lockout (see R2, "Lockout") or the temporary password was already changed.
- Quick Connect code "not found": the code expires in a few minutes; get a new one on the TV.

### Step 7: Record it (ids only)

Add one dated line to the Joey TV DECISIONS.md (or ask Claude to): `<date> friend granted jf:<id>`. For the pilot household: `<date> pilot friend granted jf:<id>`, and record the device model and Fire OS or Android version against Q42 in the plan (no names, no emails, no passwords).

**Verify:** the line is in DECISIONS.md; B.'s own and the household alias's Joey pages show nothing new (the friend's plays belong to `jf:<id>` and are hidden from private mode).

### R1-B Phase B additions

(Stub, filled in WP-B9.) Install Joey Media (Downloader short URL or ADB, DECISIONS #36); Quick Connect inside Joey Media; one-time "Set up Jellyfin" card (Q39).
Nothing here applies until the dated "GO Phase B" line and the WP-B5 security gate PASS exist; no friend receives `media.joeyhome.net` or the APK before that (rule 17).

### Facts to keep in mind while onboarding

- **Household budget:** upload 32.5 Mbps, so the friend group is sized for **1 simultaneous stream at the 20 Mbps cap**. Each friend user is limited to 2 sessions (a Phase B TV holds two); that does not limit the group.
  The group budget is held by watching upload and the go-gate, not by a setting. Watch Active devices during the pilot and tell friends to message you first if they want to stream on a busy night.
- **The household alias** is one shared non-admin "outside" Jellyfin user (unlimited sessions); do not give friends that login.
- **Privacy:** friends are recorded by Jellyfin user id only, in files, logs and DECISIONS. Never write a name, email or password into any repo or planning file (rule 20).
- **If a friend travels** outside AU/NZ they lose access (403) until they return; no action needed. Do not open the geo gate for a trip.

## R2 Revoke

**What this does:** cuts one friend off from Jellyfin immediately, while keeping their viewing history (`jf:<id>` play rows) so a later re-enable restores everything.
Use it to remove a friend, to pause one, or to rehearse (joeytest, WP-A6 step 2). It also holds the **lockout** note and the rule for **joeytest**.
**Tested 2026-10-20 (revoke drill PASS on joeytest):** disable, devices deleted, zero sessions, play rows unchanged; re-enable by unticking Disable, fresh Quick Connect sign-in, play rows still unchanged.

**Before you start:** paste the helpers from R0. You need the user's 32-character id (Dashboard, Users, click the user, copy `userId=` from the address bar). Write down the id only, never the name.

**Emergency, whole edge:** if the problem is not one user but the public door itself, use the kill switch (R3, "Kill switch" above). R2 is per user.

### Revoke one user

1. **Disable the user.** Jellyfin Dashboard, **Users**, click the user, **Profile**, tick **Disable this user**, **Save**. Nothing is deleted.
   **Verify:** `JfUser '<id>'` prints `IsDisabled = True`.

2. **Delete their devices.** Dashboard, **Devices**, find the user's rows (the TV and any phone browser) and delete each one (tick, then the delete/trash control).
   **Verify:** the Devices list shows no rows for that user, and `JfSessions` prints no line containing `<id>`.

3. **Stop any live session.** Dashboard home, **Active devices**: if the user is still shown playing, use the stop/terminate control on that session (exact 12.2.0 label unchecked). After steps 1 and 2 the token is dead, so this normally clears by itself within a minute.
   **Verify:** `JfSessions` prints no line with `<id>`. On the friend's TV the Jellyfin Android TV app asks them to sign in again and pick an account; nothing keeps playing (observed in the 2026-10-20 drill).

4. **Seerr permission removed** (Phase B only; nothing to do in Phase A, friends are not in Seerr). From Phase B: Seerr, Settings, Users, the user, remove Request permissions or delete the Seerr user.
   **Verify:** (Phase B) the user's Seerr permissions read as none.

5. **Joey Media** (Phase B only): the guest UI and the TV shell re-validate the Jellyfin session at **every launch**; a disabled user is signed out on the next launch. Nothing to do in Phase A.

6. **Check their history is kept.** Write down the `jf:<id>` count before step 1 if you can.
   ```powershell
   JfPlays
   ```
   **Verify:** the `jf:<id>` row count is the same as before you revoked (DECISIONS #15: rows are kept).

7. **Record it, id only.** Add the dated line to the Joey TV DECISIONS.md: `<date> revoked jf:<id>`. No name, no reason that identifies a person.
   **Verify:** the line is in DECISIONS.md.

### Re-enable one user

1. Dashboard, **Users**, the user, **Profile**, untick **Disable this user**, **Save**. (Do not save the Access tab; it reverts library access.)
   **Verify:** `JfUser '<id>'` prints `IsDisabled = False`, `EnabledFolders = 2`, `EnableAllFolders = False`, `MaxActiveSessions = 2`, `LoginAttemptsBeforeLockout = 10`.
   If any of those drifted, re-apply the template (R1 step 2, `joeytest_policy.py <id>`; never on the alias user).
2. The friend signs in again with Quick Connect (devices were deleted, so a new sign-in is needed).
   **Verify:** `JfSessions` shows a line with `<id>`; `JfPlays` shows the **same** `jf:<id>` count as before the revoke (history kept).
3. Record: `<date> re-enabled jf:<id>`.

### Lockout: "the user is Disabled and I did not do it"

*Tested 2026-10-21 (drill on joeytest): the fail2ban IP ban at 5 failures fires before the Jellyfin user lockout at 10.*

Jellyfin's lockout **disables the user** after the configured failed sign-ins. Friends are set to **10** (Q28), deliberately above fail2ban's 5, so on the open port the **IP ban fires first**
(5 failures in 10 minutes bans the address for 1 hour). The lockout can therefore only be reached from a second address, or by tries on the LAN address `http://192.168.68.59:8096`, which bypass SWAG (and so fail2ban). Revoke and lockout look identical in the dashboard, so check before re-enabling:

1. **Was it the friend?** Ask them whether they typed the password wrong repeatedly (a TV remembering an old password counts).
2. **Look for guessing.**
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec joey-swag fail2ban-client status jellyfin-auth"
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec joey-swag tail -n 40 /config/log/nginx/access.log"
   ```
   **Verify:** the first prints `Currently banned` and `Total banned` counts. A ban of a **friend's** address means they did it themselves (the ban is 1 hour and lifts alone).
   Many 401 lines on `/Users/AuthenticateByName` from addresses that are not the friend's mean someone is guessing the username: tell the friend, change nothing else, and consider disabling until it stops.
3. **Re-enable** with "Re-enable one user" above (Profile, untick **Disable this user**). First check `fail2ban-client status jellyfin-auth` and the user's `InvalidLoginAttemptCount`: a lockout the friend did not cause means someone is guessing that username from more than one address. If the friend did it: tell them to wait for their ban to lift if applicable, then use the right password or Quick Connect.
   Phase B note: the guest sign-in path (`hub/guest_auth.py`) keeps its own counter and refuses before Jellyfin is called, so the guest UI alone can never cause a lockout. That counter does not exist until WP-B2; ignore it in Phase A.

**Drill result (2026-10-21, joeytest):** phase 1, 5 wrong passwords from a phone on cellular via `:8443`: fail2ban `jellyfin-auth` total banned went 0 to 1, the phone's address was dropped for 3600 s, the home WAN address was untouched. Phase 2, 5 wrong passwords on the LAN address `:8096` (bypasses SWAG, so no second ban): the user showed `IsDisabled = True` with `InvalidLoginAttemptCount` 11 against `LoginAttemptsBeforeLockout` 10. Order proven: the IP ban at 5 fires before the user lockout at 10, so a real lockout needs two or more source addresses, or LAN tries. Whether re-enabling resets the failed-attempt counter was not recorded.

### joeytest (the test account), rule 22

The internet-reachable test account is **disabled between work packages**. Each WP that uses it opens with "B. re-enables joeytest" and closes with "B. disables joeytest", each with the `IsDisabled` read-back.
Read `Policy.IsDisabled` first at the start of a session; do not assume the state the last one left it in.
To do it: Dashboard, Users, joeytest, Profile, untick (or tick) **Disable this user**, Save, then `JfUser '<joeytest id>'` (the id is in DECISIONS). HANDOVER.md records the state at every WP close.
**Verify:** `IsDisabled = False` after re-enable, `IsDisabled = True` after disable.
When re-enabling joeytest at WP-A6 step 1, re-apply the template first (R1 step 2) so it reads `MaxActiveSessions = 2`.
joeytest is the account for every friend-path test on the public address (the admin is refused there). **Never run `joeytest_policy.py` on the household alias**, and in the dashboard double-check which user's profile is open before typing a session limit (on 2026-10-20 a "0" landed on the admin and on joeytest in turn; open the profile by its direct `userId=` link).

## R4 Deploying while friends stream / patch cadence

**What this does:** keeps the two public-facing containers patched on purpose (not by surprise), and says how to deploy or update without breaking a friend's evening.
Two parts: **A. Patch cadence (Q10)** and **B. Deploying while friends stream**. (The plan's R4 is Part B; the Q10 cadence lives here too.)

**Policy (Q10, accepted 2026-10-18):**
- **SWAG (`joey-swag`) is pinned and manual.** The image tag is fixed in `deploy/docker-compose.yml` (now `lscr.io/linuxserver/swag:5.8.0-ls490`, never `latest`). Joey's `joey-*` containers are held out of What's Up Docker (WUD) runs.
- **Jellyfin is manual, with a weekly check by B.** WUD still *notifies* about new Jellyfin images, but no longer applies them (below).

Paste the helpers from R0 first. All NAS writes are yours (rule 10); Claude reads.

### A. Patch cadence

#### A1. How Jellyfin was made manual (in place since 2026-10-12)

WUD auto-updated Jellyfin 12.1 to 12.2 on 2026-10-12, mid-use. The same day Jellyfin was given the label `wud.trigger.exclude=dockercompose.local`: the "local" trigger (which updates automatically) skips it,
and a second trigger, `dockercompose.manual` (`WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_AUTO=false`, so it never fires by itself), is the only way WUD updates it, when you ask.

**Verify it is still so (once now, and after any change to the media compose):**
```powershell
ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker inspect jellyfin | grep wud"
```
Expect a line `"wud.trigger.exclude": "dockercompose.local"`. If it is missing, stop: Jellyfin can update itself in front of friends. Tell Claude; it is a one-line change in `/volume1/media-server/docker-compose.yml` followed by `docker compose up -d jellyfin`.

#### A2. Weekly check (same day each week, a 5-minute job)

1. **Jellyfin.** Open the Joey **Server** page, Updates band (`/server#updates`; WUD sweeps hourly). The Jellyfin row shows "Manual · excluded" with an **Update now** button when a new image exists. Also glance at https://github.com/jellyfin/jellyfin/releases and the Security tab of that repo.
2. **SWAG.** Glance at https://github.com/linuxserver/docker-swag/releases for a new tag (format `5.8.0-lsNNN` or newer) and whether the notes mention nginx, OpenSSL or certbot security fixes.
3. **Decide.** Suggested rule (not in the plan; confirm or change it): security fixes within the same week; other releases after about a week of soak; never on an evening a friend streams (check `JfSessions`, see Part B).
4. **Record** in HANDOVER.md or DECISIONS only when you actually update: `<date> Jellyfin updated <old> to <new>` or `<date> swag tag <old> to <new>`.
5. **Joey TV app (WP-B8).** `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "tail -1 /volume1/Docker/joey/life-dashboard/deploy/history.log"`: the line ends `tv=current`. A lingering `tv=pending` means a deploy was missed after a release (deploy again); `tv=FAIL:auth` means the NAS token needs renewing. Meaning of every token and what to do: [`tv-release.md`](tv-release.md), "History tokens". (A TV release alone does not recreate swag, so it needs no R4 timing; only a `deploy/swag/**` change does.)

**Verify (weekly):** you looked at both pages and wrote down "checked, nothing" or "updating on <day>". If you skip two weeks in a row there is a CVE window; set a calendar reminder.

#### A3. Update Jellyfin (UNTESTED — prove at the first real Jellyfin update; WP-A6 step 10 exercises only the deploy side)

1. **Check nobody is watching.**
   ```powershell
   JfSessions
   ```
   **Verify:** `sessions = 0`, or no line shows `public` and `playing = True`. If a friend is playing, wait or ask them. Recreating Jellyfin drops streams for about 30 seconds.
2. **Update.** Either Joey Server, Updates, Jellyfin, **Update now** (two-step: confirm page, then "Update Jellyfin now"), or on the NAS:
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "cd /volume1/media-server && docker compose pull jellyfin && docker compose up -d jellyfin"
   ```
   **Verify:** `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker ps --filter name=jellyfin"` shows `Up` with a fresh "Up N seconds" and the new image tag.
3. **Post-update checks, in this order. LAN first, outside last.**
   1. LAN, straight to Jellyfin:
      ```powershell
      ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "curl -s -m 8 http://127.0.0.1:8096/health"
      ```
      **Verify:** prints `Healthy`.
   2. LAN, through swag (checks the proxy path and the certificate name; **443 here, not 8443**):
      ```powershell
      ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "curl -s -m 8 --resolve jellyfin.joeyhome.net:443:127.0.0.1 https://jellyfin.joeyhome.net/health"
      ```
      **Verify:** prints `Healthy`. If it hangs or prints nothing, swag is the problem, not Jellyfin: `docker ps --filter name=joey-swag`.
   3. Version and network attachment:
      ```powershell
      ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker network inspect joey-edge | grep -c jellyfin"
      ```
      **Verify:** 1 or more (jellyfin is still on `joey-edge`; Known proxies `172.31.250.1, 172.18.0.1` depend on it). In Jellyfin, Dashboard shows the new version.
   4. Settings survived: Dashboard, **Networking**: Known proxies unchanged, and `PublicHttpsPort` still 8443 (re-run `jellyfin_public_port.py`, R1 step 3, if not); Dashboard, Playback, **Transcoding**: hardware acceleration still Intel QSV (`docker exec jellyfin ls /dev/dri` lists `renderD128`).
   5. Friend template survived: `JfUser '<a friend id>'` prints the template values (R1 step 2 lists them, `MaxActiveSessions = 2`).
   6. Outside, from the phone hotspot (laptop tethered, Wi-Fi off):
      ```powershell
      curl.exe -sI --doh-url https://cloudflare-dns.com/dns-query https://jellyfin.joeyhome.net:8443/health
      ```
      **Verify:** `HTTP/1.1 200`. (From a non-AU/NZ address you would see 403, which is correct.) The router does NAT loopback (hairpin PASS 2026-10-19), so the laptop on home Wi-Fi also reaches this URL; the hotspot is the true outside check.
   7. A real sign-in: Quick Connect or play 1 minute as joeytest (R2 "joeytest" first: re-enable, then disable again; never the admin, which is refused on the public address). **Verify:** `JfSessions` shows the session as `public`.
4. **Rollback** if step 3 fails: put the previous image tag back in `/volume1/media-server/docker-compose.yml` (the previous tag is on the Server page and in `docker images`), then `docker compose up -d jellyfin`.
   Jellyfin databases can migrate forward and refuse to start on an older version, so take a copy of its config folder before a **major** version jump (Dashboard, Backups if your version has it, otherwise a copy of the appdata folder).

#### A4. Update SWAG (a repo change, not a click; UNTESTED — prove at the first swag bump)

Because swag is pinned in git, a bump is a code change with review and a test (`tests/deploy/test_edge.py` pins the edge shape).

1. **Ask Claude** (a Joey session) to bump the tag on a `joeytv-*` branch: it edits the `image:` line in `deploy/docker-compose.yml`, runs the suite, pushes the branch. (Claude may push feature branches, not merge.)
2. **You merge** (`gh pr merge`) once the suite is green, then pre-pull the image so the outage is short:
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "cd /volume1/Docker/joey/life-dashboard/deploy && docker compose pull swag"
   ```
   **Verify:** `Downloaded newer image` (or `Image is up to date` if it was already pulled).
3. **Check nobody is watching** (`JfSessions`, as in A3 step 1; a swag recreate cuts every remote stream for about 10 seconds).
4. **Deploy** using the Part B method (detached; see Part B below). `deploy.sh` recreates swag only when the deploy touched `deploy/swag/**` (or the swag compose entry) or with `--force`.
   For an image-tag bump, confirm in step 5.1 that swag really got a fresh "Up" time; if it did not, re-run with `--force`.
5. **Post-update checks, LAN first:**
   1. `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker ps --filter name=joey-swag"` shows the new image tag and a fresh "Up" time.
   2. LAN `/health` through swag (A3 step 3.2) prints `Healthy`.
   3. `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker logs --since 5m joey-swag 2>&1 | grep -ci 'Address in use'"` prints `0` (php-fpm stays on its unix socket).
   4. `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec joey-swag fail2ban-client status jellyfin-auth"` prints the jail (still `jellyfin-auth`; banned count survives or resets to 0).
   5. Only 443 listens: `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec joey-swag nginx -T 2>/dev/null | grep -E 'listen'"` shows only `443 ssl` lines.
   6. The real client address still reaches nginx: `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec joey-swag tail -n 3 /config/log/nginx/access.log"` shows a client that is not 172.x or 127.0.0.1 for any outside request. If it shows 172.x, **close the forward** (R3) and tell Claude.
   7. Outside from the hotspot: the `curl.exe -sI --doh-url ... :8443/health` line from A3, `HTTP/1.1 200`.
6. **Rollback:** revert the tag commit (or restore the previous tag), `git push`, merge, deploy again. `/volume1/Docker/joey/swag` (certificates, state) is untouched by an image bump.

#### A5. Certificate expiry alert

SWAG renews the Let's Encrypt wildcard (`*.joeyhome.net`, DNS-01 via the Cloudflare token) by itself, roughly 30 days before expiry. Let's Encrypt no longer sends expiry e-mails (since 2025),
so **Uptime Kuma's certificate-expiry notification is the only alarm**: monitor #10 "Jellyfin edge" (`https://jellyfin.joeyhome.net:8443/health`, keyword `Healthy`, 60 s / 2 retries) has cert-expiry ON and Discord attached (read back 2026-10-20; its alert path was drilled the same day).

**Check it exists and is armed (once, then every quarter):**
1. Kuma, monitor #10, **Edit**: "Certificate Expiry Notification" ticked, Discord notification attached. Kuma, Settings, Notifications: the expiry-days setting lists at least one threshold (Kuma's default is 7, 14 and 21 days).
2. The monitor's detail page shows a certificate expiry date. On 2026-10-19 the certificate expired **2027-01-17**, so a renewal should have moved it to about mid-March 2027 by about 2026-12-18.
3. Read the date straight from the NAS as a second source (does not depend on Kuma):
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker exec joey-swag sh -c 'echo | openssl s_client -connect 127.0.0.1:443 -servername jellyfin.joeyhome.net 2>/dev/null | openssl x509 -noout -enddate'"
   ```
   **Verify:** prints `notAfter=<date>`. **Calendar reminder: 2026-12-20**, check that `notAfter` has moved forward; if it still reads 2027-01-17, renewal is failing.

**If the alert fires or renewal fails:**
1. `ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "docker logs --since 48h joey-swag 2>&1 | grep -i -E 'certbot|renew|error' | tail -n 30"`. The usual cause is the Cloudflare API token (expired, revoked or mis-scoped).
2. Rotate the token with the "Token rotation" section above (new token in `deploy/edge.env`, `edge_cf_ini.sh`, `docker compose restart swag`, revoke the old one; rule-11 routine). Do not enable staging unless you are testing; production issuance is rate-limited.
3. **Verify:** `notAfter` has moved; the Kuma alert clears on its next check.

### B. Deploying while friends stream

Facts first:
- `deploy.sh` **never touches Jellyfin**.
- **Since PR #9 (merged 2026-10-19), `deploy.sh` recreates `joey-swag` ONLY when the deploy changed `deploy/swag/**` (or the swag compose entry), or when run with `--force`.** When it does, expect a **~10 second edge blip**: friends' connections through 8443 are cut, a stream in progress may stall or error, and the friend may have to press play again. A deploy that does not touch swag has no edge blip. (Earlier text saying swag is recreated "on every deploy" is superseded.)
- The gate suite (about 10 minutes at `-n 2`) plus the image build can make software transcodes stutter on a 3.7 GB NAS.
- WUD updates and "Update all" are the same kind of risk: they restart containers mid-stream.

**Deploys must survive a laptop close (incident 2026-10-19/20).** On 2026-10-19 at about 21:29 the laptop was closed during an interactive `ssh -t ... deploy.sh`; the session got SIGHUP mid `compose up`,
leaving `joey-hub` and `joey-connectors` stuck in state **Created**, and `joeyhome.net` returned **502 for about 11 hours (21:29 to about 08:50)**.
Restore was `docker compose up -d --remove-orphans` (Joey back in about a minute), then `deploy.sh --force` re-run detached (PASS).
- **PR #11 (deploy.sh self-detach: `setsid`, HUP-proof, logs to `deploy/logs/deploy-<UTC>-<pid>.log`) is merged and was deployed on 2026-10-20 (404c93d), but that deploy still ran the OLD `deploy.sh`.** Until one deploy has run the new script (its log appears in `deploy/logs/`), run every deploy detached by hand:
  ```powershell
  ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "cd /volume1/Docker/joey/life-dashboard/deploy && nohup sh deploy.sh > /tmp/deploy.out 2>&1 < /dev/null &"
  ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "tail -f /tmp/deploy.out"
  ```
  (Ctrl-C only stops the `tail`.)
- **After that**, `deploy.sh` detaches itself, tails its own log in the foreground, and returns the child's exit code; Ctrl-C or a dropped connection stops only the watcher.
  **To stop a running deploy you must `kill <pid>` (the pid is in the log file name), and never do that mid `compose up`.**
- If a deploy is ever killed and hub shows "Created": `docker compose up -d --remove-orphans` in `/volume1/Docker/joey/life-dashboard/deploy`, then `deploy.sh --force` detached.

Steps:
1. **Look first.** Joey Server, **Live**, and Jellyfin Dashboard, Active devices, or:
   ```powershell
   JfSessions
   ```
   **Verify:** no line shows `public` with `playing = True`. If one does, wait, or deploy late at night (the NAS is 24/7 from the invite day, F7). If you want to know whether this deploy will blip the edge, ask Claude whether `deploy/swag/**` or the swag compose entry changed between the NAS HEAD and origin/main.
2. **Deploy**, detached as above (add `--force` only to redeploy an unchanged SHA, which also recreates swag). Before any deploy, confirm the NAS clone's HEAD equals origin/main (rule 9).
3. **After it, LAN `/health` first** (A3 step 3.1 and 3.2), then `tail -n 3 /volume1/Docker/joey/life-dashboard/deploy/history.log` shows `PASS`, then the outside curl (A3 step 3.6).
   **Verify:** `Healthy` on both LAN checks, `PASS`, `HTTP/1.1 200` outside.
4. **Never start a deploy in the 15 minutes before 00:00 UTC (11:00 AEDT / 10:00 AEST).** The test gate runs on UTC, and tests that read the real date can fail across midnight (GATE-FAIL 2026-10-21; the same commit passed 20 minutes later). A clock-freeze fix for those tests is in progress.
5. **Never "Update all" in WUD, and never take `edge` out of `COMPOSE_PROFILES`** (R3: a deploy with the profile off can remove `joey-swag` mid-stream). Use R3's kill switch only to close the door, then decide.
6. **Deploy-with-stream drill (WP-A6 step 10, PASS 2026-10-21):** with joeytest streaming remotely, run `deploy.sh --force` (detached). Pass (B., 2026-10-20): the stream survives the ~10 s swag recreate, or resumes after ONE client retry or press of play; record which.
   `docker ps` shows `joey-swag` Up with a **new** start time, history.log PASS. **Result (drill 2026-10-21, 1080p HEVC DirectPlay on the public address):** a deploy's swag recreate does not interrupt a direct-play remote stream (no visible pause, no client retry); transcoded streams untested.

## F7 NAS 24/7

**What this does:** stops the NAS powering off at night, so friends in AU and NZ can watch in the evening and the public edge, Uptime Kuma and the backups keep running.
Decision F7 (2026-10-16): "NAS runs 24/7 if this project proceeds", taking effect **when the first friend gets access, not before**. This is WP-A6 step 7, done **on the invite day**.
**Current state (2026-10-20): the NAS still powers off and on by its ADM schedule** (it came up at about 07:00 on 2026-10-20 after the overnight off). *UNTESTED — prove at WP-A6 step 7.*

**Before you start:** WP-A5 DONE; the pilot friend's invite is the same day; the restore drill (R5, "Restore media.db") has passed. You are in ADM (the NAS web interface), signed in as the admin you normally use.

1. **Note the current state first.**
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "uptime"
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "cat /proc/sys/vm/swappiness"
   ```
   **Verify:** a short uptime from the last boot (hours, not weeks); swappiness reads **10**. Write both down.

2. **Remove the power schedule.** ADM, **Settings**, **Hardware**, **Power**: delete or disable every scheduled power-off **and scheduled power-on** entry, then **Apply** (menu labels unconfirmed on this ADM version). Do not change anything else under "Hardware".
   **Verify:** the Power page lists no scheduled power-off. Also check ADM Scheduled tasks (or Task Scheduler) for a power-off job, and that nothing outside ADM (a smart plug, a script on another machine) cuts the power at night.

3. **Tell Claude** (coordinator or WP-A6 session): "NAS is 24/7 from <date>". Claude then writes the superseding DECISIONS entries:
   - the index "Host + deploy" bullet in the parent project's DECISIONS.md,
   - a dated log line superseding the 2026-09-11 "powered OFF ~22:00" standing fact,
   - and the same line in the Joey TV DECISIONS.md (F7 takes effect).
   **Verify:** a `grep -n "24/7"` of the parent DECISIONS.md shows the new dated line.

4. **Stale overnight comments (Q14, low priority).** Claude prepares a comment-and-doc-only commit for `hub/media_backup.py`, `hub/tasks.py` (follow/awards docstrings) and `docs/connector-contract.md` (grep for "off overnight"; the old line number may have moved):
   the "NAS is off overnight" wording changes to say the NAS is on 24/7. **The Awards sync's 22:00 to 07:00 skip window stays (Q14)**, so no behaviour or test change. You merge it like any PR.
   **Verify:** `git diff` of that commit shows only comments and docs; the suite stays green.

5. **Prove it the next day, then for three days.**
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "uptime"
   ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "ls -lt /volume1/Docker/joey/backups/media | head -n 6"
   ```
   **Verify (day 1):** uptime is more than 24 hours. **Verify (3 consecutive days):** the backup folder gains about one new `media-<date>.db.gz` every 20 to 24 hours. Joey **Server** shows no "Media backup: none in ..." warning.

6. **After ANY reboot or ADM firmware update (power cut, firmware, a manual restart):**
   1. **Swappiness resets to 60 on reboot.** The boot hook `/usr/local/etc/init.d/S99joey-swappiness.sh` sets it to 10 and survived the 2026-10-20 reboot, but its survival across an ADM firmware update is only medium-confidence. Re-check:
      ```powershell
      ssh -i $env:USERPROFILE\.ssh\joey_nas root@192.168.68.59 "cat /proc/sys/vm/swappiness; ls /usr/local/etc/init.d/S99joey-swappiness.sh"
      ```
      **Verify:** `10` and the file listed. If it reads 60 or the file is gone, tell Claude (B. re-runs `sysctl -w vm.swappiness=10` and reinstalls the hook from `nas_scripts/swappiness_boot.sh`).
   2. LAN `/health` first (R4 A3 step 3.1 and 3.2), then the outside curl. Friends' sessions will have dropped; they sign in again.
   3. docker `restart: unless-stopped` should bring swag back by itself; if `docker ps --filter name=joey-swag` shows it not running, `docker compose up -d swag` in `/volume1/Docker/joey/life-dashboard/deploy`. Also confirm `joey-hub` and `joey-connectors` are **Up**, not Created (see the 2026-10-20 incident in R4 Part B).

### Things that change when the NAS stays on

- Disks run continuously (wear and noise); `/volume1` is RAID0, so keep the "Restore media.db" drill and the off-box copy in mind.
- The off-box copy runs from `deploy/media_offsite.sh`; its optional cron hook (`nas_scripts/media_offsite_cron.sh`) re-adds its crontab line only at boot, which on a 24/7 NAS means only after a reboot. Check `crontab -l` shows the line, or run the script by hand weekly.
- Maintenance now lands on a live system: updates and deploys follow R4 (check `JfSessions` first).
- Uptime Kuma now alerts on night-time outages too; expect Discord pings if something drops at 3 am.
- The ADM auto-update/reboot window, if enabled, can restart the NAS during a friend's evening: set it to a quiet hour or disable auto-reboot (exact menu unchecked on this ADM version), and re-check swappiness after each (step 6).
