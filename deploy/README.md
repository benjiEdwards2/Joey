# deploy

Compose file, `.env.example` and `deploy.sh` — the ONLY path to production (rule 13). Runbook:

- **Deploy:** `ssh root@<nas> /volume1/Docker/joey/life-dashboard/deploy/deploy.sh` (`--force` redeploys an unchanged SHA).
- **From your computer:** `JOEY_NAS=root@<nas> deploy/push.sh` lists every update on GitHub main the NAS is not running
  yet, asks, then runs deploy.sh over ssh. `--list` (no deploy), `--search WORD` (pending updates mentioning WORD),
  `--all [N]` (last N updates, deployed or not), `--history [N]` (last N deploys), `--yes` (no question). Mac / Linux /
  Git Bash on Windows.
- **What it does:** lock → `git pull --ff-only` (up to 3 attempts, 5 s apart) → `compose config` → build `life-test` and run the full suite offline
  (`--network none`) → `compose build` + `up -d` → smoke (`/healthz`, `tests/deploy/smoke.py`, nothing restarting) → prune.
  A red gate resets the tree to the previous SHA and leaves the live stack alone; a failed build/up/smoke rolls back.
- **History:** `tail deploy/history.log` — one line per run: `PASS`, `NOTHING-TO-DEPLOY`, `GATE-FAIL`, `ROLLED-BACK`,
  `ROLLBACK-FAILED` (both SHAs unhealthy: act now) or `ABORTED` (died early; tree reset, just rerun), with `dur=NNNs`.
- **Manual rollback:** take a `prev=` SHA from history.log, then
  `docker run --rm -v /volume1/Docker/joey/life-dashboard:/work -w /work alpine/git reset --hard <sha>` and, in `deploy/`,
  `docker compose build && docker compose up -d --remove-orphans`. The next `deploy.sh` pulls forward again.
- **Edge profiles (Joey TV WP-A3):** `swag` (profile `edge`, `joey-swag`, host network mode: nginx binds host 443 itself) and `ddns` (profile
  `ddns`, `joey-ddns`) start only when `COMPOSE_PROFILES` in `deploy/.env` names them (`edge`; `ddns` never while the WAN IP is
  static). Unset, a deploy is unchanged. With `edge` on, the smoke step runs `nginx -t`, `nginx -s reload` and the `/health` curl
  (up to 120 s). Token and `STAGING` live in the NAS-only `deploy/edge.env`, read by swag and ddns only. Runbook and
  kill switch: `docs/public-edge.md`.
  - **Conf changes need a recreate, not a reload:** the swag confs are single-file `:ro` binds, so a running swag sees
    new conf only after a recreate. While `edge` is on, `deploy.sh` force-recreates swag only when the deploy changed a
    file under `deploy/swag/` (or on `--force`; a rollback uses the same diff); for a manual conf change
    outside `deploy.sh`, run `docker compose up -d --force-recreate swag`, not `nginx -s reload`.
  - **Rollback to a pre-edge SHA removes swag:** that tree has no `swag` service, so `up -d --remove-orphans` takes
    `joey-swag` away. `COMPOSE_PROFILES` in `.env` is not in git and **survives rollbacks**, so rolling forward brings
    swag back by itself.
  - **Never toggle `COMPOSE_PROFILES` off without runbook R3** (the kill switch in `docs/public-edge.md`): a deploy with
    the profile off may remove `joey-swag` mid-stream (Q47; checked live at the first edge deploy).
- **Stale lock:** "another deploy is running" with nothing running → `rmdir /tmp/joey-deploy.lock` (auto-cleared after 30 min).
- **Env files:** `.env` (all keys today; `TUNNEL_TOKEN` for compose) plus optional `hub.env` / `connectors.env`, which
  override `.env` per service, and the NAS-only `edge.env` (Cloudflare token for swag and ddns) — the split is at the top of `.env.example`; keep them all `chmod 600`. Setting notes:
  `docs/setup.md`.
- **Volumes:** hub backups land in `/volume1/Docker/joey/backups/media` (uid 1000); connectors see only the snapshots dir.
