# NAS: install stackctl beside the media stack

For the hub's Server → Updates **Restart + update media stack** button. Do this once, as root over ssh, AFTER a Joey
deploy that contains `stackctl/` (so `/volume1/Docker/joey/life-dashboard/stackctl/` exists on the NAS — the NAS has no
git binary, so the folder arrives with the normal `deploy.sh` pull, nothing else to copy). Everything below works in
the Asustor BusyBox shell.

## 1. Make the token

```sh
TOKEN=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'); echo "$TOKEN"
```

64 hex characters. It goes in two places (steps 2 and 5) and nowhere else — never in chat, a commit or a screenshot.
Treat it like a root password: whoever holds it can recreate every media container.

## 2. stackctl's env file

```sh
printf 'STACKCTL_TOKEN=%s\n' "$TOKEN" > /volume1/media-server/stackctl.env
chmod 600 /volume1/media-server/stackctl.env
```

## 3. Check the names before adding the service

```sh
cd /volume1/media-server
docker compose config --services          # the compose SERVICE names
grep -n 'env_file' docker-compose.yml     # any env_file outside /volume1/media-server?
```

- stackctl skips the services named in `EXCLUDE` (default `wud stackctl`). If WUD's **service** key is not `wud`
  (e.g. `whatsupdocker`), set `EXCLUDE` in the block below to the real name plus `stackctl`.
- If an `env_file` (or anything compose itself reads, not a container bind mount) lives outside
  `/volume1/media-server`, add it to stackctl's `volumes:` read-only at the SAME path, or `compose config` fails inside it.

## 4. Add the service

Append under `services:` in `/volume1/media-server/docker-compose.yml` (same indentation as the other services):

```yaml
  stackctl:
    container_name: stackctl
    build: /volume1/Docker/joey/life-dashboard/stackctl
    env_file:
      - ./stackctl.env
    environment:
      - COMPOSE_FILE=/volume1/media-server/docker-compose.yml
      - EXCLUDE=wud stackctl
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      # the SAME path as on the host: relative binds, .env and the project name resolve as when you run compose here
      - /volume1/media-server:/volume1/media-server
      # compose reads this service's build path while loading the file; read-only, same path
      - /volume1/Docker/joey/life-dashboard/stackctl:/volume1/Docker/joey/life-dashboard/stackctl:ro
    ports:
      - "192.168.68.59:8810:8810"   # NAS LAN address only - never through the tunnel
    labels:
      - wud.watch=false
    restart: unless-stopped
```

Then build and start only stackctl:

```sh
cd /volume1/media-server
docker compose up -d --build stackctl
docker logs stackctl                      # "stackctl: listening on :8810, compose file ..., exclude 'wud stackctl'"
```

`build:` is used (not `image:`) because nothing is published to a registry: compose builds the image from the Joey
checkout on the NAS. `docker compose pull` skips a build-only service, and `wud.watch=false` keeps WUD from offering it.

## 5. Check it before the hub uses it (nothing is restarted here; same shell as step 1, so `$TOKEN` is set)

```sh
docker exec stackctl docker version --format '{{.Client.Version}} -> {{.Server.Version}}'
docker exec stackctl docker compose -f /volume1/media-server/docker-compose.yml ps
docker exec stackctl docker compose -f /volume1/media-server/docker-compose.yml config --services
wget -qO- --header "Authorization: Bearer $TOKEN" http://192.168.68.59:8810/status; echo
wget -qO- http://192.168.68.59:8810/status; echo   # no token: must fail with 401
```

- `ps` must list the RUNNING media containers (jellyfin, radarr, ...). An empty list means the project name doesn't
  match (e.g. the stack was started with `-p` or from another folder): stop and fix that first, or a run would create
  duplicates.
- `/status` with the token: `{"running": false, "started_at": null, "finished_at": null, "exit_code": null, ...}`.

## 6. Hub env

Add to `/volume1/Docker/joey/life-dashboard/deploy/hub.env` (or `deploy/.env` if hub.env isn't split out yet;
`chmod 600`):

```sh
STACKCTL_URL=http://192.168.68.59:8810
STACKCTL_TOKEN=<the same 64 hex characters>
```

Then recreate the hub so it reads them: `/volume1/Docker/joey/life-dashboard/deploy/deploy.sh --force`.
`/server` → Updates now shows **Restart + update media stack** and a "Media stack · No run yet" line. Without these
two lines the button is hidden and the line reads "Not connected".

## Updating or removing stackctl

- New stackctl code arrives with a Joey deploy; rebuild it by hand (stackctl never recreates itself):
  `cd /volume1/media-server && docker compose up -d --build stackctl`.
- Remove: delete the `stackctl:` block, `docker rm -f stackctl`, delete `stackctl.env`, and drop the two hub lines.
- Rotate the token: repeat steps 1, 2 and 6, then `docker compose up -d stackctl` and redeploy the hub.
