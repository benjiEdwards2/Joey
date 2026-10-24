# JY-140 Health rows say "LAN"

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/templates/media_apps.html`, `tests/hub/test_media_detail.py`
Needs: none
Options page: none: tiny change that follows an existing pattern (the Server card's "LAN" word)

## Problem
A Server card for an app with no gated hostname links to its LAN address and says "LAN" beside the name. The Health rows on `/media/apps` take the same `server.service_card` (so they already carry `lan`) but never show the word. A tap on such a row opens an address that only works at home, with no hint of it.

## Acceptance criteria
1. A Health row whose link is a LAN address shows the word "LAN" in its meta line, after the Up/Down word (same word and `a.lan` flag as the Server card).
2. A row with a gated hostname (the `service_card` sets `lan` False) shows no "LAN".
3. A Down row keeps its note after the word; the order is status, LAN, note.
4. Regression test `test_health_rows_say_lan_for_lan_only_apps` fails before the change and passes after; `python -m pytest -q tests/hub/test_server*.py tests/hub/test_media_detail.py tests/hub/test_app_links.py` green.

## Data
None. `service_card` already returns `lan`.

## Performance budget
None apply (one extra template conditional).

## Options and the pick
None: follows the Server card.

## Out of scope
Changing the word, the Server card, or the "Open <app>" button (already says LAN, JY-L1).

## Accept checklist
Open Media > Health on the preview: LAN-only apps (no gated hostname) show "Up · LAN"; an app with a gated hostname shows only "Up".

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #85, squash-merged as `2588cf7` (2588cf7f4bc03a36172e2b8d3c16f390626cbd9e).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
