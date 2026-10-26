# JY-255 RQ2 friend pick in TV mode

Status: building
Size: M
Live risk: arr/Seerr/qBittorrent write (the same Seerr writes as JY-231, now also sent from TV mode: the friend's own pending POST with `profileId` + `seasons`, and the admin-key PUT that keeps the pick)
Area: `hub/static/tv.js`, `hub/static/tv.css` (one tail block, no tokens), `hub/media_discover.py` (the JY-231 TV-mode gate), `hub/templates/_guest_request_panel.html`, `hub/templates/_request_block.html` (comment), `hub/static/control-surface.css` (one comment line, no tokens), `hub/README.md` "Requests", `docs/hub-changelog.md`, `tests/hub/test_guest_request_picks.py`, `tests/hub/test_tv_mode.py`.
Needs: JY-231 (merged at `bcfd1c4`).
Options page: none: the TV styling is RQ2's original TV build (`joey-rq2-friendpick` 2428063), on the existing request panel and the JY-188 TV recipes.

## Problem
JY-231 gave friends the Quality chips and season ticks on desktop and phone, and left TV mode out. B., 2026-10-27: "stop any tv development please". He then resumed TV work: "Go for tv change again."

So in TV mode (`html.tv`, `hub.media_front.tv_mode`) a friend picks quality and seasons when requesting, the same as JY-231 on the web. The source is RQ2's TV hunks on `joey-rq2-friendpick` 2428063 (`tv.js`, `tv.css`, the TV-mode panel and request path), ported by hand onto main's `tv.js` (JY-187 Back memory, JY-192 Rate strip + episode Back, JY-194 Discover search, JY-248 Home stop, JY-250 `history.back()`). That branch is not modified.

4K stays approval only (JY-231, B. 2026-10-27: "JY-231: go approve"). The `NEVER` set already refuses a friend whose Seerr user could auto-approve, in TV mode too.

## Acceptance criteria
1. In TV mode the Discover request panel is JY-231's form: Quality chips (the default preselected; no row with one profile) and, for a show, the season ticks ("All seasons" ticked, no "+ future", seasons on disk disabled, no Specials). Request keeps `data-first`, so one OK sends the defaults.
2. In TV mode the title page's confirm step shows the Quality chips, as on the web.
3. A TV-mode request carries the pick exactly as on the web: the friend's own request (`X-Api-User`), `profileId` and only the open ticked `seasons`, pending; an unknown profile falls back to the default; an override rule is undone by the admin-key PUT. Nothing approves (JY-231 criteria 3 to 8 hold in TV mode).
4. D-pad: Up from Request reaches the chips and ticks; Left / Right move between chips (the radio's own arrow-key change is prevented). OK (Enter, the WebView's DPAD_CENTER) on a focused tick or chip toggles it with a click (so the form's "All seasons" onchange runs) and does not submit the form. OK on Request still submits.
5. A tick inside the scrolling season list (or the dialog itself) is scrolled into its box when focused, since focus never scrolls (`preventScroll`).
6. Back (`window.joeyTV.back()`) closes the open panel and returns focus to the poster that opened it, from a chip or a tick too.
7. JY-188 holds: nothing in `tv.css` under 18 px (RQ2's 16 px season status line is raised to 18 px), density B unchanged, the 4 px ring sits on the chip's / tick's label, never on the 1 px radio. The panel never outgrows the TV viewport (it scrolls).
8. Every existing `tv.js` behaviour and its node tests hold: JY-187, JY-192, JY-194 (Enter on the search field is still the search, not a toggle), JY-248, JY-250.
9. The panel and confirm step leak nothing in TV mode (JY-231 criterion 11).

## Data
No tables, no migrations, no snapshot change. Seerr writes as JY-231 (`POST /api/v1/request` with `profileId` and `seasons`; `PUT /api/v1/request/{id}` with the admin key only when an override rule replaced the pick), now also from TV mode. `media_quality.choices(kind)` (cached 10 minutes) is read when a TV-mode friend opens the panel or the confirm step, never on a page render.

## Performance budget
- Media list / item page, warm p95 <= 150 ms.
- Discover page <= 3 s, never blocks.

The panel and the confirm step are explicit steps, not page renders; the profile read is JY-231's cached one. Builders have no NAS access, so the PR states this instead of a number; measured in the full check.

## Options and the pick
No options page: RQ2's original TV build on the existing panel. B.'s words:
- "stop any tv development please" (2026-10-27, JY-231 deferred the TV picks);
- "Go for tv change again." (2026-10-27, this item).

## Out of scope
- `tv/` (the Android shell) and any adb run in this build (the orchestrator holds the TV session).
- A per-friend 4K cap, hiding 4K (approval only, JY-231).
- Changes to the web / phone flow (JY-231 as merged).

## Test changes
- 2026-10-27: `test_tv_mode_keeps_the_request_flow_from_before_rq2` (JY-231 criterion 10, "TV mode unchanged") pinned the deferral this item reverses. It is replaced by `test_tv_mode_carries_the_picks_like_the_web`, which pins the opposite: chips, ticks and the profile in TV mode. B.: "Go for tv change again."

## Accept checklist
On the preview, as a friend:
1. With `?tv=1` in a browser: Discover › a film › the panel shows the Quality chips, default ticked. Pick 4K, Request. The answer reads "Requested in 4K — waiting for approval".
2. With `?tv=1`: a show's panel shows "All seasons" ticked and the season ticks. Tick Seasons 1 and 2 ("All seasons" unticks), 4K, Request: "Requested in 4K · Seasons 1–2 — waiting for approval".
3. Check in Seerr, or on Activity › Requests (JY-230): both requests are pending, requested by the friend, 4K and Seasons 1–2. Nothing approved.
4. **On the TV (Joey TV app):** Discover › a show › OK opens the panel with Request focused. Up reaches the Quality chips and season ticks; Left / Right move between chips; OK toggles a chip or tick (it does not send). A long season list scrolls to the focused tick. The focus ring is on the chip or tick, and no text looks smaller than the rest of the TV screens. Request sends; the answer shows the pick.
5. **On the TV:** open a panel, move to a tick, press Back. The panel closes and the poster that opened it has the focus.
6. **On the TV:** a title page's Request › the confirm step shows the Quality chips; OK on a chip toggles it, OK on Confirm request sends.

## Questions for B.
None.

## Shipped notes
