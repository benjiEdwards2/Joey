# JY-188 TV scale B, compact chrome (U2)

Status: shipped 2026-10-25
Size: M
Live risk: none
Area: `hub/static/tv.css`, `hub/templates/404.html`, `hub/templates/guest_signin.html` (no change needed), `tests/hub/test_tv_mode.py`
Needs: JY-189 (posters fetch h=600 in TV mode, merged)
Options page: `JoeyTV\mockups\tv-v2\08-density.html` (shell 08, options A / B / C, key T for chrome)

## Problem
B.: "rows way too large... cards also a little too large". Joey TV shows 6 posters across at 132x198 with a two-line caption (about 296 px per row, 1.5 rows on Overview) under 132 px of chrome. Plex and Jellyfin on Android TV show 8 to 11 across. Evaluation findings Z1/Z2 (scale), P1 (no scrim), O2/R4/Y3 (16 px text, 2.57:1 separators), P4 (Play 4.47:1), L3 (sign-in form below the fold), F1 (404 layout).

## Options and the pick
Gate 1, 2026-10-25, B. in chat: "JY-186: scale B, chrome on".
B = compact (Plex-like), compact chrome ON. TV mode only (`html.tv`); desktop, iPad and phone are unchanged.

## Acceptance criteria
1. Density B: shelf and grid cards 104x156 (poster fetch stays h=600 from JY-189), 14 px gaps, 8 across in the Movies / TV shows / Discover grids, two shelf rows plus a peek on Overview. Applies to Overview shelves, library grids and the title-page shelves.
2. Caption: title 18 px on one line always; meta 18 px under the focused card only (line height is reserved so nothing shifts).
3. Compact chrome: top bar 64 px (27 overscan + 36 + 1), sub-tabs row 40 px, so a grid starts at y = 104. Brand mark 32, section pills 36 / 18 px, user chip 36. Overview has no sub-tabs; the first shelf label sits 12 px under the bar.
4. P1: a scrim gradient sits over the title-page backdrop. Facts line uses `--tv-t3`, synopsis `--tv-t2`.
5. O2/R4/Y3: nothing in `tv.css` under 18 px (was 16): `seclabel`, `row-meta`, chips, tags; `span.sep` colour is `--tv-t4` (was 2.57:1).
6. P4: the Play button (and the request panel's primary and the Request chip) use `--tv-primary` `#4f46e5`, white on it at 6.3:1 (was 4.47:1).
7. L3: when "Use username and password instead" is open, the Quick Connect block is hidden so the form fits above the fold.
8. F1: the 404 page in TV mode is a centred message with one 56 px "Back" button.
9. `tests/hub/test_tv_mode.py` audits that every `font-size` in `tv.css` is >= 18 px.

## Data
None.

## Performance budget
No server change. CSS only; `tv.css` is served only in TV mode.

## Decisions made while building
- Focus scale stays 1.06 (the mockup says 1.08 for B). `tv.js` `POSTER_GROW` is pinned to the scale by an existing test and `tv.js` is outside this item; changing both is a one-line follow-up if B. wants the lift.
- `guest_signin.html` needed no edit: L3 is one `:has(details[open])` rule.
- Existing test renamed `..._six_column_grid_...` to `..._eight_column_grid_...`, expectation 6 to 8 (dated line in the test).
- `tv.css` changes sit in blocks commented `JY-188` so U6, JY-248 and later TV items rebase cleanly.

## Out of scope
Nav row and `base.html` (JY-248), U6 (JY-192), option C, desktop / iPad / phone.

## Accept checklist
1. Overview: 8 posters across, two rows and a peek, the bar is 64 px; only the focused card shows its meta line.
2. Movies / TV shows / Discover: 8 across, grid starts under a 40 px sub-tab row.
3. A title page: backdrop darkened, facts and synopsis readable, Play clearly legible when focused.
4. Sign-in: open "Use username and password instead"; the Password field is fully visible.
5. A bad URL on the TV: centred "No page here" with a Back button.
6. **Device check (grouped TV session):** `tv_ui_capture.py device --only title_movie,title_series,notfound,overview` gives 0 `tiny` and `lowContrast` <= 2.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #162, squash-merged as `37bac74` (37bac745763741233db6ca3fab47df69b003962d).
- Deploy: `2026-10-25T02:08:49Z PASS prev=62e533d new=37bac74 suite green, smoke ok tv=current gate=-n2 avail=1962 end=2026-10-25T02:15:49Z dur=420s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
