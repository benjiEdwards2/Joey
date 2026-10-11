# NAS: add WUD's manual-only `dockercompose.manual` trigger

For the hub's Server → Updates "Update now" on containers excluded from auto-update
(prowlarr, qbittorrent, uptime-kuma, gluetun). Apply by hand on the NAS; nothing here is run
by the hub.

## Source (WUD 9.3.0)

- `website/docs/configuration/triggers/README.md` (tag 9.3.0), Common Trigger Configuration:
  `WUD_TRIGGER_{trigger_type}_{trigger_name}_AUTO`, boolean, default `true`, "Whether to execute
  the trigger automatically (`false` requires manual execution via UI or API)".
- `app/triggers/providers/Trigger.ts` (tag 9.3.0): schema `auto: this.joi.bool().default(true)`;
  `init()` only registers for container-report events `if (this.configuration.auto)`.
- `app/api/container.ts` (tag 9.3.0) `runTriggerForContainer`: runs the named trigger for the
  container without checking include/exclude labels, so `manual` works on excluded containers.

## Edit `/volume1/media-server/docker-compose.yml`

Under the `wud` service `environment:`, next to the existing
`WUD_TRIGGER_DOCKERCOMPOSE_LOCAL_*` lines, add:

```yaml
      - WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_FILE=/compose/docker-compose.yml
      - WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_PRUNE=true
      - WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_AUTO=false
```

- Set `PRUNE` to match the value `LOCAL_PRUNE` has today. If `local` has any other options
  (e.g. `BACKUP`), copy them across with `MANUAL` in place of `LOCAL`.
- Leave the excluded containers' labels as they are:
  `wud.trigger.exclude=dockercompose.local` only. Do **not** add `dockercompose.manual` to them.
  With `AUTO=false` the `manual` trigger never fires on its own for any container.
- Don't change the `wud` container's own labels. The hub always refuses to update WUD
  ("Update WUD by hand").

Then recreate WUD: `docker compose up -d wud`.

## Check

1. WUD logs show the `dockercompose.manual` trigger starting, with **no** "Registering for auto
   execution" line for it. `local` still logs that line.
2. `GET /api/triggers` lists an entry with `"type":"dockercompose"` and `"name":"manual"`.
3. After the next WUD sweep, an excluded container with an update (e.g. uptime-kuma) is not
   updated by itself. The hub's "Update now" for it then returns "Update requested".

Until this is applied, the hub's manual Update now gets HTTP 404 from WUD (trigger not found)
and shows "WUD refused (HTTP 404)". Nothing is changed when that happens.
