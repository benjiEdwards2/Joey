# JY-101 "N h this month" uses the old duration format

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/media_pages.py`, `tests/hub/test_media_history.py`
Needs: none
Options page: none: follows an existing pattern (`media_text.duration`, "1h 52m")

## Problem
HITLIST: "'N h this month' uses the old duration format (`media_pages.py`)." The numbers line on Activity > To rate (`/media/history`) printed decimal hours ("18.7 h this month · 45.1 h all time"). Everywhere else lengths read "1h 52m" (`media_text.duration`).

## Acceptance criteria
1. The numbers line prints watch time in the duration words: "18h 42m this month · 45h 6m all time" for 18.7 and 45.1 hours.
2. No watch time reads "0m this month · 0m all time" (was "0 h").
3. Tests: `test_history_page_renders_every_section_in_main` and `test_quiet_words_when_history_is_empty_or_absent` pin the new text. Dated pin change: 2026-10-24, both assertions carried the old "N h" wording, replaced per HITLIST JY-101.

## Data
Reads `history.hours_month` / `history.hours_total` (decimal hours, unchanged snapshot schema).

## Performance budget
None affected.

## Options and the pick
None: follows an existing pattern.

## Out of scope
The snapshot's decimal hours (connector and schema are unchanged).

## Accept checklist
Open Activity > To rate: the numbers line reads "Xh Ym this month · Xh Ym all time".

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #81, squash-merged as `219f96e` (219f96e5659ac13a37edc5b4a76b77f49c407b90).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
