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

## Media env (deploy/.env, on the NAS only)

`JELLYFIN_URL` + `JELLYFIN_API_KEY` feed the connectors and the hub's `/img` proxy;
`JELLYFIN_USER` (optional) picks whose "up next" shows, default the first administrator.
`JELLYFIN_USER_HER` (2026-10-05, optional) is the exact display name of Georgina's Jellyfin user —
B. creates that account in Jellyfin; unset, her view shows a quiet word and never falls back to the
admin. Radarr/Sonarr/Jellyseerr URL + key pairs are in `deploy/.env.example`; the hub also uses the
Jellyseerr pair live for Discover & Search. `media.db` is backed up nightly into
`/volume1/Docker/joey/backups/media` (the host dir must be owned by uid 1000).

Play recorder (2026-10-06): the hub polls Jellyfin `/Sessions` every `PLAY_POLL_SECONDS` (default 60) into `media.db`;
set `PLAY_RECORDER=off` to stop it. It needs the same `JELLYFIN_URL` + `JELLYFIN_API_KEY`. Neither knob is listed in
`deploy/.env.example` yet, so add them there by hand only if you want to change the defaults.
