# Joey tech notes

Lessons, gotchas and field notes that cost time once. Builders: read the headings for your area before you start. Each note: what bites, the fix, then where it came from.
Add a note here when you prove a flake or hit a trap (`docs/PROCESS.md`, machine rule). No secrets, keys, tokens, emails or user ids in this file. `<nas>` is the NAS LAN address.
Source tags: LD = project `LifeDashboard/DECISIONS.md`, JT = project `JoeyTV/DECISIONS.md`, mem = session memory notes (all dated). Paths are repo paths.

## NAS shell and BusyBox
- The NAS shell is BusyBox: no bash, no brace expansion, no python3, no git on ADM. Write `sh` scripts, and run Python only inside a container. (where: LD 2026-08-31, 2026-10-12)
- Git on the NAS runs in an `alpine/git` container with the deploy key; manual rollback uses the same container. (where: LD 2026-08-31, `deploy/README.md`)
- `set -o pipefail` works in NAS BusyBox sh and in the gate image's dash, but Ubuntu 24.04's dash (the GitHub runner's `sh`) rejects it. Tests that run a repo script must pick a shell that accepts it (`sh`, `busybox sh`, `bash --posix`). The first Linux CI run found this and the film-page race (see "Hub templates"); the laptop hid both. (where: JY-006, PR #37, `tests/deploy/test_media_offsite.py`, 2026-10-23)
- The hub port is unpublished, so `curl` to `<nas>:8800` returns 000. Read the hub from inside: `ssh root@<nas> 'docker exec -i joey-hub python -' < script.py` (the proven read-only route; the NAS has no python3). (where: LD 2026-10-12)
- ADM Defender (not dockerd) writes the nft DNAT rules that keep real client IPs on published ports, and a container started seconds after another stops gets none. SWAG therefore runs in host network mode. (where: JT 2026-10-19)
- The ADM 6.6 kernel has no REJECT target for iptables-nft: fail2ban must use `banaction = iptables-allports[blocktype=DROP]`. (where: JT 2026-10-19)
- Swappiness resets on every NAS reboot: re-apply `nas_scripts/swappiness_boot.sh` (project folder). (where: JT 2026-10-19, 2026-10-21)
- The NAS is off about 22:00 to 07:00 (Joey TV F7: 24/7 once friends are live; the deploy-window rule stays until `docs/PROCESS.md` changes). Overnight jobs never run (Seerr's 03:00 full scan and 05:00 availability sync never did): move them to daytime. (where: LD 2026-09-11, 2026-10-12; JT F7)
- NAS egress drops DNS and TCP SYNs while qBittorrent saturates the line (Discover 8 s, OMDb/TMDB failures, deploys aborting on github.com DNS). Cap qBittorrent download to about 70 % of the plan before blaming Joey. (where: LD 2026-10-12)
- RAM: swap at or below 1,273 MB and available at or above 1,200 MB. A gate at `pytest -n auto` drove load to 12 and 1.2 GB swap, so the gate uses `-n 2` (CI uses `-n auto`). (where: LD 2026-10-09, `CLAUDE.md`)
- Jellyfin on the NAS sees Docker traffic as remote unless the Docker bridge range is in its LAN list (`172.18.0.0/16` plus the NAS /22). Otherwise Seerr's sign-in, proxied from its container, is refused. (where: JT 2026-10-19)

## Deploy and gate image
- The gate (`life-test` image) runs on UTC with no `.env`, and `.dockerignore` decides what it sees. A test that reads the real clock, `.env` or a `docs/` file can pass on the laptop and fail the gate: a `docs/` file needs its own `!docs/<file>` whitelist line (see "Tests" for the clock). `**/*.env` did not match `*.env.bak-*`, so `append_env.sh` backups (with token values) reached the image and the token-scan test failed the gate; now `**/*.bak-*` is ignored too. Tests that need `node` skip in the gate and run in CI. (where: LD 2026-10-06, 2026-10-14; JT 2026-10-19; `.github/workflows/ci.yml`)
- An unanchored `.gitignore` line `data/` swallowed `connectors/schema/data/*.schema.json`, so fresh clones were broken while the dev tree was green. Root-anchor ignore rules (`/data/`). (where: LD 2026-08-31, commit 8498380)
- A rejected `git push <branch>:main` (non-fast-forward) once went unnoticed and `deploy.sh` shipped another session's main. Check `HEAD == origin/main` and read the push output before deploying. (where: LD 2026-10-06)
- Do not start a deploy in the 15 minutes before 00:00 UTC (10:00 AEST / 11:00 AEDT). Two midnight-UTC tests are frozen (PR #14), but any new test on the real date brings the GATE-FAIL back. (where: JT 2026-10-21, `docs/public-edge.md` R4)
- `deploy.sh` is detached (`setsid`, log in `deploy/logs/`): a closed laptop or dropped ssh no longer kills it. Re-attach with `tail -f` on the newest log. A second deploy exits 2. (where: JT 2026-10-20, `deploy/README.md`)
- The post-deploy smoke waits on `/healthz` (up to a timeout), not a fixed sleep: early rollbacks were fixed-5-s-sleep false alarms. Never add a bare `sleep` to smoke. (where: LD 2026-10-07)
- A single-file `:ro` bind pins the file's inode: `git pull` replaces the file and the running container keeps the old copy. Mount directories; for swag confs, recreate (`up -d --force-recreate swag`), never `nginx -s reload`. (where: JT 2026-10-19, `deploy/README.md`)
- Never toggle `COMPOSE_PROFILES` (`edge`, `media`) off without the kill-switch runbook: a deploy with the profile off removes `joey-swag` mid-stream. The variable lives in the NAS `.env` and survives rollbacks. (where: `deploy/README.md`)
- `media.env` is the only secrets file `joey-media` reads. After editing it, `up -d hub joey-media` (both): owner ids resolve once per process. (where: `deploy/README.md`)
- A `tv/` PR without a `tv/VERSION` bump turns main's `release` job red by design, docs-only edits included. (where: JT 2026-10-21, `docs/tv-release.md`)
- Auto-mode classifier refusals of deploy and merge (2026-10) are historical; Claude merges and deploys (`CLAUDE.md` rule 11). The classifier still refuses Claude editing its own rule files (`CLAUDE.md` gates, DECISIONS), 2026-10-23: B. edits those. (where: LD 2026-10-06; JT 2026-10-21; mem 2026-10-23)

## Secrets and `.env`
- Appending to a NAS `.env` without a trailing-newline check glued a key onto the previous line (`ICS_URL_HER`). Always use `nas_scripts/append_env.sh` (project folder, not this repo: newline guard, CR strip, backup). It only appends: to change an existing line use `sed`. (where: LD 2026-09-11, JT 2026-10-21)
- PowerShell piping into ssh prepends a UTF-8 BOM, and Windows text-mode stdin sends `\r\n`: the key becomes unreadable, and `keytool` refuses a password as "not ASCII". Pipe from the Bash tool, or `scp` the file, or send raw ASCII bytes. Never `\r` in a secret. (where: LD 2026-10-08; JT 2026-10-22)
- Verify a secret by count, never by value or length: `grep -c '^KEY='` (not `grep -c KEY`). A length-only check passed two wrong values (a user name where the admin was meant; a value with a space). (where: LD 2026-10-08; JT 2026-10-19)
- A pasted base64 key rejected and 2 characters short of a multiple of 4 is missing its `==` padding: try padding before asking for a re-copy. (where: LD 2026-10-05)
- Secret txt hand-off files go on the Desktop, never under `Desktop\Claude\` (the GitHub backup syncs it), and are deleted after the count check. Generate passwords as ASCII letters and digits only. (where: LD 2026-09-11; JT 2026-10-22)
- The Access audience tag is not secret (it is in every JWT) but keep it out of files and chat anyway. Access keys load lazily on the first non-loopback request, so a fresh container logs nothing until Joey is loaded through Access. (where: JT 2026-10-21)
- A committed text file with a date, a semicolon and a decimal on one line can trip the money pre-commit guard. Reword the comment. (where: LD 2026-10-05)

## Git, worktrees and merges
- The shared clone may sit on another session's branch, and two merges once landed on `apex-shell`. Always `git branch --show-current` first; build and merge only in your own worktree; never merge or push `main` from the clone. (where: LD 2026-10-06, `CLAUDE.md`)
- Squash merges break `git merge-base --is-ancestor <branch> origin/main`: the branch tip is never an ancestor of the squash commit, so a merged branch looks unmerged. Check `gh pr view` shows MERGED and that the PR head SHA equals the local tip, then `git branch -D` (plain `-d` tests the checked-out branch, not `origin/main`). (where: `docs/PROCESS.md`, mem 2026-10-22)
- The reverse also bit: a branch the HANDOVER called "awaiting push" (`library-grid`) was never pushed and everything after assumed it had landed. Before a round, confirm every branch it relies on really reached `origin/main`. (where: mem 2026-10-22)
- Stacked branches: when A is squash-merged, rebase B with `git rebase --onto origin/main <A's old tip>`. (where: `docs/PROCESS.md`)
- Run the full suite on the merge itself: two older tests failed only on the combination. Re-point them as dated decisions, never weaken them silently. (where: LD 2026-10-16)
- Several agents appending to the changelog, README or the CSS tail produce keep-both conflicts. Give each agent its own dated CSS tail block; resolve by keeping both. (where: LD 2026-10-13, 2026-10-19)
- `git stash` is shared by every worktree of a clone: a `stash pop` in one worktree can apply another builder's stash. Never stash in item worktrees; commit to the item branch instead. (where: JY-153/JY-224 builds, 2026-10-24)
- Under heavy CPU load (several builders running suites) the Windows git credential helper (`gh auth git-credential`) can time out and return nothing, so `git push` falls back to a terminal prompt and fails. Keep one heavy run at a time; retry pushes with `GIT_TERMINAL_PROMPT=0` once load drops. (where: orchestrator, 2026-10-24)
- Run `git status` and `git fetch` before every commit and stage only your item's files; another session edits the same repo constantly. (where: LD 2026-10-05, `CLAUDE.md`)

## Windows laptop, PowerShell and the Bash tool
- B.'s terminal is Windows PowerShell 5.1: no `&&` (use `;`), no `<` redirect, no `$(...)` inside a double-quoted ssh string, `$env:TEMP` can be empty in the Claude panel (use full paths), a bare `cd` line is skipped (use `git -C`). Git Bash lines (`/c/...`, `tr ... <`) fail there. (where: `docs/public-edge.md` R0, JT 2026-10-20/21)
- Long ssh one-liners get mangled in PowerShell and pasted multi-line loops get mangled in Git Bash. Put the commands in a script, `scp` it, and run one short line. (where: LD 2026-10-05; mem 2026-10-19)
- The Bash tool eats backslashes in heredocs and chokes on apostrophes in long JS/JSON. Write patch scripts and data files with the Write tool and run them from a file. (where: LD 2026-10-07; mem 2026-10-14)
- Never `taskkill /IM python.exe`: it kills every session's local hubs and agents. Stop by PID from `Get-NetTCPConnection -LocalPort`. (where: LD 2026-10-06)
- Absolute Unix defaults are live paths on Windows (`/data/sqlite/media.db` resolves to `C:\data\...`); `tests/conftest.py` points them at temp dirs. Add any new path env var there. (where: LD 2026-10-06)
- The work laptop has no admin or Docker and its firewall blocks LAN serving: phone previews go through private artifacts, and installs are user-scope. (where: LD 2026-09-02, global rules)
- `nslookup` through the corporate resolver appends the search suffix even when you name 1.1.1.1: use a trailing dot (`<domain>.`) or DoH from the NAS. (where: LD 2026-09-11, JT 2026-10-19)
- `adb get-state` error text contains the word "device": compare `.strip() == "device"`. (where: mem 2026-10-23)
- Scripts that ssh with stdin text must encode UTF-8 explicitly: cp1252 turned an em dash into `\x97` and a re-enable script died, leaving a Jellyfin user disabled. (where: JT 2026-10-22)

## Jellyfin, Seerr, arr and qBittorrent
- Jellyfin 12.2 wants `Authorization: MediaBrowser Client=..., Token="..."`. The old `X-Emby-Token` and `X-Emby-Authorization` give 400 or 401, and faked 401s count toward fail2ban. (where: JT 2026-10-19, `CLAUDE.md` notes)
- Jellyfin 12.x ignores `AnyProviderIdEquals` (returns everything). Filter client-side on `ProviderIds.Tmdb`. Probe a new upstream query live before trusting a documented filter. (where: LD 2026-10-06)
- Jellyfin 12.2 first-touch item queries take 2.5 to 9.6 s: warm items (`hub/media_warmup.py`), parallel reads, 6 h disk meta cache. (where: LD 2026-10-12)
- Jellyfin counts every live session, Quick Connect included, against the friend template's `MaxActiveSessions`. REST-created sessions and web sign-outs leave sessions behind (`DELETE /Devices`). A refused sign-in is probably this. (where: JT 2026-10-19, 2026-10-22)
- Lockout counts lifetime failed logins and Quick Connect sign-ins do not reset it. Scripts that try wrong passwords must read the count first and refuse when count plus attempts reaches the cap. (where: JT 2026-10-22)
- The Jellyfin 12.2 web UI reverts a user's Access tab: apply the friend template by API (`nas_scripts/joeytest_policy.py`). (where: JT 2026-10-19)
- WUD auto-updated Jellyfin to 12.2 and the old Jellyseerr broke on the new auth headers. Jellyseerr is now `ghcr.io/seerr-team/seerr` and Jellyfin is manual-only (`wud.trigger.exclude`). Check Seerr's Default Server after any Seerr update: it was lost once. (where: LD 2026-10-08, 2026-10-12)
- Seerr: a request quality is the arr quality profile (`profileId` on `POST /api/v1/request`); person credits drop `order`; a request with `X-Api-User` is created as that user. Never use the bare admin key for friends. (where: LD 2026-10-07, 2026-10-21; JT 2026-10-21)
- Sonarr `statistics.percentOfEpisodes` is of aired episodes (3 of 8 files reads 100 %). "Upgrade available" is Sonarr's cutoff-unmet ("wants better"), not "a better release exists"; a Minimum Custom Format Score of 1000 can make every release ineligible. (where: LD 2026-10-19, 2026-10-21)
- qBittorrent downloads stalled on queue limits: max active was 1 download / 2 torrents and a dead 0-seed torrent held the slot. Set 5/10/5 with `dont_count_slow_torrents=true` via the API (B. approved). The earlier BACKLOG proposal (8/12) is superseded. The port forward comes from the VPN provider, not qBit. (where: mem `project_lifedashboard.md` 2026-10-12; LD 2026-10-12; mem VPN Switch 2026-10-12)
- WUD: `updateKind` is only filled when an update exists (read `image.digest.watch` instead); watch by digest with `wud.watch.digest=true` labels. Uptime Kuma metrics use basic auth with an empty user and the API key. (where: LD 2026-10-05, 2026-10-06)

## Cloudflare, edge and TV
- The Deco X50 silently drops external 80 and 443. The public edge is `jellyfin.<domain>:8443` with one forward to NAS:443; hairpin works. A router change is B.'s hands item, not a script. (where: JT 2026-10-19, `docs/public-edge.md`)
- Start every edge probe with the LAN `/health` (`curl --resolve ... <nas>`). `joey-swag` had simply been stopped (a kill-switch rehearsal never undone) while Claude hunted router faults. (where: JT 2026-10-19)
- Never put a kill-switch command in a block beside commands B. should run: a pasted `docker compose stop swag` took the edge down. (where: mem 2026-10-20)
- The guest host (`media.<domain>`) must never get an Access application: guests sign in with Jellyfin. The private apex has one Access app and one allowlist policy; guest and private sign-out are separate. (where: JT 2026-10-22)
- Access OTP: a stale login tab shows "PIN already used", and "Request New Code" invalidates all earlier codes. Use one fresh tab and the newest code. (where: LD 2026-09-03)
- External checkers rate-limit (check-host.net after about 11 requests); `testssl.sh` needs `hexdump`. Grade TLS with an openssl matrix and probe from a phone hotspot. (where: mem 2026-10-20)
- The guest front navigates with htmx boosted swaps (the same document), not full page loads. Any TV focus guard must reset per boosted swap (`htmx:historyRestore`, `keyed = false`) or the Android WebView's refocus of the first control wins. Prove TV fixes before merge with `wp_b9_device.py firstfocus --tvjs` (CDP injection), not by setting focus from JS. (where: JT 2026-10-22, PR #35)
- The TCL TV drops off the LAN in deep standby (no ping, no adb) and the Projectivy launcher hides the Play Store: open listings with `am start market://details?id=...`. Never flip "install unknown apps" for B.: it is his security toggle. (where: mem 2026-10-23)
- Reported in the 2026-10-23 TV review (check HITLIST for a fix): a web sign-out leaves the Jellyfin device behind so `MaxActiveSessions` blocks the next Quick Connect (workaround: remove the stale device with `DELETE /Devices`, see the sessions note above), and Back on `/signin` burns the code. (where: JT 2026-10-23)
- Guest-front owner helpers fail closed: malformed `jf:` raises, and on the media front nothing but you, her or a friend key names an owner. New routes must be classified GUEST, PRIVATE or RESERVED (`tests/hub/test_guest_routes.py`). (where: JT 2026-10-21)

## Tests
- Gate runs on UTC; the hub container runs on Melbourne time; connectors run on UTC. Take "today" from `hub.shell.home_now().date()`, and never build fixtures from the real clock across a day boundary (an event at now + 2 h vanished from "Today" for two hours a day). (where: LD 2026-10-06, 2026-10-14)
- `monkeypatch.setattr(time, "time", ...)` also moves `date.today()`: freeze the one clock on purpose and assert on it, or you move more than you meant. (where: LD 2026-10-13)
- Loopback fake servers bind port 0 (`("127.0.0.1", 0)`) and read the assigned port: no fixed ports, and 127.0.0.1 only so they run under `--network none`. (where: `tests/deploy/test_tv_publish.py`, `tests/stackctl/test_stackctl.py`)
- Do not touch real paths: `tests/conftest.py` sets `MEDIA_DB_PATH`, `MEDIA_BACKUP_DIR`, `SNAPSHOT_DIR`, `META_CACHE_DIR` per test and turns the background loops off. A stray real file made later tests flaky. (where: LD 2026-10-06, `tests/README.md`)
- Assert placement inside `<main>`, never substring counts over the whole page: sections once rendered into `<title>` and a count-based test stayed green. (where: LD 2026-10-05)
- A failing test is a flake only after it passes alone several times at the same commit and also fails on `main`. Then add it here with the cause. Known history (none open as far as we know): runner-history tail flaked under `-n 4` (fixed, anchor bytes); `test_media_detail` apps tests flaked from a shared real file (fixed, isolation); `test_pwa` stylesheet versioning failed once order-dependent. (where: `docs/PROCESS.md`; LD 2026-10-06, 2026-10-12, 2026-10-13)
- The suite only grows. A bug fix starts with a test that fails on the old code (prove it fails), and a pin that must change gets a dated line saying why. (where: `CLAUDE.md` rule 4)
- `tests/hub/conftest.py` routes `hub.upstream.session(...)` through `requests`, so fakes at `requests.get/post` see every call. Fakes written before that must match new arr URLs before the generic `arr_get` branch. (where: LD 2026-10-13, 2026-10-21)

## Hub templates, CSS and htmx
- Hub CSS and htmx are content-versioned with `?v=<hash>` through the Jinja global `static_v`. Keep one shared Jinja environment (`hub/shell.py`): a second environment drops the global and ships an empty `css?v=`. (where: LD 2026-10-05, 2026-10-09)
- `StaticFiles` sends no Cache-Control: a style change that does not show needs a hard refresh once. Immutable headers apply only to versioned URLs. (where: LD 2026-09-11)
- htmx history snapshots made Back show stale, undone state (Follow, Request): `historyCacheSize 0` plus `no-store` makes Back reload fresh. Boosted swaps keep the same document, so scripts that run once on load must re-run on swap. (where: LD 2026-10-08; JT 2026-10-22)
- A `display:flex` rule beats the `hidden` attribute: add `[hidden]{display:none!important}`. (where: LD 2026-10-13)
- `test_media_nav` forbids the word "select" before "{" in CSS comments; keep comments free of selector-looking text. (where: LD 2026-10-14)
- Never hand-roll colours or radii: use the recipes in `docs/style-guide.md` and the `:root` tokens. Every row or card is one whole link with plain title text (`row_href`; no anchors inside `.uptitle` or `.pgtitle`). (where: LD 2026-10-06, `CLAUDE.md`)
- Pass `visible_areas`, not `registry.areas`, to any page that lists areas: film, person, discover and plays routes once showed hidden areas. (where: LD 2026-10-06)
- The film page draws its Similar and Recommended shelves only once the Seerr title body (code name `jellyseerr`) is in. `pending_parts` must also list "shelves" while `raw` is missing, or shelves that arrived first render empty and never fill (fixed in PR #37, found by the first Linux CI run). Any "fill later" part must name every input it needs. (where: JY-006, `hub/media_film.py`, 2026-10-23)
- Python `http.server` previews need `<meta charset>` in the page. (where: LD 2026-10-13)

## Media and Awards data
- `media.db` (SQLite) lives on the NAS SSD, never on a network share. It is the hub's only write path: schema bumps are migrations (v3 follow shows, v4 `rating_skip`, v5 `episode_rating`). Back it up (`hub/media_backup.py`; off-box via `deploy/media_offsite.sh`). (where: LD 2026-10-05, 2026-10-16; `deploy/README.md`)
- Episode ratings come from OMDb `?i&Season=` and fill on first view in a background task: `ratings` is None until the first view queues it (open a show twice in a preview). OMDb needs `OMDB_API_KEY` in the NAS `.env`. (where: LD 2026-10-16)
- The Wikipedia award parser knows page shapes per era (tables up to about 2020, `{{Award category}}` after). Audit a sync for editions with `done` and zero winners as well as `skipped`. After a parser change bump `PARSER_V` so editions re-queue. (where: LD 2026-10-16)
- The Awards loop moves to weekly passes once the backlog is zero: after a parser change run `docker exec -i joey-hub python - --pass --cap 200 < scripts/awards_sync.py`. (where: LD 2026-10-16)
- Follow (films): actors come from top-5 credits order on `/movie` (Seerr person credits drop `order`), directors any, new and future only, at most 10 per run on a 6 h loop. A 6 h re-apply flips a manual Sonarr unmonitor back. (where: LD 2026-10-07, 2026-10-12)
- Jellyfin's `jf:<id>` owner keys: B. and Georgina stay `you` and `her`; friends are keyed `jf:<id>` and see only their own rows. Never log a user name, URL or id. (where: JT 2026-10-16, `CLAUDE.md`)
- Snapshots are the only connector-to-hub channel. Feeds are frozen by `docs/connector-contract.md`; a new field needs the contract doc, the schema and the sample snapshots in the same change. (where: LD 2026-09-11; `tests/connectors/test_contract_doc.py`)

## Previews (launch.json)
- The preview tool reads `Documents\Claude\.claude\launch.json`, not the project's. Add an entry there with its own port per worktree. The Edit tool works on it; a Python script rewriting it was refused, and Edit can hit ENOENT under OneDrive (repoint an existing preview script then). (where: mem 2026-10-22; LD 2026-10-16)
- Worktrees have no `data/`: point `SNAPSHOT_DIR` at the worktree's `config/sample_snapshots` (or the main checkout's demo snapshots). `python -m hub.seed_demo` makes demo data; `HUB_DEV=1` re-reads templates. (where: LD 2026-10-22, `CLAUDE.md`)
- uvicorn re-reads templates but not routers: restart the preview after a merge. (where: mem 2026-10-22)
- Preview scripts copied from pre-E1 code need `from hub import upstream as _up; _up.session = lambda name: requests`, or every upstream shows "Couldn't reach". (where: LD 2026-10-16)
- Browser-pane screenshots time out while the pane is hidden: use headless Chrome against the same port. Headless Edge crops below about 492 px wide: use an iframe shim for 375 px checks. (where: LD 2026-10-14, 2026-08-31)
- Eyes-on at 375 px catches what tests miss: sideways scroll, and tap targets under 30 px. (where: LD 2026-10-12, 2026-10-16)
