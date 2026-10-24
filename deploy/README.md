# deploy

Compose file, `.env.example` and `deploy.sh` — the ONLY path to production (rule 13). Runbook:

- **Deploy:** `ssh root@<nas> /volume1/Docker/joey/life-dashboard/deploy/deploy.sh` (`--force` redeploys an unchanged SHA).
- **Detached + logged (2026-10-20):** deploy.sh re-runs itself under `setsid` (own session, HUP ignored, stdin
  `/dev/null`) and writes everything to `deploy/logs/deploy-<UTC>-<pid>.log` (ignored by git and docker). Your terminal
  just follows that log and ends with the deploy's exit code. Closing the laptop, a dropped ssh session or Ctrl-C only
  stops the watching: the deploy, rollback included, runs to the end. **Re-attach:** `ssh root@<nas>` then
  `tail -f /volume1/Docker/joey/life-dashboard/deploy/logs/<newest>.log` (`ls -t deploy/logs | head -1`); the outcome
  line still lands in `history.log`. A second deploy started meanwhile prints the running one's pid and log path, then exits 2.
  If the NAS has no `setsid`, deploy.sh warns that only HUP is ignored: keep that session open. Stop a running deploy
  only if you must, with `kill <pid>` (TERM, logged `ABORTED`); never mid `compose up`. For a plain foreground run,
  `JOEY_DEPLOY_DETACHED=1 deploy.sh`.
- **From your computer:** `JOEY_NAS=root@<nas> deploy/push.sh` lists every update on GitHub main the NAS is not running
  yet, asks, then runs deploy.sh over ssh. `--list` (no deploy), `--search WORD` (pending updates mentioning WORD),
  `--all [N]` (last N updates, deployed or not), `--history [N]` (last N deploys), `--yes` (no question). Mac / Linux /
  Git Bash on Windows.
- **What it does:** detach (log file) → lock → `git pull --ff-only` (up to 3 attempts, 5 s apart) → `compose config` → memory check → build `life-test` and run the full suite offline
  (`--network none`) → `compose build` + `up -d` → smoke (`/healthz`, `tests/deploy/smoke.py`, nothing restarting) → prune.
  A red gate resets the tree to the previous SHA and leaves the live stack alone; a failed build/up/smoke rolls back.
- **Gate /tmp is in RAM (JY-235, 2026-10-24):** the gate runs `life-test` with `--tmpfs /tmp:rw,exec,size=512m,mode=1777
  -e TMPDIR=/tmp` and `pytest -q -n 2 -o tmp_path_retention_policy=failed tests/`. On the NAS overlay disk the SQLite-heavy
  tests took the suite to 996 s; on tmpfs it is 192 s (quiet NAS, available ≥ 1,381 MB, swap ≤ 1,010 MB). Keep `exec`:
  Docker's tmpfs is noexec by default and git then skips a test's hook (a red gate). Retention=failed keeps only failing
  tests' tmp dirs, so 512m holds the run.
- **Memory check before the gate (JY-240, 2026-10-24):** the gate costs ~400–520 MB of available memory with `-n 2` but
  ~243 MB with `-n 1` (JY-235 and the 2026-10-24 measurement), so `deploy.sh` reads `/proc/meminfo` first and adapts
  (variables at the top of the script):

  | Available just before the gate | Gate |
  |---|---|
  | ≥ 1,720 MB (`GATE_FULL_AVAIL_MB`) | `-n 2` |
  | 1,460–1,719 MB (`GATE_MIN_AVAIL_MB`) | `-n 1` (about 342 s) |
  | < 1,460 MB, or swap used > 1,273 MB (`GATE_MAX_SWAP_MB`), or MemAvailable unreadable | skipped |

  The output and the history line carry the mode and the available MB: `gate=-n1 avail=1588` (or `gate=-n2 ...`,
  `gate=skip avail=1400`). On `PASS` and `GATE-FAIL` the tag follows the existing text, so close-out and the budgets
  readers (they match ` PASS `, `new=` and `dur=`) are unaffected. A skip prints `SKIPPED-LOW-MEMORY (<reason>)`, logs that
  word, resets the tree to the previous SHA (as a red gate does), leaves the live stack alone and exits 1. Free memory (stop the preview, pause qBittorrent), then rerun `deploy.sh`. The
  skip is not green: `scripts/joey.py close-out` refuses the next deploy until a later green run or `--after-fail`.
- **History:** `tail deploy/history.log` — one line per run: `PASS`, `NOTHING-TO-DEPLOY`, `GATE-FAIL`,
  `SKIPPED-LOW-MEMORY` (gate not run; free memory, rerun), `ROLLED-BACK`, `ROLLBACK-FAILED` (both SHAs unhealthy: act now)
  or `ABORTED` (died early; tree reset, just rerun), with `dur=NNNs`.
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
- **Guest front `joey-media` (Joey TV WP-B1):** the same `life-hub` image run with `JOEY_FRONT=media`, served by the tunnel at
  `media.joeyhome.net` (`docs/network.md`). It sits behind `profiles: [media]`, so it is **dark** until `COMPOSE_PROFILES` in
  the NAS `deploy/.env` gains `media` (WP-B5 step 1). **Never enable it before WP-B2**, which makes the owner helpers
  fail-closed; until then a friend session would not be separated from B.'s data. It has no build, no pull and no published
  port, `depends_on` `hub` healthy (hub migrates `media.db` first), snapshots `:ro`, no backups mount, a 384m ceiling.
  - **`media.env`:** NAS-only, `chmod 600`, the only secrets file it reads (never `.env` or `hub.env`). Template
    `deploy/media.env.example`, built on the NAS by `nas_scripts/media_env.sh` (`docs/setup.md`).
  - **Restart rule:** `media.env` is an `env_file`, read at container start, and owner ids are resolved once per process.
    After editing `media.env`, a new `JELLYFIN_USER_ALIASES` entry or a new friend user, run
    `docker compose up -d hub joey-media` (both), not a reload.
  - **Smoke:** when the profile is on, `deploy.sh` waits for `joey-media` and runs `tests/deploy/smoke.py --front media`
    inside it (`/healthz` front, private paths 404, `/` 303). The live route sweep for the go-live gate is
    `tests/deploy/route_sweep.py --base https://media.joeyhome.net`.
  - **Same rule as swag:** never take `media` out of `COMPOSE_PROFILES` without the kill-switch runbook (`docs/public-edge.md`).
  - **Never bind a single file `:ro` into it.** A single-file bind pins the file's inode: an editor or `git pull` that
    replaces the file leaves the container on the old copy until a recreate (the swag confs, above). Mount directories.
- **Joey TV app releases (Joey TV WP-B8, 2026-10-21):** after smoke passes (and on NOTHING-TO-DEPLOY) `deploy.sh` runs
  `deploy/tv_publish.py` in the `life-hub` image: it pulls the GitHub Release `tv-<versionCode>` for the tree's `tv/VERSION` into
  `/volume1/Docker/joey/data/tv-app`, which `joey-media` mounts read-only (`TV_APP_DIR=/data/tv-app`, served at
  `https://media.joeyhome.net/app/` by `hub/tv_app.py`). The token is `GH_TV_TOKEN` in the NAS-only `deploy/tv.env`
  (template `deploy/tv.env.example`; absent = `tv=skipped:no-token`). It never fails a deploy and never runs inside rollback: the
  history line ends `tv=<token>` (`published:<code>`, `current`, `pending:<code>`, `skipped:no-token`, `FAIL:<reason>`). A TV
  release alone does not recreate swag. Cut a release, tokens, signing key, token renewal: `docs/tv-release.md`.
- **Stale lock:** the lock (`/tmp/joey-deploy.lock`) holds the running deploy's pid and log path. A lock whose pid is
  dead is cleared by the next deploy at once; a lock with no pid is cleared after 30 min. By hand, only when nothing is
  running: `rm -rf /tmp/joey-deploy.lock`.
- **Env files:** `.env` (all keys today; `TUNNEL_TOKEN` for compose) plus optional `hub.env` / `connectors.env`, which
  override `.env` per service, and the NAS-only `edge.env` (Cloudflare token for swag and ddns) — the split is at the top of `.env.example`; keep them all `chmod 600`. Setting notes:
  `docs/setup.md`.
- **Volumes:** hub backups land in `/volume1/Docker/joey/backups/media` (uid 1000); connectors see only the snapshots dir.
- **Off-box media.db (Joey TV WP-A6b):** `sh deploy/media_offsite.sh` on the NAS as root pushes the newest dump from
  `backups/media/`, age-encrypted, to the private repo `benjiEdwards2/joey-offsite-backup` (`media/`, newest 14);
  `--dry-run` shows the one file it would send. Not run by `deploy.sh`. Restore drill: `docs/public-edge.md` "Restore media.db".
- **Preview slot `joey-preview` (JY-012):** `python scripts/joey.py preview up <branch | PR>` / `down` / `status` from the
  laptop runs one preview hub beside the stack: its own compose project (`deploy/preview/docker-compose.yml`, so
  `--remove-orphans` here never touches it), joined to `deploy_default`, live snapshots `:ro`, a media.db copy from the
  newest backup, allow-listed keys only, every background loop off. Window 07:00-21:30, refused while a deploy holds the
  lock or under 1,400 MB available. Before a `docker compose down` of this stack, run `preview down`. Runbook and the
  env key list: `deploy/preview/README.md`.
