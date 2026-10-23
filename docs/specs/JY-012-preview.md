# JY-012 Preview slot `joey-preview` on the NAS

Status: shipped 2026-10-23
Size: L
Live risk: NAS write (a second compose project; live data read-only)
Area: `deploy/preview/`, `scripts/joey_preview.py`, one line in `scripts/joey.py`, `tests/scripts/`, `tests/deploy/` (preview compose checks), `deploy/README.md` (one section)
Needs: JY-010 (shipped). Hands: JY-014 (B. adds the `preview.joeyhome.net` hostname)
Options page: none: no new screen (the preview shows the branch's own screens)

Ready on B.'s plan approval (2026-10-23, "Go with all recommendations"; Q7 A: one `joey-preview` hub at `preview.joeyhome.net`, Access-gated, live data read-only, sample data for connector changes).

## Problem
B. accepts on production, after the deploy. He should try a branch on his own phone or TV before it merges, without risk to the live system and without breaking the NAS memory floor.

## Acceptance criteria
1. `deploy/preview/docker-compose.yml` defines compose project `joey-preview` with one service, container `joey-preview`: the hub image built from the previewed commit (tag `life-hub-preview`), `mem_limit` 256m, json-file log rotation as the main stack, no published ports, joined to the main stack's default network as an external network so the tunnel reaches `http://joey-preview:8000`. No connectors.
2. Live data read-only: the live snapshots directory is mounted `:ro`. `media.db` is a copy: the newest daily backup from `/volume1/Docker/joey/backups/media` restored into a preview-only data dir (`/volume1/Docker/joey/preview/`). The live `media.db` and its directory are never mounted.
3. No writes to the live system (`CLAUDE.md` rule 7). Every background loop the hub has is off (at least `MEDIA_BACKUP`, `PLAY_RECORDER`, `MEDIA_WARMUP`, `MEDIA_FOLLOW`, `MEDIA_AWARDS`, the digest; find the full list in `hub/`). The preview's env is built from an allow-list of keys, not a copy of `.env`: keys that can only read (Jellyfin for posters and lists, OMDb, weather, the Access audience the hub checks) are in; keys that can change the live system (Radarr, Sonarr, Seerr, qBittorrent, Prowlarr, stackctl, WUD, Discord webhooks, the tunnel token) are out, so a "request" or "restart" on the preview fails visibly. The builder lists each `.env.example` key with in/out and the reason in `deploy/preview/README.md`. The preview env file lives only on the NAS, chmod 600, and never enters git or a log.
4. `python scripts/joey.py preview up <branch | PR number>`: refuses outside 07:00–21:30 Melbourne time, while a deploy holds `/tmp/joey-deploy.lock`, or when NAS available memory is under 1,400 MB (1,200 floor + preview headroom). Then: checks out the exact commit into `/volume1/Docker/joey/preview/src` (the `alpine/git` container and the read-only deploy key, as `deploy.sh`), builds the image, restores the media.db copy, starts the slot, waits for `/healthz` inside the container (poll, no bare sleep), and prints the commit, the URL and the memory reading. If available memory falls under 1,200 MB after start, it tears the slot down and FAILs.
5. One slot. `preview up` with the slot already running replaces it (down, then up) and says which commit it replaced.
6. `python scripts/joey.py preview down`: `docker compose -p joey-preview down`, removes the preview image and the media.db copy. Afterwards no container, network or image named for the preview exists (checked and printed).
7. `python scripts/joey.py preview status`: running or not, commit, uptime, memory use, NAS available memory.
8. `deploy.sh` and the main stack are untouched. A main deploy while the slot runs is safe: the main project's `--remove-orphans` does not see the preview project (prove it in a test that reads both compose files, or say why it cannot be tested).
9. Every step PASS / FAIL / SKIP / DRY through the JY-010 runner and log; `--dry-run` prints every step and command; no secret, URL with credentials or user name in any output.
10. Tests (no network, no NAS): the compose file (mounts read-only, no live sqlite dir, mem_limit, external network, no ports), the env allow-list (every `.env.example` key classified; no write-capable key in), each refusal in 4, replace-on-up in 5, and the dry run.
11. Live (orchestrator, inside the window): `preview up main` serves `/healthz` inside `joey-preview`; NAS available memory stays at or above 1,200 MB (numbers in the PR); `preview down` leaves nothing running. After B.'s JY-014 hostname: `curl -I https://preview.joeyhome.net` shows the Access redirect.

## Data
Reads the live snapshots (`:ro`) and the newest media backup. Writes only under `/volume1/Docker/joey/preview/` and the `life-hub-preview` image.

## Performance budget
NAS available memory ≥ 1,200 MB with the slot up (measured and in the PR). joey-preview memory ≤ 200 MiB (same budget as joey-hub), measured with `docker stats`.

## Options and the pick
None: no screen.

## Out of scope
Connector previews (sample data, a later item). Cloudflare hostname and Access (JY-014, B.'s hands). Auto-teardown on a timer.

## Accept checklist
- CI green; two separate reviews and the Opus verifier posted on the PR.
- The live `up` / `status` / `down` output in the PR.
- After JY-014: B. opens `https://preview.joeyhome.net` on his phone and sees the previewed branch (footer or `/healthz` commit).

## Questions for B.
None. (If the read-only key list in 3 leaves a screen B. would want to try on the preview unusable, the builder notes it and the orchestrator asks.)

## Shipped notes
- PR #51, squash commit `d6fb047`. Builder Opus. Reviews: A (live safety, Sonnet) FAIL with 2 must-fix, B (correctness, Sonnet) PASS; one fix round; Opus verifier PASS. 125 tests in `tests/scripts/` + `tests/deploy/test_preview_compose.py`.
- Orchestrator decisions in the fix round: the live `JELLYFIN_URL` is the NAS LAN IP (reachable from `deploy_default`, so no `media` network); `JELLYFIN_API_KEY` is OUT under rule 7, because it reaches live writes in `hub/media_resume.py`. Posters show from the live img cache mounted `:ro` (cache hits only); Jellyfin-backed rows fail visibly on the preview.
- Also fixed in `scripts/joey_common.py`: `ssh_run` sends stdin as UTF-8 bytes (Windows text mode turned LF into CRLF) and scrubs the NAS user and host from its error.
- Rule 4, dated: three JY-010 assertions in `tests/scripts/test_joey_worktree.py` were re-pinned from text-mode to bytes stdin, and the pinned COMMANDS set gained `preview`. Each has a dated comment in the test; none is weaker.
- Accept: B. in the orchestrator session: "Yes: merge Phase 2 PRs on green CI plus a clean separate-agent review, without asking me for accepted each time. Record my accept as this message."
- Live run, inside the window, at commit 26de4e6: `preview up main` PASS=15 (`/healthz` after 2 polls; NAS available 1677 MB before, 1589 MB after; joey-preview 73.51 MiB of 256); `status` PASS; `down` PASS=5, nothing left; a second `status` shows not running, NAS available 1663 MB.
- Deployed: history `PASS prev=387511d new=d6fb047 suite green, smoke ok`. The old close-out script's `verify.2` read joey-media "starting" once more; a read-only re-check 2 minutes later showed all three containers healthy. JY-011's wait-and-retry covers this.
- NAS clone remote repointed from `benjiEdwards2/life-dashboard` to `benjiEdwards2/Joey` in the same window; `ls-remote` over the deploy key returns main.
- Not yet checked: `curl -I https://preview.joeyhome.net` (needs B.'s JY-014 hostname).
- Follow-ups: JY-228 (preview takes the deploy lock during its build; pin `JOEY_FRONT: ""`; fix the JELLYFIN_URL reason wording). A hub read-only switch, if B. wants Jellyfin rows on the preview, would be its own item.
