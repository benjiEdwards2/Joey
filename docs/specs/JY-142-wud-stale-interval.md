# JY-142 WUD real check interval vs the 180-minute Stale rule

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/server.py` (the Updates "refreshed" word), `hub/templates/server.html` (comment), `tests/hub/test_server_cleanup.py`, `docs/hub-changelog.md`.
Needs: none
Options page: none: no screen change proposed yet

Live risk is `none`: the live check was read-only (`docker inspect` filtered to cron/schedule/interval keys, a log read, one GET of WUD's container list from `joey-connectors`, run in memory; nothing written on the NAS).

## Problem
HITLIST row: "WUD real check interval vs 180-min Stale rule. Verify live, then adjust." The Server page's Updates line reads "17 monitored · 2 updates · checked 2h ago" and turns amber "Stale" past the Updates tile's `stale_after_minutes` (`config/areas.yaml`, 180; `hub/server.py` `build_server`, WP-T3 S9).

## What was found (live, 2026-10-24)
- WUD's own schedule is `WUD_WATCHER_LOCAL_CRON=0 8 * * *`: one registry check a day, 08:00 (container TZ Australia/Sydney, same offset as Melbourne), plus one on each WUD start (the logs show "Cron started / finished" at every restart; 19 containers watched, 0 errors).
- The Stale rule does not measure that. The age on the snapshot is the age of the hub's own poll: the `wud` connector calls WUD's `GET /api/containers` on the hourly sweep (`_runner_history.jsonl` shows hourly runs; `wud.json` was written 20:36 the same day). 180 minutes is three missed hourly polls.
- WUD's container objects carry no last-checked time (keys read: `coolingDownUntil, delay, id, image, isCoolingDown, isSnoozed, labels, result, snoozedUntil, stack, status, updateAvailable, updateKind, watcher, ...`), so the real check time is not available from the API.

## Verdict
- The 180-minute threshold is right for what it measures. It does not fire falsely: a normal sweep is at most about 60 minutes old. It fires when the connector cannot reach WUD for three sweeps, which is the case worth warning about. Multiplying WUD's real interval (24 h) into it would hide a broken connector for a day, so **no threshold change**.
- The word is wrong. "checked 2h ago" says WUD checked the registries 2 hours ago. WUD checked at 08:00 (or at its last start); the 2h is when Joey last asked WUD. Updates can show "checked 5m ago" for data up to a day old.

## Acceptance criteria
1. The Updates line says "refreshed 2h ago" in place of "checked 2h ago"; the amber words read "Stale · refreshed 5h ago".
2. The Stale rule is unchanged: the Updates tile's `stale_after_minutes` (180).
3. `tests/hub/test_server_cleanup.py` expects the new word (dated line below, per the suite rule); the stale boundary test (179 vs 240 minutes) keeps its numbers.
4. Red test first: the renamed test fails on the old code.

## Data
None.

## Performance budget
None apply.

## Options and the pick
Options page: none. B. answered both questions in chat on 2026-10-24: "JY-142: 1A, keep 180".
- **1A:** "refreshed 2h ago" (true to what the number is).
- **2:** keep the 180-minute Stale rule.

## Out of scope
Showing WUD's real next check time ("next check 08:00"). That needs the cron value passed to the hub (a new env on the NAS) and is not asked for.

## Accept checklist
Open Server: the Updates line reads "... · refreshed Nm ago" (no "checked"); with a snapshot older than 180 minutes it reads amber "Stale · refreshed ...".

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #132, squash-merged as `6a0ca25` (6a0ca258a3d78c142ae10175d22e603b069d7a72).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
