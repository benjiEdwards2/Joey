# JY-300 Requests + Upgrades merged (A: one page with a filter)

Status: building
Size: M
Live risk: none
Area: hub/media_pages.py, hub/media_upgrade_why.py, hub/templates/media_requests.html, media_downloads.html, _upgrades_list.html, _upgrade_why.html, tests/hub
Needs: JY-275 (#317, merged)
Options page: JoeyTV/review/JY-300-merged/options.md (option A)

## Problem
B., 2026-11-02: "Upgrades and requests can be merged. Could you please merge them and find a way to make it clean."

## Acceptance criteria
1. Activity › Requests shows a segmented filter: Requested, Missing, Upgrades, Done, each with its count. Plain links (`?f=requested|missing|upgrades|done`), so deep links and no-JS work; no `f` = the first non-empty filter (`?why=` alone opens Upgrades). `?f=all` lists every request row (no chip).
2. Requested = Pending / Declined / Failed; Missing = approved, processing, partly available; Done = Available (fulfilled requests already in the Seerr data); Upgrades = the arr cutoff-unmet block (viable rows, "Nothing to upgrade", the folded unchecked rows).
3. One row style; every action stays one click from the row: Approve, Decline, Remove, Upgrade, Why? (Search now inside it), per-episode fold-out (JY-109).
3a. Approve, Decline and Remove return to the filter they were posted from (`?f=` on the form action; absent or unknown = the default). Why?, Upgrade and Grab return to `?f=upgrades`.
4. Both sweeps (Search missing, Search upgrades) stay in the page header, above the filter.
5. The Upgrades section is gone from Activity › Downloads; everything else there stays (qBittorrent groups, controls, purge, Finished today, last-search lines, sweeps).
6. Why? / Upgrade / Grab links and no-JS redirects point at `/media/requests?f=upgrades&why=…`.
7. Friends: unchanged (the page is owner-only; guest tests unchanged). Owner-only routes unchanged.
8. No horizontal overflow at 2560 / 1024 / 390 (the filter is `.chips`, which wraps).
9. /media/requests warm p95 <= 150 ms (the Upgrades rows are linked only when that filter is open).

## Data
None new. Reads the jellyseerr and arr snapshots as before.

## Performance budget
Page budget row for /media/requests (warm p95 <= 150 ms).

## Options and the pick
Option A, B. 2026-11-04. "Yes, it goes." (the Upgrades list under Downloads). Friends keep what they have; nothing else removed.

## Out of scope
Purge / delete files (stays on Downloads). New friend-facing views.
