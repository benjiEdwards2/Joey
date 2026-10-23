# JY-013 `scripts/budgets.py` (measure the performance budgets)

Status: shipped 2026-10-23
Size: M
Live risk: none (read-only GETs inside joey-hub and read-only NAS commands; nothing is written)
Area: `scripts/budgets.py`, `tests/scripts/`
Needs: JY-001 (shipped)
Options page: none: command-line tool, no screen

Ready on B.'s plan approval (2026-10-23, "Go with all recommendations"; Q6 A: the budgets are acceptance criteria).

## Problem
`CLAUDE.md` lists performance budgets as acceptance criteria, but nothing measures them. Speed was measured ad hoc (EVALUATION 2026-10-12). A budget nobody measures is a wish.

## Acceptance criteria
1. `python scripts/budgets.py` runs on the laptop and measures every row of the `CLAUDE.md` budget table on the NAS over one ssh login per check (`JOEY_NAS`, default `root@nas.local`, as `deploy/push.sh`; key `JOEY_NAS_KEY`, default `~/.ssh/joey_nas`; `BatchMode=yes`; stdin encoded UTF-8). Stdlib only.
2. Page timings run inside joey-hub: a Python payload piped to `docker exec -i joey-hub python -` (the proven route; the hub port is not published). Each URL is fetched once untimed (warm-up), then timed N times (default 20, `-n`). Report p95 (nearest rank) and max:
   - hub pages: `/` and the area overview pages found from `config/areas.yaml` (read on the laptop and passed to the payload as arguments; no area names hard-coded) → p95 ≤ 50 ms;
   - media list (`/media/movies`, `/media/tv`) and up to 4 item pages (`/media/item/<id>` links collected from the lists) → p95 ≤ 150 ms;
   - Discover (find the route in `hub/`) → one cold and one warm fetch, each ≤ 3 s.
3. joey-hub memory from `docker stats --no-stream joey-hub` → ≤ 200 MiB.
4. NAS available memory from `free -m`, read before and after the page timings; the lower one is reported → ≥ 1,200 MB.
5. Full gate: the duration of the newest PASS line in `/volume1/Docker/joey/life-dashboard/deploy/history.log`, if `deploy.sh` records one (read `deploy/deploy.sh` to see the line format) → ≤ 10 min. If the line has no duration, the row is INFO "not recorded", not FAIL.
6. The report is at most 20 lines: one per budget row (name, measured value, budget, PASS / FAIL / INFO / SKIP), then one summary line. `--json` prints the same as JSON instead.
7. Exit 0 when every measured row is within budget; 1 when any row is over; 2 when a measurement could not run (ssh refused, container missing). The reason is printed.
8. Read-only: HTTP GETs only; no NAS command writes a file; no `docker` command other than `exec` (the GET payload), `stats` and `inspect`. Nothing printed contains a token, an e-mail address or a user name.
9. `--local http://127.0.0.1:PORT` runs the page-timing payload directly against a local hub (no ssh); the NAS-only rows show SKIP. This is how the tests and the dev hub use it.
10. Tests in `tests/scripts/test_budgets.py` (no network): the p95 maths, the verdict and the exit code for each case in 7, the 20-line limit, parsing of `docker stats` output (`123.4MiB / 384MiB`), `free -m` output and a history line, and the payload run against a loopback fake HTTP server bound to port 0 on 127.0.0.1. They pass on Windows and Linux.
11. One live run against production, inside the deploy window, by the orchestrator. The report goes in the PR.

## Data
None written. Reads: hub pages over HTTP inside joey-hub, `docker stats`, `free -m`, `deploy/history.log`.

## Performance budget
This item measures the table in `CLAUDE.md`. The run itself takes under 2 minutes and adds no load beyond about 100 GETs.

## Options and the pick
None: no screen.

## Out of scope
Failing deploys on budgets (`deploy.sh` stays as it is). Preview-slot measurement (JY-012 may call this script later). Fixing anything that comes out over budget: that becomes a new HITLIST row.

## Accept checklist
- CI green.
- The live report in the PR shows every budget row with a number and a verdict.

## Questions for B.
None.

## Shipped notes
- PR #48, squash commit `4b1499b` (2026-10-23). Builder Opus; review separate Sonnet agent: PASS, 0 must-fix; one fix round (bare NAS host scrubbed from ssh errors; missing `history.log` is ERROR; exit-0 tests use generous budgets). 20 tests.
- Accept: B.'s standing instruction relayed by the JoeyV2 coordinator, confirmed by B. in the orchestrator session on 2026-10-23 (see JY-010's notes for his words).
- Deployed with JY-010 at `387511d` (history PASS, dur 899 s).
- Live run on production (afternoon of the ship date), n=20: hub pages p95 52 ms (`/a/server`; 56 ms on a re-run) FAIL; media list/item p95 26 ms PASS; Discover 1.80 s cold / 0.03 s warm PASS; joey-hub 111.8 MiB PASS; NAS available 1,632 MB PASS; full gate 15.3 min FAIL. Exit 1.
- Follow-ups: JY-226 (`/a/server` over 50 ms), JY-227 (full gate over 10 min). `CLAUDE.md` TODO(JY-013) line (B. edits): "`python scripts/budgets.py` measures the budgets on the NAS (`--local URL` for a dev hub; exit 0 ok / 1 over / 2 not measured)."
