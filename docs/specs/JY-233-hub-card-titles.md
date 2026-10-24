# JY-233 Hub card titles easier to see

Status: spec
Size: S
Live risk: none
Area: `hub/static/control-surface.css` (the `.tile` rules, not the `:root` tokens), `hub/static/tv.css` (TV size line), `hub/templates/_kpi.html` (only if the option needs markup), `tests/hub/`
Needs: none
Options page: https://claude.ai/artifact/QXF4eYxr54ha2hfeHWxTcA (private; every option at desktop, iPad, phone and TV)

## Problem
B., 2026-10-24: "can you please include logos for things closer to the 'media, calendar, server' titles or make the titles a little easier to see." Today each hub summary tile has a 10 px uppercase grey title (`.microlabel`, `--text-5`) at the top left and its area icon in a 36 px chip at the top right, far from the title.

## Acceptance criteria
From B.'s pick (pending). For the recommended option C:
1. Each hub summary tile shows the area icon in a 28 px chip directly before a 16 px semibold title-case title (`--text-2`); the value and the meta line run full width below.
2. TV size (tv.css): icon chip 40 px, icon 24 px, title 24 px.
3. Existing tokens and icons only; no `:root` token change (rule 9). The state word rules are unchanged.
4. The other tiles that use `_kpi.html` (area pages, Server summary) keep working; check each page that renders a tile at the four sizes.
5. Tests: a smoke test asserts the title and icon sit together in each hub tile; the existing tile tests stay green.
6. Hub page render warm p95 ≤ 50 ms (CSS only; measured with `scripts/budgets.py` after deploy).

## Data
None.

## Performance budget
Hub page render, warm p95 ≤ 50 ms (unchanged; CSS only).

## Options and the pick
Options page: https://claude.ai/artifact/QXF4eYxr54ha2hfeHWxTcA
- A: the 36 px icon chip moves left beside a 12 px semibold uppercase title (`--text-4`).
- B: the icon stays right; the title becomes title case, 15 px semibold, `--text-2`.
- C (recommended): a 28 px icon chip inline before a 16 px semibold title-case title (`--text-2`).
Note: the private hub never runs in TV mode today (TV mode is the media front's); the TV frames force TV mode onto the hub to show the TV-size line.
B.'s pick: (pending)

### Round 2
2026-10-24, B. on the round 1 page: "None of them are separable. Can you please find a coloured icon and make them slightly larger and try again." Round 1 (A, B, C above) is set aside. Round 2 options: coloured area icons, slightly larger, near the title, each option clearly different at a glance; same four sizes. Status stays `spec` until B. picks.
Round 2 options (same page, version 2):
- A (recommended): the area icon in its area colour (22 px) on a 40 px chip tinted 15 % in that colour, right before a 16 px white title.
- B: a solid 44 px chip in the area colour with a dark glyph, 17 px title beside it.
- C: a 56 px gradient app-icon tile at the card's left (Calendar shows today's date, e.g. "Sat 24").
Colours from existing tokens: Media `--orange`, Calendar `--sky`, Server `--teal` (Weather `--gold` if it ever gets a hub card); amber and green stay for states. No new tokens. The colour lives in config: `config/areas.yaml` gets a `tone:` per area (C also `icon_face: date`), read through the area registry into `_kpi.html` as `--tone`; no area names in hub code.
Needs B.'s OK: per-area colour was removed on 2026-10-06 (style guide §1.2); picking any round 2 option brings it back for the hub icons only.

## Out of scope
Area page headers; the Joey TV shell's own screens (JY-042).

## Accept checklist
- The preview (or screenshots at the four sizes) shows the picked look on the hub.

## Questions for B.
1. (Round 2) Which option? **A (recommended):** coloured icon on a tinted chip before a bigger white title. **B:** solid coloured chip with a dark icon. **C:** large app-icon tile; Calendar shows today's date. Picking any of them brings per-area colour back for the hub icons (removed 2026-10-06).

## Shipped notes
(filled at close-out)
