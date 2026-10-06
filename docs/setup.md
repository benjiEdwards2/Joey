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

## Signed-in user (deploy/.env, on the NAS only)

Since 2026-10-06 the hub reads who is looking from Cloudflare Access's `Cf-Access-Authenticated-User-Email`
header, and that person's view (you / her) is authoritative — the Both / You / Her switcher is gone.
`OWNER_EMAIL_YOU` is B.'s own Access login address, set only in the NAS `.env` (the example file holds a placeholder);
that address is "you", any other address Access admits is "her".
`OWNER_NAME_YOU` (default Benji) and `OWNER_NAME_HER` (default Georgina) are the display names.
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

Play recorder (2026-10-06): the hub polls Jellyfin `/Sessions` every `PLAY_POLL_SECONDS` (default 60) into `media.db`;
set `PLAY_RECORDER=off` to stop it. It needs the same `JELLYFIN_URL` + `JELLYFIN_API_KEY`. Neither knob is listed in
`deploy/.env.example` yet, so add them there by hand only if you want to change the defaults.
