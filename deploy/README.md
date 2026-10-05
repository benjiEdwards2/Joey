# deploy

Compose files, `.env.example`, and `deploy.sh` — the ONLY path to production (WP9).

The hub container mounts `/volume1/Docker/joey/backups/media` as `/data/backups/media` for the nightly
`media.db` backup (2026-10-05). Env names are in `.env.example`; setting notes in `docs/setup.md`.
