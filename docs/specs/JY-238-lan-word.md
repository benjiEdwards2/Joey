# JY-238 One source for the "LAN" word

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/shell.py`, `hub/templates/server.html`, `hub/templates/media_apps.html`, `hub/templates/_app_link.html`, `tests/hub/test_lan_word.py`
Needs: JY-140 (shipped)
Options page: none: no screen change (the rendered HTML is byte-identical)

Source: the JY-140 review should-fix, 2026-10-24.

## Problem
`LAN_WORD` in `hub/server.py` is unused while three templates spell "LAN" themselves. Changing the word means three edits and a hunt.

## Acceptance criteria
1. `hub.server.LAN_WORD` is the one source. `hub/shell.py` registers it on the shared Jinja environment as the global `lan_word`.
2. `server.html` (Server card subtitle), `media_apps.html` (Health row) and `_app_link.html` ("Open <app> ↗") use `lan_word`; none spells the word.
3. The rendered HTML is unchanged: the existing JY-140, WP-H1 and WP-L1 tests pass untouched.
4. `tests/hub/test_lan_word.py`: swapping the global changes all three places (and only them); a scan fails if any template hardcodes the word outside comments.

## Data
None.

## Performance budget
None apply (one dict lookup per render).

## Options and the pick
None: no screen.

## Out of scope
Comments that mention "LAN"; the Python `is_lan()` logic; guest/Joey TV templates (none use the word).

## Accept checklist
- Server page, Media > Apps and Activity > Downloads look the same as on main.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #105, squash-merged as `459f106` (459f10625dd7c090946670df7109b2caa6f5265e).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
