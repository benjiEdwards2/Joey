# JY-210 WP38 soak test + a real runbook

Status: shipped 2026-10-26
Size: M
Live risk: none (docs, and one read-only script run on the laptop against a copy of a file)
Area: `docs/runbook.md` (new), `docs/README.md` and `README.md` (links), `scripts/check_soak.py` (new), `tests/scripts/test_check_soak.py` (new), this spec
Needs: none
Options page: none: no screen

HITLIST row JY-210: "WP38 soak test + a real runbook. Docs name a runbook that does not exist."

## Problem
`docs/README.md` and `README.md` both called `deploy/README.md` "the runbook", and the old plan promised a runbook in `/docs` (WP38 step 4) that was never written. The deploy facts are spread over `deploy/README.md`, `deploy/preview/README.md`, `docs/tv-release.md`, `docs/public-edge.md`, `docs/PROCESS.md` and the tech notes, and today's failures (a classifier block on an after-hours deploy, flaky tests, `tv.css` conflicts, a backup push stopped by a 872 MB file) are in nobody's file. The WP38 soak (`connectors/tools/check_soak.py`, from the archived MASTER_PLAN) was never built.

## What WP38 asked for (archived `MASTER_PLAN.md`, WP38, 2026-08-24)
1. `check_soak.py`: read `_runner_history.jsonl` plus every snapshot; at least 22 sweeps in 24 h (2 missed beats allowed); for each connector at least 22 `ok` results and not `error` for the whole window; `money` exempt from the ok count and only never `error`. Exit 0 prints per-connector beat counts and the money exemption line.
2. A stale-badge drill (invalid credential, 3 sweeps, last good data + stale badge, restore).
3. A Notion check (`git grep -il notion connectors/` returns nothing).
4. `docs/connectors-runbook.md` with credential rotation, the notifier, the drills and a restore pointer.
5. B.'s v1 sign-off.
Steps 2, 3 and 5 are live drills or B.'s decision, not scripts. Since then the connector fleet changed (parked connectors, a 2-minute partial loop tagged `only`, hourly loop tagged `except`), so the count rules below are adapted.

## Acceptance criteria
1. `docs/runbook.md` covers: deploy and the memory gate (JY-240) with the `history.log` outcome words; rollback (automatic and by hand); the preview slot (`joey.py preview`); close-out (`joey.py close-out`); the TV app release (`tv.yml` on merge to `main`); the NAS power schedule and the deploy window; the soak check; common failures and fixes from 2026-10-24 to 26 (classifier blocks on after-hours deploys and on rule-file edits, flaky tests, `tv.css` keep-both conflicts, the backup large-file block, DNS loss on the pull). It points to the long docs and repeats none of them.
2. `docs/README.md` and `README.md` link to it, and no longer call `deploy/README.md` "the runbook".
3. `scripts/check_soak.py HISTORY` is read only (stdlib, no writes, no network), counts over the last 24 h: at least 22 hourly-loop sweeps (lines without an `only` tag) and, per connector, at least 22 `ok` results and not `error` in every result; an exempt id (`money`) is held only to "never reports error". `--expect` adds ids that must appear; `--snapshots DIR` (a copy) also checks each snapshot's age and status. Exit 0 PASS, 1 FAIL, 2 could not run. Malformed lines are skipped and counted.
4. Tests: clean day passes; too few ok beats, an all-error connector, the exempt rule, too few hourly sweeps (the 2-minute loop does not count), an expected id that never ran, the window edge, malformed and empty files, snapshot age and error, no write or network calls in the source, the real line shape `run_all` writes, and the runbook's links, anchors and repo paths resolve (skipped in the gate image, where `docs/` is not copied).

## Data
None. `scripts/check_soak.py` reads a copy of `_runner_history.jsonl`.

## Performance budget
None apply: no hub or NAS code changes.

## Options and the pick
None: no screen.

## Out of scope
- Running the soak against the live NAS: no run was made (one read of `_runner_history.jsonl` is all it needs; see the runbook). The 24 h pass itself is a B.-timed window, not part of this PR.
- The stale-badge drill, the Notion check and B.'s v1 sign-off (WP38 steps 2, 3, 5): kept as procedures in the runbook, not automated.
- `connectors-runbook.md` (credential rotation by env-var name, the notifier): not written. The runbook does not invent steps; a later item can add them from the real setup notes.
- `CLAUDE.md` still says "`deploy/README.md` is the runbook" and "TV release runbook" in its Where-things-are list, and `docs/PLAN.md` line 57 says "Deploy runbook: `deploy/README.md`". Builders do not edit those files: proposed wording for the orchestrator is in the PR.
- The NAS power schedule in the runbook reflects the repo's own notes (ADM schedule off 22:00 to 07:00, F7 to make it 24/7 on the invite day). Whether F7 has been applied was not checked on the NAS.

## Accept checklist
- Read `docs/runbook.md`: every command is one you would run, with the output you would expect.
- `python -m pytest -q tests/scripts/test_check_soak.py` passes.
- `python scripts/check_soak.py <copy of the history>` prints one line per connector and a PASS or FAIL summary.

## Questions for B.
1. Should the 24 h soak itself be run now (one read of the history file, then offline), or after the next few deploys settle? Recommendation: after, so the window holds no deploy restarts.
2. Is the NAS still on the ADM power schedule, or has F7 (24/7) been applied? The runbook says "check, do not assume". Recommendation: tell me, and the section gets one definite sentence.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #187, squash-merged as `8e6e54a` (8e6e54a397512cfcc0348b4d386170ee3fcfaa03).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
