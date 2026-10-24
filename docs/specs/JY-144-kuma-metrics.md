# JY-144 Uptime Kuma metrics failed on /server

Status: building
Size: S
Live risk: none
Area: `connectors/feeds/uptime_kuma.py`, `connectors/fixtures/uptime_kuma/raw.txt`, `tests/connectors/test_uptime_kuma.py`
Needs: none
Options page: none: tiny bug fix that follows the existing connector pattern

## Problem
The Server page shows `uptime_kuma failed 397 of the last 397 sweeps · Uptime Kuma metrics failed (unexpected payload)`. Every live sweep fails, so the Kuma card never has data.

Root cause (read-only probe from inside `joey-connectors`, 2026-10-24, metric names and label keys only): the NAS already runs **Uptime Kuma 2.5.6**, not the 1.x line the connector was written for. Kuma 2.x adds a `monitor_id` label and two new families, `monitor_uptime_ratio{...,window="1d|30d|365d"}` and `monitor_response_time_seconds{...,window=...}`. The parser picked lines by **prefix** (`line.startswith("monitor_response_time")`), so the 42 `monitor_response_time_seconds` lines were let in, then failed the exact-name line regex and raised "unexpected payload" for the whole sweep. `monitor_status` and `monitor_response_time` themselves are unchanged in 2.x (same values, same labels plus `monitor_id`).

## Acceptance criteria
1. Lines are picked by **exact** metric name (`monitor_status`, `monitor_response_time`); other `monitor_*` families (Kuma 2.x `monitor_response_time_seconds`, `monitor_uptime_ratio`, cert gauges) are skipped, not rejected.
2. `monitor_response_time_seconds` never overwrites the millisecond reading, whatever the line order.
3. The fixture `connectors/fixtures/uptime_kuma/raw.txt` is the Kuma 2.5.6 shape (sanitised: invented names and values, no URLs, no tokens), and the fixture transform result is unchanged (5 of 6 up, Prowlarr down, Jellyfin 38 ms).
4. Kuma 1.23-shaped lines (no `monitor_id`) still parse; malformed `monitor_status` / `monitor_response_time` lines still give the reason-free "unexpected payload" error; no URL, host or key leaks.
5. Regression test `test_kuma2_sibling_families_are_skipped_not_rejected` fails before the fix and passes after; `python -m pytest -q tests/connectors/` green.
6. After deploy: the Server page's Kuma card shows monitors and the failure counter resets (B.'s check; no deploy in this item's build).

## Data
None. Snapshot `uptime_kuma` envelope shape unchanged.

## Performance budget
None apply (one connector parse; no route change).

## Options and the pick
None: one obvious fix (exact name match instead of prefix).

## Out of scope
- Reading the new 2.x families (uptime ratio, average response) into the card. A separate idea if B. wants it.
- JY-200 (Kuma 1 → 2 upgrade): the live box already reports 2.5.6, so that row looks done; the orchestrator should confirm with B. and close it.

## Accept checklist
- After deploy, /server: the Uptime Kuma card lists the monitors; no "unexpected payload" line.

## Questions for B.
None.

## Shipped notes
Build check 2026-10-24: the fixed parser run read-only against the live payload inside `joey-connectors` parsed 14 monitors (12 up, 2 pending at the time), 11 with a response time. Counts only were printed.
