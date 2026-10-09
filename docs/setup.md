# Dev clone setup

Hooks don't clone with a repo — every fresh clone does this once:

```
git clone https://github.com/benjiEdwards2/life-dashboard.git
cd life-dashboard
pip install --user -r hub/requirements.txt -r requirements-dev.txt
git config core.hooksPath scripts/hooks
```

That last line installs the **money pre-commit guard**
(`scripts/precommit_money_guard.py`): it blocks any staged plaintext money data —
files under `connectors/money/` or any `*.csv`/`*.db` that isn't `.age`-encrypted
or allowlisted, and any staged line shaped like a bank transaction row. The
`.gitignore` rules (WP0) are the first layer; this hook is the second.

Run the suite from the repo root (fixture-mode, no credentials, no network):

```
python -m pytest -q tests/
```

Dev hub with demo data:

```
python -m hub.seed_demo
set SNAPSHOT_DIR=data/demo-snapshots && python -m uvicorn hub.main:app --port 8800
```

## Env files on the NAS (deploy/.env, optional hub.env / connectors.env)

All secrets live in `deploy/` on the NAS only, never in git. Today one `deploy/.env` feeds both the hub and
the connectors (compose `env_file`) and supplies `TUNNEL_TOKEN` to cloudflared by interpolation. Since
2026-10-09 (review D-05) compose also reads the optional `deploy/hub.env` and `deploy/connectors.env`, so each
container can carry only its own keys; a key there overrides the same key in `.env`. The key-by-key split is
at the top of `deploy/.env.example`. Once `.env` holds only `TUNNEL_TOKEN`, remove `- .env` from both
`env_file` lists so no app container carries the tunnel token. Keep all three files `chmod 600`.

## Signed-in user (deploy/.env, on the NAS only)

Since 2026-10-06 the hub reads who is looking from Cloudflare Access's `Cf-Access-Authenticated-User-Email`
header, and that person's view (you / her) is authoritative — the Both / You / Her switcher is gone.
`OWNER_EMAIL_YOU` is B.'s own Access login address, set only in the NAS `.env` (the example file holds a placeholder);
that address is "you", any other address Access admits is "her". It must be the real Access email, not the example value:
left at the placeholder, every signed-in person is treated as "her" (this happened 2026-10-06).
Unset or blank (2026-10-09, review H-38) it counts as not configured: signed-in people get the "both" view and no
owner, and the hub logs one warning — nothing is written as "her" by accident.
`OWNER_NAME_YOU` (default Benji) and `OWNER_NAME_HER` (default Georgina) are the display names (both optional).
The other person's email address is never recorded — not in `.env`, the repo, tests or docs.
Without the header (local dev on port 8800, tests) the page shows "Not signed in" and the old
`?owner_view=` query + cookie still pick the view; send the header with curl to preview the signed-in state.

## Media env (deploy/.env, on the NAS only)

`JELLYFIN_URL` + `JELLYFIN_API_KEY` feed the connectors and the hub's `/img` proxy;
`JELLYFIN_USER` (optional) picks whose "up next" shows, default the first administrator.
`JELLYFIN_USER_HER` (2026-10-05, optional) is the exact display name of Georgina's Jellyfin user —
B. creates that account in Jellyfin; unset, her view shows a quiet word and never falls back to the
admin. Radarr/Sonarr/Jellyseerr URL + key pairs are in `deploy/.env.example`; the hub also uses the
Jellyseerr pair live for Discover & Search. `QBIT_URL` + `QBIT_USER` + `QBIT_PASS` (2026-10-06) are the
qBittorrent Web UI LAN address (NAS IP, port 8080) and a permanent Web UI login set in qBittorrent → Options → Web UI
(the linuxserver image otherwise prints a throwaway password each start); read-only, on the 2-min loop. `media.db` is backed up nightly into
`/volume1/Docker/joey/backups/media` (the host dir must be owned by uid 1000).

Metacritic (media-ux4, 2026-10-08): `OMDB_API_KEY` (optional) is a free OMDb key (omdbapi.com, 1,000 calls a day). The
hub looks up a title's Metascore by IMDb id when its film page opens, at most once per title per 7 days and at most 800
calls per process per day; unset, the film page simply has no Metacritic pill. It reaches the hub like the other media
keys, through `deploy/.env` (compose `env_file`).

Awards (2026-10-08): `AWARDS_CONTACT` (required for the sync) is the contact the Wikimedia User-Agent policy asks for —
B.'s email address, set in the NAS `deploy/.env` only (`append_env.sh`), never in the repo; the hub sends it in
`User-Agent: Joey/awards (+https://joeyhome.net; <contact>)`. Unset, the Awards sync makes no calls and the Awards tabs say
"Not synced yet". `MEDIA_AWARDS=off` stops the loop altogether (default on). The first passes backfill ~400 ceremonies, 40 every
6 h (~2½ days), then weekly on Sundays; watch `docker logs` for "awards: 40 editions, N rows, 0 failed". One edition by hand:
`docker exec -i <hub container> python - --edition oscars:97 < scripts/awards_sync.py`.

Play recorder (2026-10-06): the hub polls Jellyfin `/Sessions` every `PLAY_POLL_SECONDS` (default 60) into `media.db`;
set `PLAY_RECORDER=off` to stop it. It needs the same `JELLYFIN_URL` + `JELLYFIN_API_KEY`.

## Optional knobs (unset = default; listed commented-out at the end of `deploy/.env.example`)

- `MEDIA_BACKUP` — `off` stops the nightly `media.db` gzip backup (hub; default on).
- `MEDIA_WARMUP` — `off` stops the background poster/ratings warm-up; `shelves` keeps only the home-shelf pass (hub; default on).
- `PLAY_RECORDER` — `off` stops the Jellyfin play recorder (hub; default on, needs the Jellyfin URL + key).
- `PLAY_POLL_SECONDS` — play-recorder poll interval in seconds, minimum 1 (hub; default 60).
- `META_CACHE_DIR` — disk cache for Jellyseerr bodies and ratings (hub; default `<IMG_CACHE_DIR>/meta`).
- `RADAR_LOOP` — `1` also fetches the parked BOM radar loop with the weather (connectors; default off, Windy is the radar).
- `AREAS_PATH` — area registry file (hub; default `config/areas.yaml` in the image).
- `SYSTEM_VOLUMES` / `SYSTEM_VOLUME_LABELS` — set in `docker-compose.yml`, not `.env`: statvfs targets (the snapshots dir,
  which reports `/volume1`'s numbers) and the `path=label[,path=label]` names the Server area shows.
