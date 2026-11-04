# JY-305 Desktop: taller hero carousel on load

Status: building
Size: S
Live risk: none
Area: `hub/static/control-surface.css` (`.pagehead` min-height rules, 768 px and up), `hub/templates/area_shelves.html` (the Home hero `pagehead(...)` call), `hub/templates/_pagehead.html` only if a modifier class is needed, `tests/hub/` (`test_home_shelves.py`, `test_joey_media_home.py`)
Needs: none
Options page: yes, 3 options at desktop / iPad / phone / TV (heights)

## Problem
B., 2026-11-02: "Show more of the carousel when loading into the overview page. I want to really see the impact of the image on the screen before having to scross down"

## What the code does today
- "The overview page" is read as Joey Home (Media, `area_shelves.html`): the Overview pill was removed (JY-248) and Home is where the backdrop hero lives. The hub front page (`hub.html`) has a plain `pagehead` with no backdrop. Question 1 confirms.
- The Home hero is `pagehead(h.title ...)` with a backdrop and `drift`. `.pagehead` has `min-height: 170px`, and `220px` from 768 px. Its content is the eyebrow, title, sub, the "Open in Jellyfin" action and the tab strip, so the image is a short band before the shelves.
- The title page hero already uses `min(56vh, 640px)` (desktop) and `min(48vh, 520px)` (iPad): the existing reference pattern.
- The TV Home has its own hero (`tv_home.py`, `tvt.hero`); the guest Home has none.
- The code draws one hero item (`media_hero`: playing, resume or newest). B. says "carousel"; Question 3 asks whether he means rotation or just a taller image.

## Acceptance criteria
1. At 1440x900 the Home hero fills the desktop height in the pick, with title, sub, action and tab strip readable and inside it.
2. At 1024x768 (iPad) the hero uses the iPad height in the pick; the first shelf title still shows on the first screen.
3. Phone (390x844) is unchanged; Play and the first shelf stay reachable without a long scroll.
4. TV Home and the guest Home are unchanged (`test_tv_home_jy259.py` untouched).
5. The height uses the existing viewport-relative pattern (`min(Nvh, Mpx)`), so it holds at other desktop sizes and is capped on very large screens.
6. Text keeps its contrast on the taller image (existing scrims; no new colours).
7. Other `.pagehead` pages (Library, Requests, Following) keep their heights.
8. Tests: the Home hero carries the new class or rule; other pageheads do not.

## Options (page to build)
- A. Moderate: `min(60vh, 640px)` on desktop, `min(48vh, 520px)` on iPad (same style as the title page hero; the first shelf title peeks below).
- B. Cinema (recommended for "see the impact"): `min(75vh, 800px)` on desktop, `min(55vh, 600px)` on iPad; the first shelf starts below the fold.
- C. Full screen: the hero is the whole first screen, with a small "scroll" chevron as the cue to the shelves.

## Data
None. The backdrop loads at `?h=1280` today (`_pagehead.html`); the builder checks it stays sharp at the chosen height and raises the size only if it does not.

## Performance budget
Media Home page p95 <= 150 ms warm (same markup). Backdrop bytes stay at the existing `h=1280` unless the sharpness check fails; then the new size and load time go in the PR. Measured on the preview.

## Out of scope
Rotating several hero items, changing which item is the hero, the title page hero (JY-269), phone and TV layouts.

## Accept checklist
- [ ] Desktop 1440x900: the image dominates the first screen.
- [ ] iPad: image large, first shelf title visible.
- [ ] Phone and TV look as before.

## Picked (B., 2026-11-04, options page) and re-target
Overview B (JY-276 / JY-277) landed first, so the Home hero is now the `.homecar` carousel in `hub/templates/_home_carousel.html`; this item now sets that slide's size (CSS `--slide-w`, slides stay 16:9). Option B "cinema": slide height min(55vh, 600px) from 768 px (iPad), min(75vh, 800px) from 1100 px (desktop), phone unchanged. From 1920 px and from 3000 px (review fix 2026-11-04): up to min(75vh, 1100px) high, 16:9, the 80vw width cap winning, so 1440-high desktops get about 1080 px.

## Questions for B.
1. Which page is "the overview page"? A. Joey Home with the backdrop hero (recommended), B. the hub front page (greeting, no image).
2. Which height? A. moderate, B. cinema (recommended), C. full screen.
3. "Carousel": A. just the single hero image taller (recommended), B. also rotate several titles (a bigger, separate item).

## Shipped notes
