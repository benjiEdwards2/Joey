# JY-306 Preview on fixed ports (3001 / 3002 / 3003)

Status: ready (B. 2026-11-03: "Is it something you could complete the hitlist for spinning up two ports with option a and b")
Size: M
Live risk: none (PC only, no NAS write, no live key; a LAN-open port is Question 1)
Area: `scripts/joey_preview_local.py` (new), one line in `scripts/joey.py`, `deploy/preview/README.md` (one section), `tests/scripts/`
Needs: none (JY-012 preview slot, shipped, is left untouched)
Options page: no

## Problem
B., 2026-11-02: "boot or spin up a local port that allows me to preview JOEY running these changes in a separate..." On 2026-11-03 he is unsure between Overview options A and B and wants both up on two ports, "a port variation", to compare them live. Today there is one slot and it takes minutes to build. Target: 3001 and 3002 each serve a web build of a chosen branch, 3003 serves the TV build, so a build is checked before every live deploy.

## What the code does today
- `python scripts/joey.py preview up <branch | PR>` / `down` / `status` (`scripts/joey_preview.py`, JY-012) runs ONE slot, compose project `joey-preview`, on the NAS. It runs from the PC over ssh.
- Selection: a branch name or PR number is resolved to an exact commit, checked out on the NAS (alpine/git, read-only deploy key), built as image `life-hub-preview`, and started. A running slot is replaced.
- Port: none published. The slot joins the main stack network and is reached only through the tunnel at the preview hostname, behind Access. It is not on the LAN by port.
- Data: the newest daily `media.db` backup restored as a copy; live snapshots and the poster cache mounted `:ro`; env built from an allow-list (`ENV_IN`), so every write-capable key is out and every background loop is pinned off.
- Gates: refuses outside 07:00-21:30 Melbourne, while a deploy holds the lock, or under 1,400 MB NAS available memory; takes the deploy lock for the build; tears down below 1,200 MB; `mem_limit` 256m.
- TV: there is no TV preview mode. The TV shell (`tv/`) is a WebView over the guest media front; the 10-foot styling switches on with the `JoeyTV/` user agent or the `tv=1` cookie (`?tv=1` sets it, `hub/media_front.py`). A TV build means the hub with `JOEY_FRONT=media`.
- Locally: `python -m hub.seed_demo`, then `SNAPSHOT_DIR=data/demo-snapshots python -m uvicorn hub.main:app --port 8800` (`hub/README.md`). One process, demo data, no branch handling. `HUB_DEV=1` re-reads templates. Caches default under the data dir; `META_CACHE_DIR`, `IMG_CACHE_DIR`, `MEDIA_DB_PATH`, `SNAPSHOT_DIR` are env-settable.

## Where it runs
On the PC, not the NAS. The existing tooling is NAS-side, but it is one slot, build-heavy, locked to the window and gated by the 1,200 MB floor, so three more NAS slots do not fit. The new tooling runs the hub as plain uvicorn processes on the PC from git worktrees, with demo or read-only data. Nothing runs on the NAS.

## Acceptance criteria
1. `python scripts/joey.py local up <slot> <branch>` with slot `1`, `2` or `3` starts a hub for that branch on port 3000+slot and prints the URL, branch, commit and PID. Slot 3 starts the TV build (media front, `tv=1` landing). Re-running a slot replaces it.
2. The branch is checked out in its own worktree, `../wt-preview-<slot>` (reusing the JY-010 worktree helper if it fits). The shared clone is never switched. A branch already checked out elsewhere is refused with a clear line.
3. `local down <slot>` (or `all`) stops the process and removes that slot's state. `local status` lists each slot: port, branch, commit, PID, uptime, URL, and "stopped" for the rest.
4. Two slots run side by side without clashing: each has its own port, its own state dir `data/preview-slots/<slot>/` holding the sqlite file, meta cache and image cache (`MEDIA_DB_PATH`, `META_CACHE_DIR`, `IMG_CACHE_DIR`), and its own worktree. A test starts two slots and shows no path or port is shared.
5. Data is mock or read-only: default is the `seed_demo` snapshots copied per slot; `--data nas` may copy the newest `media.db` backup read-only, never mounts or writes a live path. No `.env` is read or copied. Write-capable env keys are unset and every background loop is off (the same `FORCED_OFF` set as `joey_preview.py`, imported not copied). A request or restart fails visibly.
6. A port already in use by something that is not our slot makes `up` fail with the owner PID, and it never kills a foreign process. `up` polls `/healthz` (no bare sleep) and fails after 30 s with the last 20 log lines.
7. Slot processes are detached and survive the terminal; logs go to `data/preview-slots/<slot>/hub.log`. Nothing under `data/preview-slots/` or the worktrees is ever committed (ignore rule checked).
8. `up` refuses a dirty worktree check-out of the wrong branch and prints no secret, hostname, IP or user name; the printed LAN URL is built at run time from the PC's own address and never written to a file in the repo.
9. A test covers up, status, replace, down and the port-clash path with a fake process runner (no real server in unit tests); one live smoke starts slots 1 and 2 on two branches and shows different commits at `/healthz` on 3001 and 3002.
10. `deploy/preview/README.md` gains a section "Local fixed-port previews" with the commands and the NAS-slot vs PC-slot difference.

## Data
None added. Each slot owns a copy of its sqlite file; the demo seed is the default; the live `media.db` and live snapshots are never opened for write.

## Performance budget
NAS available memory untouched (nothing runs there; the 1,200 MB floor is not in play). On the PC: one slot up in <= 15 s from a warm worktree, health green; each slot <= 250 MB RSS. Measured and put in the PR.

## Questions for B.
1. LAN reach, for phone and TV. A. Bind 0.0.0.0 so the phone and TV can open `http://<pc-address>:3001-3003` (recommended; needs one Windows Firewall inbound allow for 3001-3003, Private network only, which may need IT if it is a managed profile; those hubs show demo data only). B. Bind 127.0.0.1 only: PC browser only, no firewall change, no phone or TV. C. Start on 127.0.0.1 and make `--lan` opt-in per run.
2. Data. A. Demo seed only (recommended; zero risk). B. Demo by default with `--data nas` for a copy of the latest backup, which needs the backup file reachable from the PC.
3. TV build on 3003. A. Media front in a normal browser with `tv=1` (recommended; enough to judge layout, D-pad not tested). B. Also a build of the TV shell APK later, a separate item.
4. Slots 1 and 2 default to the same branch pair for the Overview A/B compare: A. `local up 1 <branch-A>` and `local up 2 <branch-B>` by hand (recommended). B. A one-shot `local compare <A> <B>`.
