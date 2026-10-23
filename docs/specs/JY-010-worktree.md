# JY-010 `joey.py worktree new / remove / list`

Status: building
Size: M
Live risk: none
Area: `scripts/joey.py`, `scripts/joey_common.py`, `scripts/joey_worktree.py`, `tests/scripts/`, `.gitignore` (one line)
Needs: JY-002 (shipped)
Options page: none: command-line tool, no screen

Ready on B.'s plan approval (2026-10-23, "Go with all recommendations", JOEYV2_PLAN.md §4 row JY-010), with the orchestrator's 2026-10-23 correction: "merged" is proven with `gh`, not `git merge-base --is-ancestor`, because squash merges break ancestry.

## Problem
Every item gets its own worktree and branch, and a merged worktree must be removed at close-out. Today that is typed by hand, and 48 worktrees have piled up. A squash-merged branch never looks merged to `--is-ancestor`, so the old safe-removal check refuses good removals and invites `--force`.

## Acceptance criteria
1. `python scripts/joey.py worktree new JY-### slug` fetches `origin`, then runs `git worktree add <clone>/../wt-JY-### -b feat/JY-###-slug origin/main`. `<clone>` is the main clone (found from `git rev-parse --git-common-dir`), so the command works from the clone or from any worktree.
2. `new` writes `<worktree>/.env` (already git-ignored) with `JOEY_ITEM`, `HUB_PORT` = 9000 + the item number (JY-010 → 9010), `SNAPSHOT_DIR=data/demo-snapshots`, and `MEDIA_DB_PATH`, `MEDIA_BACKUP_DIR`, `META_CACHE_DIR` under `<worktree>/data/dev/` (created). It prints the PowerShell line that starts the dev hub on that port with those values.
3. `new` refuses (exit 1, one-line reason, nothing changed) on: a bad id (`JY-` + 3 digits), a bad slug (`[a-z0-9-]+`), an existing worktree path, a branch that exists locally or on `origin`.
4. `python scripts/joey.py worktree remove JY-###` (or `--path <worktree>` for older non-JY worktrees) removes the worktree and its branch only when one of these proves it merged:
   a. `gh pr list --head <branch> --state all` finds a PR whose state is MERGED and whose head SHA equals the local branch tip (squash merges); or
   b. the tip is an ancestor of `origin/main` (plain merges of older branches). This is a second accepted proof, never the only check for JY branches.
   Then it runs `git worktree remove <path>` (never `--force`) and `git branch -D <branch>`.
5. `remove` refuses (exit 1, reason, nothing changed) when: no proof; the PR is OPEN or CLOSED unmerged; the PR head SHA differs from the local tip (local commits that never reached the PR); the worktree has uncommitted or untracked changes; the path is the main clone.
6. `python scripts/joey.py worktree list` prints one row per worktree: path, branch, PR number and state, and `removable yes/no (why)`. One `gh pr list --state all --limit 300` call, not one per row.
7. Every subcommand takes `--dry-run`: prints each step and the command it would run, changes nothing.
8. Each run prints PASS/FAIL per step and writes a log to `<clone>/.joey/logs/joey_<date>.log` (`/.joey/` added to `.gitignore`). No tokens, URLs with credentials or user names in the log.
9. `scripts/joey.py` is a thin dispatcher: a dict of subcommand name → module, so JY-011 (`close-out`) and JY-012 (`preview`) each add one line. Shared helpers live in `scripts/joey_common.py`: the step/PASS/FAIL runner with `--dry-run` and a write guard, `run()` for subprocesses, `gh_json()`, and `ssh()` to the NAS (`JOEY_NAS`, default `root@nas.local`, as `deploy/push.sh`; key `JOEY_NAS_KEY`, default `~/.ssh/joey_nas`; BatchMode; UTF-8 stdin). Stdlib only.
10. Tests in `tests/scripts/` build a throwaway origin (bare repo) and clone in `tmp_path`, with `gh` replaced by a fake (no network). They cover: new (worktree, branch, `.env` port), each refusal in 3 and 5, removal on proof 4a and on proof 4b, list output, dry-run changing nothing, and that the log never contains a token-like string. Tests skip when `git` is not on PATH. They pass on Windows (laptop) and Linux (CI, gate image).

## Data
None. No database, no snapshots. Reads git and `gh` only.

## Performance budget
None of the hub budgets apply. `worktree list` finishes in under 5 s with 50 worktrees (one `gh` call).

## Options and the pick
None: no screen.

## Out of scope
Removing the 48 old worktrees (JY-021 uses this tool). `close-out` (JY-011). `preview` (JY-012). Editing `CLAUDE.md` / `docs/PROCESS.md` TODO lines: proposed in the PR, applied by B. or with his OK.

## Accept checklist
- CI green on the PR.
- `python scripts/joey.py worktree list` in the shared clone shows every worktree with a removable verdict.
- `python scripts/joey.py worktree remove JY-010 --dry-run` after merge says it would remove `wt-JY-010` and `feat/JY-010-worktree`.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
