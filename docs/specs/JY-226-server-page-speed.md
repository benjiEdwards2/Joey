# JY-226 Server page within its render budget

Status: shipped 2026-10-24
Size: M
Live risk: none
Area: `hub/server_history.py`, `hub/server.py` (`sweep_stats`, `history_band` callers), `hub/server_space.py` (reads `recent()`), `tests/hub/`
Needs: JY-031 (shipped: the forecast cache)
Options page: none: no visible change

Source: `scripts/budgets.py` (JY-013): `/a/server` warm p95 52, 56, 53, 52 ms on the NAS against the 50 ms hub-page budget.

## Problem
Every `/a/server` render re-reads and JSON-decodes the full 7-day `server_system_samples` table and re-derives values that change at most every 2 minutes, so the page's cost grows with the stored rows. Research, 2026-10-24 (laptop, production-shaped data: 5,040 rows, 3 volumes each; a warm render median 80.7 ms, p95 125 ms):

| Hot spot | ms | share |
|---|---|---|
| `server_history.recent()` (`hub/server_history.py:103-125`): SQL read 16 ms, `json.loads` per row 18 ms, dicts + `parse_utc` ~10 ms | 44 | 55 % |
| `history_band()` (`hub/server.py:576-603`): the 7-day `week` scan calls `_vol_pct` 5,760 times | 12.6 | 16 % |
| `sweep_stats()` (`hub/server.py:180`): 1,000 runner lines × 14 connectors per request | 6.5 | 8 % |
| rest of `build_server` | ~7 | 9 % |
| Jinja render, gzip, framework | ~10 | 12 % |

Measured fixes (monkeypatched, median / p95): A, decoded rows kept in memory, re-read only when the table changes: 80 → 37 / 40 ms. A + C, also memoise `sweep_stats` on the cached runner history: → 31 ms. A + B + C, also cache `history_band` per sample set and minute: → 18 ms, but sparklines redraw at most once a minute.

## Acceptance criteria
From B.'s answer (pending). For the recommended A + C:
1. `server_history.recent()` keeps the decoded rows in memory and re-reads only when the table changes (key: db path + `MAX(ts)` + `COUNT(*)`); `since` is filtered in Python. Thread-safe.
2. `sweep_stats` is memoised on the cached runner history (same pattern as `get_runner_history`).
3. The `/a/server` HTML is byte-identical to before for the same data and clock (a test renders both ways and compares).
4. A new sample or a prune shows on the next render (a test fails on stale-cache behaviour).
5. The Free space page and the JY-031 forecast loop give the same results as before.
6. `scripts/budgets.py` (n=20) on the NAS, three runs, all show the hub row p95 ≤ 50 ms with `/a/server` included; numbers in the PR.
7. The existing tests stay green; the suite only grows.

## Data
None (no schema change). In-memory caches only.

## Performance budget
Hub page render, warm p95 ≤ 50 ms (row 1); joey-hub memory ≤ 200 MiB (the cache holds ~5k small dicts; measure with `budgets.py`).

## Options and the pick
None for the screen (no visible change). One technical choice, question 1.

## Out of scope
Template or CSS changes; the media.db schema; the sample cadence or retention; the hub page.

## Accept checklist
- CI green; review posted; the three NAS budget runs in the PR.

## Questions for B.
Answers: B., orchestrator session, 2026-10-24: "Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance." = every recommended answer below, and ready.
1. How far to go? **A + C (recommended):** about 31 ms on the laptop, no visible change at all. **A + B + C:** about 18 ms, but the Server page's sparklines redraw at most once a minute.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #68, squash-merged as `8ffae27` (8ffae276895948737b83ab82e86c21cbbc85f49e).
- Deploy: `2026-10-24T01:07:20Z PASS prev=651ccd6 new=8ffae27 suite green, smoke ok tv=current end=2026-10-24T01:23:28Z dur=968s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
