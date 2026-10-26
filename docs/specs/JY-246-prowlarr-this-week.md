# JY-246 Server page: "Prowlarr N failed grabs" says "this week"

Status: spec (built as option A; waiting for B.'s pick)
Size: S
Live risk: none
Area: `hub/server.py`, `tests/hub/test_server_library_health.py`, `tests/hub/test_server.py`
Needs: JY-143 (shipped: the arr feed counts the last 7 days)
Options page: none: one word added to an existing line

## Questions for B.
1. Should the Library health line say the window? (**built as: A**)
   - **A) Add "this week"** (recommended, built as): `Prowlarr 3 failed grabs this week`. JY-143 made the count cover the last 7 days (`ARR_WINDOW_DAYS`); without the words it reads as all-time, and it is the only amber word on the line.
   - B) Leave the words: `Prowlarr 3 failed grabs`. Shortest, but the reader cannot tell the window.
   - C) Put the window on the whole line: `Library health (7 days)`. The Radarr / Sonarr counts are live queue sizes, not 7-day counts, so this would be wrong for them.

## Problem
JY-143 changed the arr feed so `prowlarr.failed_grabs` counts the last 7 days, not all time. The Library health line under Services > Downloads still says `Prowlarr 3 failed grabs`, which reads as all-time. From the JY-143 spec, question 1.

## Acceptance criteria
1. `library_health()` returns `failed` = `Prowlarr N failed grab(s) this week` (singular `grab` for 1). Test: `tests/hub/test_server_library_health.py` (red on the old words).
2. The amber span on `/server` and `/a/server` shows the new words; zero failed grabs still shows no amber and no words.
3. No other word on the line changes.

## Data
None. `arr.json` `prowlarr.failed_grabs` is unchanged.

## Performance budget
None apply (one string).

## Out of scope
The connector window (JY-143, shipped). The Radarr / Sonarr counts.

## Accept checklist
`/server` Library health line: amber `Prowlarr 3 failed grabs this week` with the demo data; "all clear" with none.

## Shipped notes
(none yet)
