# JY-254 Digest sent just after boot lists services as Down

Status: shipped 2026-10-26
Size: S
Live risk: none
Area: `hub/boot.py` (new), `hub/server_digest.py`, `hub/server_alerts.py`, `tests/hub/test_server_digest.py`, `tests/hub/test_server_alerts.py`, `tests/hub/conftest.py` (one autouse fixture), `docs/hub-changelog.md`, `hub/README.md`
Needs: none
Options page: none: no screen (the Discord text only)

Source: JY-213/214 live checks, 2026-10-26 (`JoeyTV/review/JY-213-214_live_checks_2026-10-26.md`, finding under "First digest").

## Problem
The 24, 25 and 26 Oct digests listed many services as "Down" (26 Oct: Jellyfin, Radarr, Sonarr, Seerr, Prowlarr, qBittorrent, Gluetun, Uptime Kuma, Portainer, WUD). The NAS is off 22:00-07:00. joey-hub starts with it, and the digest loop (`hub/tasks.py`, first tick 90 s after start, then every 5 min) sends as soon as it is past `DIGEST_AT`. At that moment the `media_status` snapshot is from before the shutdown, or from the boot sweep taken while the containers were still starting. These are false alarms.

What the digest can see: it reads the snapshots (`hub.store.get_snapshots`); the "Down" part comes from `media_status` `apps[].up`. That connector runs every ~2 min (`deploy/docker-compose.yml`), so a fresh sample lands within minutes of boot. The boot reference is the hub's own start time: joey-hub starts with the NAS, so hub start is boot to within a minute. `/proc/uptime` was not used: it does not exist on the dev machines and adds nothing the start time does not give.

Same root cause in the push alerts (review, 2026-10-26): `server_alerts.check_once` runs 60 s after the hub start and pushes "X is Down" from the same snapshot, with no grace.

## Fix (the smallest change that fits)
One shared helper, `hub/boot.py` `settled(snaps, now, booted)`: True on the first check where either
- a `media_status` sample taken after the hub started (`updated_at` >= start) shows every app up, or
- `BOOT_GRACE` (15 min, a named constant) has passed since the hub started.

Digest: a capped wait in `tick`; it holds while not settled.

Alerts: while not settled, `check_once` drops the `down:` items and keeps their seen-rows (the `keep` prefix of `sync`). So a service with no sample since start (or still starting) is not alerted, an outage pushed before a restart is not pushed again, and after the grace a still-down service alerts as today. Other Attention items (disk, Kuma, backup, sweeps) are not held.

After the grace window the digest sends whatever the snapshots say, so a service that is still down shows "Down" as before. The hold only delays the send (a real outage costs at most ~15 min, plus up to one 5-min tick); it never changes the text. "Starting" wording was not chosen: a once-a-day message would then never say whether the service came up.

## Acceptance criteria
1. `hub/boot.py`: `BOOT_GRACE = timedelta(minutes=15)`; `STARTED` is the hub start time (aware UTC, set at import); `settled` as above.
2. `server_digest.tick(now=None, booted=None)`: `booted` defaults to `STARTED`. Before `booted + BOOT_GRACE`, the tick posts nothing and writes no row unless the `media_status` snapshot was updated at or after `booted` and every app in it is up.
3. Digest tests (red first):
   - boot + 2 min, `media_status` from before boot with services down: no post, no row.
   - boot + 5 min, a fresh sample with all apps up: posts at once, "All N services up".
   - boot + 5 min, a fresh sample with one app still down: no post.
   - boot + 30 min, a fresh sample with a dead service: posts, and the text says "Down: <name>".
   - boot + 16 min, no sample after boot at all: posts (the cap), and still says "Down" from the snapshot it has.
   - a deploy restart after today's row exists: nothing posted at restart + 2, 5 or 20 min.
   - a restart after `DIGEST_AT` with no row and no fresh sample: held at restart + 0-14 min, sent at + 15 min.
4. `server_alerts.check_once(live, snaps, now=None, booted=None)`: while not `settled`, no `down:` item is pushed and existing `down:` seen-rows are kept.
5. Alert tests (red first): no Down alert at boot + 2 min without a fresh sample; an alert at boot + 20 min for a dead service; an already-running hub alerts a real outage at once; an outage pushed before a restart keeps its row through the grace and is not pushed again.
6. Existing tests run as a hub that started long before (one autouse fixture in `tests/hub/conftest.py` sets `boot.STARTED`); none is weakened, skipped or deleted.

## Data
Reads `media_status` `updated_at` and `apps[].up` (already read). No table change.

## Performance budget
None apply (a background tick, no route).

## Out of scope
- Uptime Kuma's own monitors (`kuma:` items) at boot: not held; Kuma reports its own state.
- Other parts of the digest that may be stale just after boot (WUD updates count, arrivals): they are not "Down" claims.

## Accept checklist
After the next morning boot, the Discord digest arrives a few minutes after 07:30 at most and does not list services as Down that were up; no "Joey Server: X is Down" push arrives for a service that came up.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #186, squash-merged as `48c0e37` (48c0e37a717869a4236bb32a6c079092e6f1c763).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
