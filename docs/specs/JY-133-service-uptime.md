# JY-133 P7 Service history on the card

Status: spec (built as the recommended option for B.'s morning review, 2026-10-26)
Size: S
Live risk: none
Area: `hub/server_uptime.py` (new), `hub/server.py` (`service_card`, `build_server`), `hub/main.py` (`_server_response`), `hub/tasks.py` (`_server_tick`), `hub/templates/server.html` (the card), `hub/README.md`, `tests/hub/` (new `test_server_uptime.py`; one line in `test_server_page_speed.py`)
Needs: none (JY-144 and JY-226 shipped)
Options page: none yet. The before / after screenshots at four sizes are in `JoeyTV\review\morning-2026-10-27\JY-133\`.

## Questions for B.
1. Where do the 7-day numbers come from?
   - **A: Joey keeps its own 7-day record of Kuma's states (built as).** Each new Uptime Kuma snapshot (the 2-minute feed, already cached on disk) is sampled into media.db about every 5 minutes, the same way the System sparklines are (WP-U4). Each card gets one line: "99.4% up · 7 days · down 2d ago". It is the 7 days B. asked for, with no Kuma call. It starts empty: the line says "· 2 days" until a week is collected.
   - **B: Kuma's own ratios.** The connector also reads Kuma 2.x `monitor_uptime_ratio`. Kuma only gives 1, 30 and 365-day windows, so the card would say "99.8% up · 30 days". Numbers from day one and no new table, but not 7 days, and it needs a connector change.
   - **C: Both.** A, with B's 30-day figure shown until A has 7 days. Most complete, about twice the code.
2. When a service was down this week, also say when: **"down 2d ago" (built as)**, or the day and time ("down Tue 21:14"), or nothing.

Data / privacy / budget notes:
- Data: one new media.db table, `server_kuma_samples(ts TEXT PRIMARY KEY, states TEXT)`: one row per new `uptime_kuma` snapshot, `states` is JSON `{monitor name: up|down|pending|maintenance}`. Kept 8 days (about 1,500 rows while the NAS is on 07:00-22:00). Created on first sample; no migration.
- The NAS is off 22:00-07:00, so "7 days" means the hours it was on. Pending and maintenance samples do not count either way.
- Privacy: monitor names and states only. No URL, host, port or key is stored (the connector already drops them). The Server page is private-only.
- Budget: hub page render p95 ≤ 50 ms (`/a/server`). The render only reads a dict kept in memory (`server_uptime.peek()`); the sample and the 7-day sum run after the page (the existing background task) and on the hub's 5-minute Server loop. No live call on render.

## Problem
P7 from the 2026-10-19 Server review: "Uptime Kuma 7-day uptime % and last outage under each service." Why: "'Up' now vs 'flaky this week'." Today a card says only Up or Down and the response time.

## Acceptance criteria
For option A:
1. `server_uptime.sample(snaps)` stores the `uptime_kuma` snapshot when its `updated_at` is newer than the last stored row; never twice; nothing for a missing, error or empty snapshot; rows older than 8 days are pruned; never raises.
2. `server_uptime.summary(rows, now)` gives each monitor, over the last 7 days: up % = up / (up + down) samples, the days covered, and the time of the last down sample.
3. Words: "100% up · 7 days"; "99.4% up · 3 days · down 5h ago"; never "100.0%" for a monitor that was down (floor to one decimal, at most 99.9%); "today" when under a day is covered; no line without at least one up or down sample.
4. The Services card shows the words as a second line under the name (`<span class="svc-sub svc-uptime">`), matched to the monitor the same way as the response ms (name or id, any case). No matching monitor: no line.
5. The render never reads the table: `/server` with an empty cache shows no uptime line and still 200s; the after-page task and `tasks._server_tick` sample and refresh.
6. The existing Server tests stay green; the suite only grows. One existing test changes, dated 2026-10-26: `test_server_page_speed.py::test_server_pages_are_byte_identical_with_the_caches` holds the uptime cache empty (the after-page task would otherwise add the lines between its first and later renders); its JY-226 checks are unchanged.

## Data
New table `server_kuma_samples` (above). No snapshot change.

## Performance budget
Hub page render, warm p95 ≤ 50 ms (row 1): a dict lookup per card. Measured on the NAS by `scripts/budgets.py` at the full check.

## Options and the pick
See "Questions for B.". Pending B.'s pick; built as A.

## Out of scope
- Kuma's own 1/30/365-day ratios (option B).
- A per-service history page or sparkline.
- Discord alerts for a flaky service.

## Accept checklist
- Server › Services: each card with a Kuma monitor shows "N% up · N days".
- A service that went down shows "down …ago" on its card.
- After a week the line says "7 days".

## Shipped notes
