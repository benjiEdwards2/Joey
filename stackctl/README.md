# stackctl

A tiny helper that pulls and recreates the whole **media-server** stack (`/volume1/media-server/docker-compose.yml`)
when Joey's hub asks — the one job What's Up Docker can't do (WUD's compose triggers update one container at a time).
Behind the Server page's **Restart + update media stack** button (`hub/server_stack.py`). Added 2026-10-12.

- `stackctl.py` — the whole service: Python 3.12 standard library only (no frameworks), one file.
- `Dockerfile` — `python:3.12-alpine` + `docker-cli` + `docker-cli-compose`. Runs as **root** on purpose: it drives the
  host's Docker through `/var/run/docker.sock`.
- Install on the NAS: [`NAS_INSTALL.md`](NAS_INSTALL.md).

## What a run does

`POST /media/pull-up` starts one background job (a second request while it runs gets `409`):

1. `docker compose -f $COMPOSE_FILE config --services` — every service in the media-server compose.
2. Drop the `EXCLUDE` services (default `wud stackctl`: WUD and stackctl itself are never touched).
3. `docker compose pull <services>` then `docker compose up -d --no-deps <services>` — newest images, containers
   recreated where the image or config changed. Pinned tags (Seerr `v3.5.0`) stay pinned; manual-only apps
   (Jellyfin, gluetun, qBittorrent, Prowlarr, Uptime Kuma) DO update. Joey's own containers are a different compose
   and are never in the list.

`GET /status` → `{"running", "started_at", "finished_at", "exit_code", "log_tail"}` (UTC ISO times; `log_tail` = the
last 50 output lines, ending `exit N`). Exit code: the first failing step's, else `0`.

## Security

- Every endpoint needs `Authorization: Bearer <STACKCTL_TOKEN>` (constant-time compare); anything else is `401`.
- No token in the environment → stackctl refuses to start.
- The token is never logged; an output line that somehow contains it is masked `***`. The request log is the request
  line + status only (no headers). Only service names are taken from `compose config` — never the resolved config,
  which would carry other apps' secrets.
- The port is published on the NAS LAN address only (`192.168.68.59:8810`), never through the Cloudflare tunnel.
  The hub calls it server-side; the browser never sees the URL or the token.
- The Docker socket is root on the NAS: treat `STACKCTL_TOKEN` like a root password.

## Environment

| Variable | Default | Does |
|---|---|---|
| `STACKCTL_TOKEN` | — (required) | The shared Bearer token (also in the hub's env) |
| `COMPOSE_FILE` | `/volume1/media-server/docker-compose.yml` | The compose file — mounted at the **same path** as on the host |
| `EXCLUDE` | `wud stackctl` | Compose **service** names never pulled or recreated (space-separated) |
| `PORT` | `8810` | Listen port inside the container |

Why the same path: compose resolves relative bind paths (`./config`), the `.env` file and the project name
(`media-server`, from the folder name) from where the compose file sits. Mounted at `/compose` instead, a run would
create a second `compose` project pointing at host paths that don't exist.

## Tests

`tests/stackctl/test_stackctl.py` — the Bearer check, the service filter, token masking, the one-job rule and the HTTP
layer with the docker calls faked. The hub side: `tests/hub/test_server_stack.py`.
