# powerctl

A tiny helper that powers the NAS down when Joey's hub asks: it stops the **media-server** stack cleanly, then
shuts the host down. Behind the Server page's red **Power down** pill (`hub/server_power.py`). Added 2026-11-05 (JY-274),
built like [`stackctl`](../stackctl/README.md).

- `powerctl.py`: the whole service, Python 3.12 standard library only, one file.
- `Dockerfile`: `python:3.12-alpine` + `docker-cli` + `docker-cli-compose` + `nsenter`. Runs as **root** on purpose.
- Install and the supervised live test: [`NAS_INSTALL.md`](NAS_INSTALL.md).

## What a power-down does

`POST /power-down` answers `202 {"pending": true}` at once and starts one background job; any further request gets
`409 {"error": "pending"}` until the host is gone (a failed shutdown clears the flag so it can be retried).

1. Wait `GRACE_S` (3 s): the hub's page and its `power.log` line finish first.
2. `STOP_CMD` (default `docker compose -p media-server stop -t 45`): every media container stops cleanly. Capped at
   60 s; a stuck or failed stop is logged and the shutdown goes ahead anyway.
   After a successful (or timed-out) stop it writes the marker `MARKER_PATH` (default `/data/stopped-by-powerctl`,
   the `./powerctl-data:/data` bind mount in `deploy/docker-compose.yml`). `compose stop` marks containers manually
   stopped, so `restart: unless-stopped` leaves them down after a boot; at startup powerctl, if the marker exists, runs
   `START_CMD` (default `docker compose -p media-server start`, 120 s cap), logs it and deletes the marker. Empty
   `MARKER_PATH` = no marker; empty `START_CMD` = marker deleted, nothing started.
3. `SHUTDOWN_CMD`: in the image, `nsenter -t 1 -m -u -i -n -p -- poweroff` (below). **Empty = dry run**: the step is
   logged as "dry run" and nothing is powered off. The code's default is empty; only the Dockerfile sets the real one,
   so tests and a laptop run can never power anything off.

The hub tells the owner "Shutting down in 60 s"; the stop (up to 60 s) and the host shutdown fit inside that.

`GET /status` -> `{"pending", "requested_at", "stage", "exit_code", "log_tail"}` (`stage`: idle, waiting, stopping,
shutting down, shutdown sent, failed).

## The host shutdown command, and why

`nsenter -t 1 -m -u -i -n -p -- poweroff`

- The container shares the host PID namespace (`pid: host`) and is `privileged`, so `nsenter -t 1` enters PID 1's
  mount, UTS, IPC, net and PID namespaces and runs the **host's own** `poweroff` from the host's filesystem. That goes
  through ADM's init and shutdown scripts (services stopped, volumes unmounted cleanly), exactly as `poweroff` typed in
  an ssh root shell would. Nothing is mounted or faked from the container.
- Not `shutdown -h now`: ADM's BusyBox userland may not ship a `shutdown` binary; `poweroff` is present on BusyBox
  systems. The operator checks it exists before the live test (`NAS_INSTALL.md` step 5).
- Not the ADM web API: that needs an admin password in the hub (spec option C, rejected).
- Not a delayed `shutdown -h +1`: the delay lives in powerctl (grace + capped stop), so the job is observable via
  `/status` until the host goes.

Override with `SHUTDOWN_CMD` in `deploy/powerctl.env` if the live test shows ADM needs another command.

## Security

- Every endpoint needs `Authorization: Bearer <POWERCTL_TOKEN>` (constant-time compare); anything else is `401`.
- No token in the environment: powerctl refuses to start.
- The token is never logged; the request log is the request line and status only.
- No published port: only containers on Joey's compose network (the hub) can reach `powerctl:8811`.
- `pid: host` + `privileged` + the Docker socket make it root-equivalent on the NAS. It exposes one action.

## Home Assistant (later, not built)

B. wants "Goodnight" on his phone to turn the NAS off once Home Assistant exists (spec, 2026-11-05 additions). HA makes
exactly the call the hub makes, and this endpoint stays stable for it:

```
POST http://<powerctl address>:8811/power-down
Authorization: Bearer <POWERCTL_TOKEN>
-> 202 started, 409 already pending, 401 bad token
```

e.g. an HA `rest_command` with `method: post` and the header from HA's `secrets.yaml`. HA is not on Joey's compose
network, so at that point powerctl needs a LAN-only published port (`ports: ["<NAS LAN IP>:8811:8811"]`, like
stackctl) or HA calls through the hub. Decide that when HA is installed; a call from HA does not write the hub's
`power.log` (the Server page's "Last shutdown" line only shows hub presses).
