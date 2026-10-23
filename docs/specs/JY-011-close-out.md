# JY-011 `joey.py close-out JY-###` (merge, deploy, verify, shipped notes)

Status: building
Size: L
Live risk: deploy
Area: `scripts/joey_closeout.py`, one line in `scripts/joey.py`, `tests/scripts/`
Needs: JY-010 (shipped: `scripts/joey.py`, `scripts/joey_common.py`, `scripts/joey_worktree.py`)
Options page: none: command-line tool, no screen

Ready on B.'s plan approval (2026-10-23, "Go with all recommendations"; Q3 A: the merge rules are enforced by this script). Orchestrator corrections, 2026-10-23: merge with `--squash`; the container-health check waits and retries (on 2026-10-23 `verify.2` failed only because `joey-media` was still "starting"; it passed when re-run 18 s later).

## Problem
Every item ends with the same close-out: merge, deploy, check the NAS, write the shipped notes, mark the HITLIST row, remove the worktree. Joey TV's `JoeyTV\scripts\pr_close_out.py` already does merge → deploy → verify reliably. The repo needs the general version, and it must refuse to merge without green CI, a review and B.'s accept, because the free GitHub plan has no branch protection.

## Acceptance criteria
1. `python scripts/joey.py close-out JY-### [--accepted-in-chat "<B.'s words, dated>"] [--deploy auto|yes|no] [--after-fail] [--timeout MIN] [--dry-run]` finds the item's open PR from its branch `feat/JY-###-*`.
2. Gates. It refuses (exit 1, one line per failed gate, nothing changed) unless all hold:
   a. the PR is open, not a draft, and mergeable;
   b. the `ci` check on the PR head SHA concluded `success`;
   c. a PR comment whose first line starts with `Review:` and says `PASS` exists, posted after the newest commit on the PR head was pushed (a later commit needs a fresh review);
   d. B.'s accept: the `accepted` label, or a PR comment that is exactly `accepted` (case-insensitive), or `--accepted-in-chat` with B.'s quoted words and date (recorded verbatim in the shipped notes and as a PR comment before the merge).
3. Merge: one `gh pr merge N --squash` call, no retries. Read-back: state MERGED, the merge commit is on `origin/main` after `git fetch`.
4. Deploy decision: `--deploy auto` (default) deploys unless every file the PR changed is Markdown or under `.github/`; `yes` / `no` force it. A skipped deploy is logged as SKIP with the reason.
5. Deploy (ported from `pr_close_out.py` `deploy.1`–`deploy.3`): refuse outside 07:00–21:30 Melbourne time and in the 15 minutes before 00:00 UTC (tech notes); refuse when NAS available memory is under 1,200 MB; wait for a running deploy (`/tmp/joey-deploy.lock`); refuse when the last `history.log` line is not PASS / NOTHING-TO-DEPLOY unless `--after-fail` (the one retry); start `deploy.sh` (it detaches itself); wait for a new history line that says PASS and `new=<merge sha>`.
6. Verify (ported from `verify.1`–`verify.4`): NAS tree on the merge SHA; joey-hub, joey-media, joey-swag running and healthy; `COMPOSE_PROFILES=edge,media`; in-container smoke. The container check polls every 10 s for up to 120 s while any container is `starting`, and fails at once on `unhealthy`, `exited` or absent. Also: `/healthz` answers inside joey-hub, and the hub reports the merge SHA if it exposes one (find out; if it does not, log INFO, not FAIL).
7. Close-out docs: on a branch `chore/JY-###-shipped` from `origin/main`, fill the spec's `Status:` (`shipped <date>`) and `## Shipped notes` (PR, merge SHA, deploy history line or the skip reason, the accept source, follow-ups from `--note`), set the HITLIST row to `[x] shipped` with `PR #N` in the Why cell and the spec link in the Spec cell; push; open a PR; wait for its `ci` check; squash-merge it. If the HITLIST row or spec is not found, stop with a clear message (no guessing).
8. Labels: remove `building`, `review`, `accept`, `accepted`; add `shipped`.
9. Worktree: `joey_worktree` remove for the item (the gh-proof path from JY-010). A refusal there is a FAIL row, not a crash.
10. Every step prints PASS / FAIL / SKIP / DRY and goes to the JY-010 log. A FAIL stops the steps that depend on it (no deploy after a failed merge; no docs after a failed verify, but the summary says what is left). Secrets never reach the log (NAS host from `JOEY_NAS`, only SHAs, states and history lines are printed).
11. `--dry-run` on a doc-only PR prints every step as PASS (read-only gate checks) or DRY (state changes), with the command it would run.
12. Tests in `tests/scripts/` with fake `gh` and fake `ssh` (no network): every refusal path in 2 and 5, the deploy decision in 4, the health-check wait (starting → healthy passes; unhealthy fails at once; starting past the limit fails), the HITLIST and spec edits in 7 on a fixture copy, and the dry run in 11.

## Data
Edits `HITLIST.md` and the item's spec through a PR. Reads `deploy/history.log`, container states and `deploy/.env`'s `COMPOSE_PROFILES` line on the NAS (only that line is printed).

## Performance budget
None of the hub budgets apply. Full gate stays under 10 min (measured by `deploy.sh`, not this script).

## Options and the pick
None: no screen.

## Out of scope
Changing `deploy.sh`. The preview slot (JY-012). Running `scripts/budgets.py` (JY-013) as a gate: a later item.

## Accept checklist
- CI green; two separate reviews and the Opus verifier posted on the PR.
- The dry run against a real doc-only PR, output in the PR.
- The first real use closes out JY-011's own HITLIST row or the next item.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
