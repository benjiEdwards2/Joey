# JY-323 TV film page: cast as 2:3 tiles (not circles)

Status: shipped (merged 03257d3 2026-11-05 on B. Sweep 30 "JY-323: Accept"; deploy tonight) (B. 2026-11-05, Sweep 29 JY-307 Accept: "With the film page. can you please ensure the cast underneath the movie also have a similar 2:3 ratio poster instead of teh circular option. It can be smaller if proceeding with the 2:3 option.")
Size: S
Live risk: none (TV template/CSS only)
Area: `hub/templates/_tv_tile.html` (`person` macro), `hub/templates/_film_cast.html` (TV branch), `hub/static/tv.css` (`.tvt-person`, `.tvt-row-person`, skeleton), `tests/hub/tv_css.py` pins, `tests/hub/test_tv_*` that assert the cast row
Needs: JY-307 P4 #324 (main 2b4b290)
Options page: none (B. named the change)

## Problem
On the TV film page (P4 backdrop-led) the cast row under the title is kit circles (JY-259 P3). B. wants the same 2:3 portrait tiles the desktop movie page uses (`.casttiles`, JY-280), smaller than the poster rows is fine.

## Build
1. TV `person` tile: the headshot drawn as a 2:3 portrait (`aspect-ratio: 2 / 3`, small radius like the P3 poster tiles), name + role centred or left under it as the other TV captions; initials fallback keeps the same 2:3 box. Width smaller than a poster tile (about 0.75 of the poster-row tile; pick a rem value, pin it).
2. Apply on every TV page that uses the person macro (film, show, episode guests, person-page "also with" if any): one tile shape, no circles left on TV. Skeleton shape matches.
3. Focus ring and D-pad unchanged; the row still scrolls sideways and the TV audit (text floor, no sideways page scroll) passes.
4. `tests/hub/tv_css.py` pins updated (no `border-radius: 50%` on `.tvt-person`; 2:3 aspect); desktop/phone untouched.

## Acceptance criteria
1. 1920x1080 shot of a film page: cast tiles 2:3, headshot fills the box, name/role readable; one focused.
2. Show and episode page shots: same tile shape.
3. `grep` finds no `50%` radius on `.tvt-person` in tv.css; `tests/hub` + `tests/tv` pass; full tree passes.
4. Desktop 1440 / phone 390 film page before/after identical.

## Out of scope
Desktop/phone cast (already 2:3 on the movie page), the person page's own hero, new data.

## Shipped notes
