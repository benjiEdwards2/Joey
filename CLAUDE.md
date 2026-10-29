# Joey: rules for every agent

Read this first. Then `HITLIST.md` (what to do), `docs/PROCESS.md` (how), `docs/PLAN.md` (why), and the item's spec in `docs/specs/`.
These do not exist yet: `docs/PROCESS.md` and `docs/specs/` arrive in JY-002, `docs/PLAN.md` in JY-003, `HITLIST.md` in JY-004, `docs/reference/tech-notes.md` in JY-005. Until they merge, the item's brief is your spec.

## What this is
Joey is a private dashboard for two people, self-hosted on a NAS behind Cloudflare Tunnel + Access. It shows Media (Jellyfin and the arr stack), Calendar, Server and Weather in one place, and it replaces several separate apps. This repo is private and stays private. Owner: B., who approves every spec, picks every option and accepts every build. Joey TV (`tv/`) is its Android TV shell.

## Rules
1. No code without a spec the owner has marked `ready` (`docs/specs/`).
2. Anything with a screen gets 2 to 4 built-out options on an HTML page first. B. picks; the pick goes into the spec before building.
3. Performance budgets (below) are acceptance criteria. Measure them and put the numbers in the PR. Over budget is not done.
4. Tests ship with the code: unit tests for logic, integration tests on a fresh database (SQLite in a temp dir), and a smoke test for every screen or route. The suite only grows: never delete, weaken or skip a test without a dated line in the spec saying why. A bug fix starts with a failing regression test. CI must be green.
5. One item, one branch (`feat/JY-###-slug`), one PR, one agent. Stay inside the item's area. If you must touch something outside it, stop and say so in the PR.
6. Builders do not edit `HITLIST.md`, `docs/PLAN.md`, `docs/PROCESS.md`, this file or the design tokens (the `:root` block in `hub/static/control-surface.css`). Propose the change in the PR; the orchestrator applies it. The orchestrator edits this file and `docs/PROCESS.md` only with B.'s OK.
7. The live system is read only during development: Jellyfin, Radarr/Sonarr, Seerr, qBittorrent and the NAS files. Nothing writes to them unless the spec says so, behind a flag, against a test target.
8. Secrets stay in `.env` files (git-ignored); `deploy/.env.example` and the other `*.env.example` files list every key. Never put a secret in a commit, a log, a test or a PR.
9. Screens use the recipes in `docs/style-guide.md` and the tokens in `hub/static/control-surface.css`. No hand-rolled colours, radii or spacing.
10. Write plainly: short sentences, no filler, no claims you did not check. A PR that says "tests pass" shows the output.
11. Claude does all git and GitHub work: commits, pushes, PRs, merges, deploys. Never skip hooks. Merge style: squash, one commit per item. Merge only on green CI + a review by a different agent + B.'s accept.
    Exception (B. 2026-10-29, "Yes, allow it"): docs-only changes (`*.md`, `docs/`, `HITLIST.md`) from the sweep and close-out scripts go straight to `main` as one batched commit per day, no PR, no CI. Code never does.
    Verify after every merge (`gh pr view`, `git fetch`) and after every deploy (`deploy/history.log` PASS, smoke ok, in-container check).

## Joey standing rules
- No area names in hub code. Areas are config (`config/areas.yaml`), not code.
- State is always a word beside any colour (for example "Not synced yet"). Links never use browser-default colours.
- Never log or echo URLs, keys, tokens, user names or passwords.
- A NAS `.env` append needs the trailing-newline guard (use `nas_scripts/append_env.sh`; that folder lives in the project folder, not this repo).
- Deploy only through `deploy/deploy.sh`, and only between 07:00 and 21:30 Melbourne time. The NAS is off 22:00-07:00. It aborts on any red test and rolls back a failed deploy.
- NAS memory ceiling: available RAM stays at or above 1,200 MB during any deploy or preview.
- Machine rule: builders edit files and run git only, until the orchestrator sends "machine free: tests allowed". One heavy run (full suite, timing, deploy gate) at a time.
- Before every commit: `git status` + `git fetch`; stage only your item's files (parallel sessions share the repo).
- One worktree per item: `git worktree add ../wt-JY-### -b feat/JY-###-slug origin/main`. Never merge or push `main` from the shared clone: it may sit on another session's branch.
- Anything only B. can do (router, Cloudflare, secrets, the TV) goes in one hands bundle per state window, with exact click-paths. Tests that need one state change run together in that window.
- Every question to B. about how something looks (a background, a title page, a poster, a layout, a colour) comes with the picture: a published Artifact page or screenshots of each option, using real titles where possible, linked right in the ask. For a simple change (one change, one or two shots) the screenshot files go straight into chat, no artifact; the orchestrator never opens them. B. 2026-10-29: "Happy for you to approve that once you show me an image of what you have done. No need for an artifact if its simple." B. 2026-10-28: "Update claude.md to also provide tehe artifact or where I can see teh background or title pages if it is asking me to complete this."
- Token rules (B. 2026-10-29: "Apply all six token recommendations"; measured in `review-token-usage-2026-10-29.md` in the project folder):
  1. The orchestrator hands over (`/handover`) and restarts fresh when its context passes ~200k tokens. Never run it past 300k.
  2. No images in the orchestrator. Reviewers and verifiers look at screenshots and contact sheets; the orchestrator gets a verdict and a link.
  3. Short outputs only in the orchestrator: `| tail -3` on test runs and logs; big files are read by the agent that needs them.
  4. No builder runs past ~150 turns. Split L items into S/M phases before briefing.
  5. One script per item for review-post + merge + deploy; no "still waiting" turns while agents run.
  6. GitHub traffic (push, pull, PRs, CI) is free in tokens; reading diffs and logs is not, so a reviewer reads them, not the orchestrator.
- Builder and review tier follow the item's size:

| Size | Builder | Review |
|---|---|---|
| S (chore or small) | Sonnet | One Sonnet reviewer |
| M | Opus, or Sonnet when the spec is tight | One Sonnet reviewer |
| L, or live system / secrets / deploy | Opus | Two Sonnet reviewers, then one Opus verifier after the fixes |

## Stack
Python 3.12. The hub is FastAPI + Jinja + HTMX (`hub/`, port 8000). Connectors (`connectors/`) write JSON snapshots on a schedule and the hub reads them. Writes go to one SQLite file, `media.db`. Everything runs as Docker Compose on the NAS (`deploy/`); the hub is reached only through Cloudflare Tunnel + Access. Tests: pytest (+ pytest-xdist, `requirements-dev.txt`). Joey TV is a Kotlin WebView app built only in GitHub Actions (`tv/README.md`).

## Commands
Run from the repo root.
- Install (once per clone): `pip install --user -r hub/requirements.txt -r requirements-dev.txt`, then `git config core.hooksPath scripts/hooks` (the money pre-commit guard).
- Dev hub with demo data: `python -m hub.seed_demo`, then PowerShell: `$env:SNAPSHOT_DIR="data/demo-snapshots"; python -m uvicorn hub.main:app --port 8800`; bash: `SNAPSHOT_DIR=data/demo-snapshots python -m uvicorn hub.main:app --port 8800`. `HUB_DEV=1` re-reads templates on every render.
- Full test run, serial: `python -m pytest -q tests/`. Faster: `python -m pytest -q -n 4 tests/`. No credentials and no network needed. Builders: run these only after "machine free: tests allowed".
- Deploy (Claude runs it): `ssh root@<nas> /volume1/Docker/joey/life-dashboard/deploy/deploy.sh`, or `JOEY_NAS=root@<nas> deploy/push.sh`. History: `tail deploy/history.log` on the NAS.
- TODO(JY-006): the CI command and what it covers.
- TODO(JY-011): `scripts/joey.py close-out JY-###` (merge, deploy, shipped notes).
- TODO(JY-013): `scripts/budgets.py` (measure the budgets).

## Where things are
- `hub/` : FastAPI + Jinja/HTMX app; `hub/README.md` is the module map; `hub/static/control-surface.css` holds the tokens.
- `connectors/` : hourly and 2-minute feeds and the frozen envelope schema.
- `deploy/` : compose, `.env.example`, `deploy.sh`, `test.Dockerfile`; `deploy/README.md` is the runbook.
- `config/` : `areas.yaml` (the area registry) and `sample_snapshots/`.
- `tests/` : the cumulative suite (`tests/README.md`): hub, connectors, deploy, tv, money, stackctl.
- `docs/` : setup, connector contract, style guide, hub changelog, public edge, TV release runbook (`docs/README.md` indexes it).
- `scripts/` : dev tools, the awards sync CLI, the money pre-commit guard and hook.
- `stackctl/` : NAS helper behind Server "Restart + update media stack".
- `tv/` : the Joey TV Android shell.
- `.github/workflows/` : today only `tv.yml` (Joey TV builds).

## Definition of done
Spec ready, option picked, code and tests, budgets met with numbers in the PR, reviewed by a different agent, accepted by B. on a preview, merged, deployed, HITLIST row done and docs updated (spec shipped notes, and `hub/README.md`, `docs/` or `deploy/README.md` if the change touches them).

## Performance budgets
Each is measured inside joey-hub on the NAS. Acceptance criteria, not wishes.

| What | Budget |
|---|---|
| Hub page render, warm | p95 <= 50 ms |
| Media list / item page, warm | p95 <= 150 ms |
| Discover page | <= 3 s, never blocks |
| joey-hub memory | <= 200 MiB (cap 384) |
| NAS available memory during any deploy or preview | >= 1,200 MB |
| Full gate (`deploy.sh`) | <= 10 min |
