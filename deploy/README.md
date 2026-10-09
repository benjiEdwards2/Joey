# deploy

Compose file, `.env.example` and `deploy.sh` — the ONLY path to production (rule 13). Runbook:

- **Deploy:** `ssh root@<nas> /volume1/Docker/joey/life-dashboard/deploy/deploy.sh` (`--force` redeploys an unchanged SHA).
- **What it does:** lock → `git pull --ff-only` → `compose config` → build `life-test` and run the full suite offline
  (`--network none`) → `compose build` + `up -d` → smoke (`/healthz`, `tests/deploy/smoke.py`, nothing restarting) → prune.
  A red gate resets the tree to the previous SHA and leaves the live stack alone; a failed build/up/smoke rolls back.
- **History:** `tail deploy/history.log` — one line per run: `PASS`, `NOTHING-TO-DEPLOY`, `GATE-FAIL`, `ROLLED-BACK`,
  `ROLLBACK-FAILED` (both SHAs unhealthy: act now) or `ABORTED` (died early; tree reset, just rerun), with `dur=NNNs`.
- **Manual rollback:** take a `prev=` SHA from history.log, then
  `docker run --rm -v /volume1/Docker/joey/life-dashboard:/work -w /work alpine/git reset --hard <sha>` and, in `deploy/`,
  `docker compose build && docker compose up -d --remove-orphans`. The next `deploy.sh` pulls forward again.
- **Stale lock:** "another deploy is running" with nothing running → `rmdir /tmp/joey-deploy.lock` (auto-cleared after 30 min).
- **Env files:** `.env` (all keys today; `TUNNEL_TOKEN` for compose) plus optional `hub.env` / `connectors.env`, which
  override `.env` per service — the split is at the top of `.env.example`; keep them all `chmod 600`. Setting notes:
  `docs/setup.md`.
- **Volumes:** hub backups land in `/volume1/Docker/joey/backups/media` (uid 1000); connectors see only the snapshots dir.
