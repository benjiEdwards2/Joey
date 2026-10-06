# Server → Update now — live check (WP-U1, 2026-10-06)

Run once after deploying WP-U1, before trusting the button on anything important.
The hub calls WUD 9.3 `POST /api/containers/{id}/triggers/dockercompose/local` (no body,
HTTP Basic from `.env`). WUD itself does **not** honour `wud.trigger.exclude` on that
endpoint — the hub's `auto` check is the only guard, so step 2 matters.

## 0. Prove the endpoint from the NAS first (read-only)

From the compose folder on the NAS (where `.env` lives):

```sh
set -a; . ./.env; set +a; curl -s -u "$WUD_USER:$WUD_PASS" "$WUD_URL/api/containers/$(docker inspect -f '{{.Id}}' homepage)/triggers"
```

Expect a JSON list that includes `"type":"dockercompose"` and `"name":"local"`. That proves the
login, that WUD's container `id` is the Docker container id, and that the trigger applies to
homepage. Repeat with `uptime-kuma`: `dockercompose.local` must NOT be in its list.
`401` = wrong login; `403` = the WUD user lacks the write role (`admin`/`rw`) the run endpoint needs;
`404` = WUD does not know that container id.

## 1. Pick a safe container

Use `homepage` (or any non-critical container that WUD currently shows with an update). Never
gluetun, qbittorrent, prowlarr, uptime-kuma or wud — the page shows those as "Manual · excluded".

## 2. Confirm page

Open `/server#updates`. Check the excluded five show "Manual · excluded" and no Update now
button. Click **Update now** on the safe row: the confirm page must show container, image,
current → new tag, kind and the "about a minute" warning.

## 3. Click

Press **Update <name> now**. Expect a redirect to `/server#updates` with
"Update requested for <name>" and "Requested just now" on the row. "WUD refused (HTTP n)" or
"WUD unreachable" means no update happened — see the codes in step 0.

## 4. Watch WUD

In the WUD UI (port 3030) and the Discord channel, confirm the container was recreated on the
new image, and that the app answers again within about a minute.

## 5. Row clears on the next hourly sweep

After the next `wud` sweep (hourly) the row leaves Updates and "Requested …" disappears. If the
row is still there with the same tag, the trigger ran but the image did not change — check the
WUD log.
