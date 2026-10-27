# JY-256 Stop the arr set for the deploy gate

Status: building
Size: L
Live risk: deploy (changes `deploy/deploy.sh`, the only path to production, and stops four live media containers for the gate)
Area: `deploy/deploy.sh` (stop set around the gate), `tests/deploy/test_deploy_script.py`, `docs/runbook.md`, `deploy/README.md`, this spec
Needs: JY-240 (pre-gate memory check; shipped 2026-10-24)
Options page: none: no screen

## Problem
About 430 MB of retained heap builds up in the media apps within 2 to 4 hours of boot, so NAS available memory sits around 1,380 MB and deploys skip below 1,460 MB (`SKIPPED-LOW-MEMORY`, first seen 2026-10-26 09:11). Measured on 2026-10-27 (`JoeyTV/review/nas-memory-2026-10-27.md`, option H): stopping sonarr, radarr, prowlarr and flaresolverr frees about 504 MB of pinned memory (anon + shmem: 149 + 140 + 112 + 103), plus 23 MB of swap. `docker pause` frees nothing: a frozen process keeps its memory. So the gate stops them (`docker stop`) and starts them again after.

## Acceptance criteria
1. One variable at the top of `deploy.sh`, with a dated comment: `GATE_STOP_SET`, default `sonarr radarr prowlarr flaresolverr` (spaces or commas). The environment overrides it. An empty value disables the feature: no `docker` call for it, no history tag. qBittorrent, jellyfin, jellyseerr and gluetun are never in the default.
2. Just before the JY-240 memory check, deploy.sh stops each container in the set that is running (`docker inspect` says `Running` true). A container that is not running, or does not exist, is left alone and logged as such. Then `mem_check` measures again, so the existing thresholds (1,720 / 1,460 MB, swap 1,273 MB, unchanged) decide on the freed number. The available memory before the stop is logged too.
3. Each name is written to the list file `deploy/logs/gate-stopped.list` before its `docker stop`, so a run that dies mid-stop still knows it. The file sits in `deploy/logs/` (already ignored by git and Docker), not `/tmp`: the NAS powers off at 22:00, `/tmp` does not survive that, and `docker stop` on an `unless-stopped` container keeps it stopped across a reboot.
4. Restart on every exit path, once per run: gate pass, `GATE-FAIL`, `SKIPPED-LOW-MEMORY`, rollback, an error (`set -e`) and a signal (INT/TERM). `gate_start` starts every listed container; a run-once flag stops a second call doing it again, and the EXIT trap is the net for errors and signals. While the trap runs, INT and TERM are ignored, so a second signal cannot cut the restart short.
   - On a gate pass the containers start right after the suite and before `compose build`, so they are down only for the suite.
   - `gate_fail` and `gate_skip` start them before they write the history line, so that line is written after the restart.
   - A rollback comes after the pass-path start, so nothing is left to start then.
5. Only containers this run stopped (or a crashed run left in the list) are started. A container that would not start stays in the list, is logged loudly (`!! ... start it by hand ... !!`) and adds `start-failed=<names>` to the history line.
6. Recovery: right after taking the lock (this covers the stale-lock path), deploy.sh starts anything still in the list from an earlier run, before the pull. `docker start` on a running container does nothing, so this is safe.
7. Every stop and start is logged with its duration (`gate stop set: stopped sonarr in 3 s`, `gate stop set: started sonarr in 1 s (after the gate)`).
8. Each history line written after the stop carries `stopped=sonarr,radarr,prowlarr,flaresolverr` (only the ones this run stopped; `stopped=none` when none were running), after the existing text and before `end=`. Readers still parse: close-out matches ` PASS ` / `NOTHING-TO-DEPLOY` and `new=`, `scripts/budgets.py` matches `PASS ` and `dur=`. `NOTHING-TO-DEPLOY` lines are unchanged (no gate, no stop).
9. BusyBox `sh` only: no `local`, arrays, `[[ ]]` or brace expansion.
10. A `deploy.sh` change takes effect from the second deploy after it merges: the first deploy after the merge still runs the old copy it read before its own pull (runbook, Deploy). Plan memory for the old behaviour once.

### Test rows
All in `tests/deploy/test_deploy_script.py`, run under a local POSIX sh with a fake `docker` (now answering `inspect`, `stop`, `start`) and a fake meminfo.

| Criterion | Test |
|---|---|
| 1 | `test_gate_stop_set_is_a_dated_variable_at_the_top_and_never_names_the_core_media` (string pin) |
| 1 | `test_empty_gate_stop_set_is_a_no_op` (behaviour) |
| 2, 4, 7 | `test_stop_then_re_measure_then_gate_then_start_before_the_build` (the fake frees 130 MB per stop: 1,380 MB would skip, 1,900 MB runs `-n 2`; suite green, start before `compose build`, PASS line) |
| 4, 8 | `test_restart_on_every_exit_path[gate-fail / skip / error / signal]` (error: an injected `false` after the check; signal: the fake suite sends TERM to deploy.sh) |
| 2, 5 | `test_a_container_that_was_already_stopped_is_left_alone` |
| 3, 6 | `test_a_list_left_by_a_crashed_run_is_restarted_first[plain / stale lock]` |
| 5 | `test_a_container_that_will_not_start_stays_listed_and_is_logged` |
| 8 | history assertions in the rows above (`stopped=...`, `stopped=none`, none when empty) |
| 9 | `test_gate_stop_set_is_busybox_safe` (string pin) plus every behaviour run |
| 2 | `test_memory_check_runs_right_before_the_gate_and_after_the_pull` (existing, unchanged) |

## Data
None. `deploy/history.log` lines gain `stopped=...` (and `start-failed=...` on a failed start). New NAS-only file `deploy/logs/gate-stopped.list`, present only while containers are down or after a failed start.

## Performance budget
- NAS available memory ≥ 1,200 MB during the gate: improves by about 500 MB (measured 504 MB pinned). Expected before the suite: about 1,890 MB with this alone, so `-n 2`.
- Full gate ≤ 10 min (`dur=`): adds the stops and starts. `docker stop` waits up to 10 s per container (then kills it); typical is a few seconds each. Expected under 1 min added.
- Media downtime: sonarr, radarr, prowlarr and flaresolverr are down for the suite (about 3 to 6 min at `-n 2`), plus about 1 min of .NET cold start after. qBittorrent keeps downloading; imports and searches wait.

## Options and the pick
None: no screen. From the NAS memory review (2026-10-27), options A (retire Homepage, JY-209) and H (this item).

B.'s decision, in chat on 2026-10-28: "JY-209: retire Homepage. Deploy gate: stop sonarr, radarr, prowlarr and flaresolverr for the gate and start them again after (option A + H). Go."

## Out of scope
- Retiring Homepage (JY-209, its own item).
- Stopping only when memory is short: the set stops on every gate run, as decided.
- Waiting for the apps' health after the start; Uptime Kuma may flag them for the window.
- Connector sweeps during the window: an arr fetch may record an error and the hub shows the last good data with a stale badge until the next sweep.
- Changing the thresholds, `-n 1` everywhere (option F), or a docs-only gate skip (option G).

## Accept checklist
- `deploy.sh` diff: the stop sits before `mem_check`, the start right after `gate`, the trap starts what is listed, the default set names only the four.
- `python -m pytest -q tests/deploy/` output in the PR.
- Before the first live run: check qBittorrent's completed queue for an import in flight.
- After merge: the first deploy still runs the old copy. From the second deploy on, the log shows `== gate stop set (JY-256) ==`, four `stopped ... in N s` lines, a higher `memory: available` line, then four `started ... (after the gate)` lines; `history.log` ends `... stopped=sonarr,radarr,prowlarr,flaresolverr end=...`; `docker ps` shows the four running; `deploy/logs/gate-stopped.list` is gone.

## Questions for B.
None.

## Shipped notes
