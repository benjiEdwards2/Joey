# JY-143 Prowlarr indexerstats window

Status: building
Size: S
Live risk: none
Area: `connectors/feeds/arr.py`, `tests/connectors/`, `connectors/README.md`, `docs/connector-contract.md`
Needs: none
Options page: none: tiny change that follows an existing pattern (the arr feed already counts "this week" with `ARR_WINDOW_DAYS`)

Live risk is `none`: the live check was one read-only GET against Prowlarr, run inside `joey-connectors` with its own config. Nothing was written on the NAS.

## Problem
HITLIST row: "Prowlarr indexerstats window. If cumulative, amber never clears; verify live." The hub's Library health line goes amber on `Prowlarr N failed grabs` whenever `prowlarr.failed_grabs` is above zero. The arr feed summed `GET /api/v1/indexerstats` with no dates.

Live check, 2026-10-24 (read-only GET, five indexers, counts only):

| Window asked | grabs | queries | failed grabs | failed queries |
|---|---|---|---|---|
| none (what the feed sent) | 306 | 2658 | 4 | 2 |
| last 30 days | 306 | 2658 | 4 | 2 |
| last 365 days | 306 | 2658 | 4 | 2 |
| last 7 days | 92 | 1022 | 0 | 0 |
| last 3 days | 44 | 305 | 0 | 0 |
| last 24 hours | 30 | 93 | 0 | 0 |

So the answer with no dates is all-time. The 4 failed grabs are older than 7 days and the amber would never have cleared. Prowlarr supports `startDate` and `endDate` on this endpoint (both answered above).

## Acceptance criteria
1. The arr feed calls `/api/v1/indexerstats` with `startDate` = now minus `ARR_WINDOW_DAYS` and `endDate` = now (UTC, `%Y-%m-%dT%H:%M:%SZ`). Test: `tests/connectors/test_arr_prowlarr_window.py` (red on the old code, which sent no params).
2. Envelope shape, schema and the failure handling are unchanged (`prowlarr: null` on a failed call, the key never leaked); the existing arr tests stay green.
3. `connectors/README.md` and `docs/connector-contract.md` say the counts are for the last 7 days.

## Data
Snapshot `arr.json`, object `prowlarr {grabs, queries, failed_grabs, failed_queries, indexers}`: same fields, now counted over 7 days. No schema change, no migration.

## Performance budget
None apply (one existing call gained two query parameters).

## Options and the pick
None: follows the existing "this week" window (`ARR_WINDOW_DAYS = 7`, JY-143 uses the same constant).

## Out of scope
The hub word. `Prowlarr 4 failed grabs` now means "in the last 7 days" but does not say so (see question 1).

## Accept checklist
After deploy: Library health on `/server` shows no amber `Prowlarr N failed grabs` while the last 7 days have no failed grabs (live now: 0, so the amber clears on the next hourly sweep).

## Questions for B.
1. Should the Library health words say the window ("Prowlarr 2 failed grabs this week")? A) Yes, add "this week" (recommended: otherwise the count reads as all-time). B) No, leave the words. Not blocking: this PR does not change the words.

## Shipped notes
PR: (draft, see the PR). Not merged or deployed.
