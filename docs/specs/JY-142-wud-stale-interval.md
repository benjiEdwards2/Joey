# JY-142 WUD real check interval vs the 180-minute Stale rule

Status: spec
Size: S
Live risk: none
Area: none changed in this PR (spec only). Any follow-up would touch `hub/server.py` (the Updates "checked" words) and `tests/hub/test_server_cleanup.py`.
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
None yet: this PR is evidence and a question. If B. answers 1A, the criteria become: (1) the line says "refreshed 2h ago" in place of "checked 2h ago" and the Stale words keep their rule; (2) `tests/hub/test_server_cleanup.py` expects the new word (dated line here saying so, per the suite rule); (3) the stale boundary test (179 vs 240 minutes) stays as is.

## Data
None.

## Performance budget
None apply.

## Options and the pick
None yet.

## Out of scope
Showing WUD's real next check time ("next check 08:00"). That needs the cron value passed to the hub (a new env on the NAS) and is not asked for.

## Accept checklist
Nothing to try yet.

## Questions for B.
1. What should the Updates line call the age? A) "refreshed 2h ago" (recommended: true to what the number is, one word and one test line to change). B) Keep "checked 2h ago" and accept that it means the poll. C) Pass WUD's cron to the hub and say "WUD checks daily at 08:00 · refreshed 2h ago" (more words, needs a NAS env change, so a separate hands item).
2. Threshold: confirm 180 minutes stays (recommended). The alternative, a day or more, only makes sense if you want the amber for WUD's own schedule, not for the connector.

## Shipped notes
PR: (draft, see the PR). Spec only; no code change, so it closes as "verified, threshold unchanged" unless B. picks 1A or 1C.
