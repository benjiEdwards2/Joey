# NAS: install powerctl and prove it once

For the hub's Server page **Power down** pill (JY-274). Do this once, as root over ssh, inside the deploy window
(07:00 to 21:30), AFTER a Joey deploy that contains `powerctl/`. The live test (step 7) needs B. present.

## 1. Make the token

```sh
TOKEN=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'); echo "$TOKEN"
```

64 hex characters. It goes in two files (steps 2 and 4) and nowhere else: never in chat, a commit or a screenshot.
Whoever holds it can power the NAS off.

## 2. powerctl's env file

```sh
cd /volume1/Docker/joey/life-dashboard/deploy
printf 'POWERCTL_TOKEN=%s\n' "$TOKEN" > powerctl.env
chmod 600 powerctl.env
```

## 3. Turn the service on

The service block is already in `deploy/docker-compose.yml` (profile `power`). Add `power` to `COMPOSE_PROFILES` in
`deploy/.env` (comma-separated, e.g. `COMPOSE_PROFILES=media,power`), then:

```sh
cd /volume1/Docker/joey/life-dashboard/deploy
docker compose up -d --build powerctl
docker logs joey-powerctl   # "powerctl: listening on :8811, stop 'docker compose -p media-server stop -t 45', shutdown 'nsenter ... poweroff'"
```

## 4. Hub env

Add to `deploy/hub.env` (or `deploy/.env` if hub.env isn't split out yet; `chmod 600`):

```sh
POWER_URL=http://powerctl:8811
POWER_TOKEN=<the same 64 hex characters>
```

Then `deploy.sh --force` so the hub reads them. `/server` now shows the red **Power down** pill (owner only) and
"Last shutdown: none yet".

## 5. Prove the parts without powering anything off

```sh
docker exec joey-powerctl nsenter -t 1 -m -u -i -n -p -- sh -c 'command -v poweroff; uname -n'
docker exec joey-powerctl docker compose -p media-server ps --format '{{.Name}}'
docker exec joey-powerctl wget -qO- --header "Authorization: Bearer $TOKEN" http://127.0.0.1:8811/status; echo
docker exec joey-powerctl wget -qO- http://127.0.0.1:8811/status; echo   # no token: must fail (401)
```

- A pass here proves only that the binary exists and the namespace entry works, NOT that the shutdown works: only the
  live test (step 7) proves that. Also check `docker exec joey-powerctl nsenter -t 1 -m -u -i -n -p -- ls -l /sbin/poweroff`.
- Line 1 must print the host's `poweroff` path and the NAS host name (not the container id). No `poweroff`: stop and
  set `SHUTDOWN_CMD` in `powerctl.env` to what ADM has (e.g. `... -- /sbin/poweroff`), then repeat.
- Line 2 must list the running media containers (jellyfin, radarr, ...). Empty = the project name is not
  `media-server`: set `STOP_CMD` in `powerctl.env` to the real `-p` name.
- `/status` with the token: `{"pending": false, ..., "stage": "idle", ...}`.

## 6. Before the live test

- Inside the day window, B. present at the NAS (or able to press its power button).
- Nobody is watching or downloading anything that matters. The ADM power schedule still powers it on at 07:00
  (Settings, Hardware, Power); in daytime, the physical button is how it comes back.

## 7. The live test ("prove it", accept checklist item 4)

1. B. opens `/server`, presses **Power down**, types `POWER DOWN`, presses **Power down now**.
2. The page shows "Shutting down in 60 s". Write down the time.
3. Within ~60 s Jellyfin and the other media apps stop; then the NAS powers off (fans and lights out). Note the minute.
4. B. presses the NAS power button. When it is up: `/server` shows "Last shutdown: <minutes> ago by Benji"; the media
   stack comes back by itself (`restart: unless-stopped`); `cat /volume1/Docker/joey/data/sqlite/power.log` has one
   `started` line; nothing in it is a token.
5. ADM's system log shows a normal shutdown, and no disk check / "improper shutdown" warning on boot.

If step 3 does not power off: `docker logs joey-powerctl` and `/status` `log_tail` say which step failed. Fix
`SHUTDOWN_CMD`, `docker compose up -d powerctl`, repeat step 5, then step 7.

## Updating or removing

- New powerctl code arrives with a Joey deploy and is rebuilt by `deploy.sh` (it is in Joey's compose file).
- Turn off: drop `power` from `COMPOSE_PROFILES`, `docker rm -f joey-powerctl`, remove the two hub lines and
  `deploy.sh --force`. Delete `powerctl.env`.
- Rotate the token: repeat steps 1, 2 and 4, then `docker compose up -d powerctl` and `deploy.sh --force`.
