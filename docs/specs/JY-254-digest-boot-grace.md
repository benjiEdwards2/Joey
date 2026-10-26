# JY-254 Digest sent just after boot lists services as Down

Status: building
Size: S
Live risk: none
Area: `hub/server_digest.py`, `tests/hub/test_server_digest.py`, `docs/hub-changelog.md`, `hub/README.md` (one line)
Needs: none
Options page: none: no screen (the Discord text only)

Source: JY-213/214 live checks, 2026-10-26 (`JoeyTV/review/JY-213-214_live_checks_2026-10-26.md`, finding under "First digest").

## Problem
The 24, 25 and 26 Oct digests listed many services as "Down" (26 Oct: Jellyfin, Radarr, Sonarr, Seerr, Prowlarr, qBittorrent, Gluetun, Uptime Kuma, Portainer, WUD). The NAS is off 22:00-07:00. joey-hub starts with it, and the digest loop (`hub/tasks.py`, first tick 90 s after start, then every 5 min) sends as soon as it is past `DIGEST_AT`. At that moment the `media_status` snapshot is from before the shutdown, or from the boot sweep taken while the containers were still starting. These are false alarms.

What the digest can see: it reads the snapshots (`hub.store.get_snapshots`); the "Down" part comes from `media_status` `apps[].up`. That connector runs every ~2 min (`deploy/docker-compose.yml`), so a fresh sample lands within minutes of boot. The boot reference is the hub's own start time: joey-hub starts with the NAS, so hub start is boot to within a minute. `/proc/uptime` was not used: it does not exist on the dev machines and adds nothing the start time does not give.

## Fix (the smallest change that fits)
A capped wait in `tick`. The digest holds while the boot health has not settled, and sends on the first tick where either:
- a `media_status` sample taken after the hub started (`updated_at` >= start) shows every app up, or
- `BOOT_GRACE` (15 min, a named constant) has passed since the hub started.

After the grace window the digest sends whatever the snapshots say, so a service that is still down shows "Down" as before. The hold only delays the send (a real outage costs at most ~15 min, plus up to one 5-min tick); it never changes the text. "Starting" wording was not chosen: a once-a-day message would then never say whether the service came up.

## Acceptance criteria
1. `server_digest.BOOT_GRACE = timedelta(minutes=15)`; `server_digest.STARTED` is the hub start time (aware UTC, set at import).
2. `tick(now=None, booted=None)`: `booted` defaults to `STARTED`. Before `booted + BOOT_GRACE`, the tick posts nothing and writes no row unless the `media_status` snapshot was updated at or after `booted` and every app in it is up.
3. Tests (red first):
   - boot + 2 min, `media_status` from before boot with services down: no post, no row.
   - boot + 5 min, a fresh sample with all apps up: posts at once, "All N services up".
   - boot + 5 min, a fresh sample with one app still down: no post.
   - boot + 30 min, a fresh sample with a dead service: posts, and the text says "Down: <name>".
   - boot + 16 min, no sample after boot at all: posts (the cap), and still says "Down" from the snapshot it has.
4. The existing digest tests run with a hub that started long before (an autouse fixture sets `STARTED`); none is weakened, skipped or deleted.

## Data
Reads `media_status` `updated_at` and `apps[].up` (already read). No table change.

## Performance budget
None apply (a background tick, no route).

## Out of scope
- `hub/server_alerts.py` push alerts ("X is Down") at boot: not checked here; if they also fire on boot, that is a separate item.
- Other parts of the digest that may be stale just after boot (WUD updates count, arrivals): they are not "Down" claims.

## Accept checklist
After the next morning boot, the Discord digest arrives a few minutes after 07:30 at most and does not list services as Down that were up.

## Questions for B.
None.

## Shipped notes
