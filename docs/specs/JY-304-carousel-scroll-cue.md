# JY-304 Carousel scroll cue (Discover first)

Status: shipped (live 91c73ab 2026-11-04)
Size: S
Live risk: none
Area: `hub/static/control-surface.css` (the `.carousel` block under "Posters: carousels", `.carousel.prov-row`), `hub/templates/media_discover.html`, `_shelf.html`, `_film_shelves.html`, `_services.html`, a small shared script only if the pick needs one, `tests/hub/`
Needs: none
Options page: yes, 3 options at desktop / iPad / phone / TV

## Problem
B., 2026-11-02: "I nee dthe UI to show carousel or ability to scroll for things. Currently it is not clear if I am able to scroll across things."

## What the code does today
- `.carousel` is a flex row with `overflow-x: auto`, scroll-snap and the scrollbar hidden (`scrollbar-width: none`, webkit scrollbar hidden).
- Phone: cards are 104 px wide, so about 26 px of the 4th card peeks at 390 px (a CSS comment says so). From 640 px cards are 144 px and nothing forces a peek.
- Desktop: a mouse has no visible control; the wheel scrolls the page, not the row.
- Precedent: the title page Episodes row (`.tl-row`) has `.tl-arrow` prev / next buttons and a wheel handler (JY-269 P2). Discover (`media_discover.html`, `<div class="carousel">`) and the other shelves have none.
- TV rows (`tvt-row`, `tv.css`) are D-pad driven; whether a cue is wanted there is Question 3.

## Acceptance criteria
1. On Discover, every row that overflows shows a cue on desktop, iPad and phone; a row that fits shows none.
2. The cue works without hover on touch (iPad, phone) and does not depend on colour alone.
3. The cue goes away at the end of the row and returns when scrolled back.
4. Desktop mouse users can move a row without a trackpad or shift-wheel (per the pick).
5. The same cue applies to the other `.carousel` rows (Home shelves, More on Joey, person pages, Services) unless the pick limits it to Discover; the builder lists the rows touched in the PR.
6. Colours, radii and spacing come from existing tokens (`CLAUDE.md` rule 9); no new `:root` values without B.'s OK.
7. Keyboard: the row stays focusable and arrow-scrollable; arrow buttons (if used) are real buttons named "Scroll left" and "Scroll right".
8. TV: no change unless Question 3 says so; `test_tv_*` untouched.
9. Tests: the cue markup renders on an overflowing row and not on a short one; arrows are hidden or disabled at the ends; existing carousel tests stay green.

## Options (page to build)
- A. Edge fade + peek. A soft fade on the right edge when more is hidden, and a guaranteed half-card peek at every width. Pure CSS, no buttons.
- B. Arrow buttons. Round prev / next buttons on the row edges (the `.tl-arrow` pattern), shown on desktop and iPad, hidden at the ends; phone relies on the peek.
- C. Both (recommended): fade + peek everywhere, arrows on desktop and iPad.

## Data
None.

## Performance budget
Discover page <= 3 s and never blocks; Hub page p95 <= 50 ms; no new requests. Any script is small, inline, and runs after load. Measured on the preview.

## Out of scope
TV rows (unless asked), the Episodes row, scroll or snap behaviour, new row content.

## Accept checklist
- [ ] Discover on desktop, iPad and phone: it is obvious which rows scroll.
- [ ] A short row shows no cue.
- [ ] A mouse on desktop can move a row without shift-wheel.

## Picked (B., 2026-11-04, options page)
Option C on "Every carousel.": every `.carousel` shelf off the TV (Home, Discover, title pages, person page, services rows) gets an edge fade that follows the scroll position, a half-card peek on every width (3.5 / 5.5 / 6.5 / 9.5 / 11.5 cards, never smaller than the old 104 / 144 / 184 / 216 px cards; "More on Joey" keeps its 2.3 on a phone), and round prev / next buttons (the `.tl-arrow` glass) from 768 px, hidden at the ends, keyboard focusable, labelled. Built as stylesheet rules plus a small shared block in `hub/static/joey.js`. TV rows (`html.tv`) untouched.

## Questions for B.
1. Which cue? A. fade + peek only, B. arrows only, C. both (recommended).
2. Scope: A. every carousel (recommended, one look), B. Discover only for now.
3. TV rows: A. leave them (recommended; the D-pad focus shows movement), B. add an edge fade.

## Shipped notes
