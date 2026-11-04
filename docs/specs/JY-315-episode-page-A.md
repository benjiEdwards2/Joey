# JY-315 TV shows 2.2: episode page rebuilt (Q8), option A + episode carousel

Status: ready
Size: M
Live risk: none (no new upstream call; TMDB episode details already fetched for the episode flow)
Area: `hub/media_film.py` (episode_flow / episode_guests / episode_nav), `hub/templates/media_film.html` (episode branch), `hub/templates/_episode_flow.html`, hub CSS for the film page, `tests/hub/test_episode_*`
Needs: none (JY-282/288/289/290 shipped). TV untouched (waits for JY-307 phase 4).
Options page: https://claude.ai/artifact/38ZcW4DRSJ9xdf9Mdd96rV

## Problem
B. 2026-11-04 (mock-up page): "A" + "But I would still be keen to see the carousel of the episodes. Potentially as a to the left and to the right section." Q8 of the shows plan: what a single episode page should do.

## Build (option A as shot, plus the carousel)
1. Hero: the 16:9 episode still beside the text on desktop (>= 1024), above it on iPad and phone. Text column: crumbs (show > Season N > E#), eyebrow "Show · S2 · E3 of 8", episode title, the rating line (existing `epscore`), aired date · runtime, then the button row Play, Next episode, Rate, More (existing actions; "Next episode" = the next episode by number in the show, across the season boundary, hidden on the last aired episode), then the synopsis.
2. Episode carousel directly under the hero: one `.carousel` row (reuse the JY-304 cue: fade masks, half-card peek, arrows) of the season's episodes as 16:9 still tiles with "E3 · Name" captions, this episode marked (gold ring, "This one" chip as on TV), watched tiles with the seen check, scrolled on load so that this episode sits in view with earlier episodes to its left and later ones to its right. Left/right arrow keys on a focused tile move along it. Season chips (S1 / S2 / S3, existing `seasonswitch`) at the row's left end so the viewer can jump seasons; the chip for the page's season is `on`.
3. Guest stars as 2:3 cast tiles like a movie's cast row (existing `_film_cast.html` shape, initials fallback when no photo), capped at 12 with an "All N" fold like the movie cast row; "Directed by / Written by" lines (existing `crew_ep`) under it.
4. The season rating strip (`strip(mini=true)`) stays below the carousel; previous / next episode links at the bottom stay (existing `nav.prev` / `nav.next`).
5. Nothing new on the TV front; guest front unchanged.

## Acceptance criteria
1. Episode page at 1440: still left, text right, buttons on one row, carousel under the hero with this episode in view and the correct chip, guests as 2:3 tiles.
2. Episode page at 1024 and 390: still above the text, no horizontal page overflow, carousel scrolls with the cue.
3. The carousel's "this one" tile is the page's episode; clicking another tile opens that episode page; the season chips switch seasons.
4. "Next episode" opens the next episode by number (season boundary crossed); it is absent on the last aired episode.
5. More than 12 guests: 12 shown + "All N" fold; an episode with no guests shows no Guest stars block.
6. TV episode page unchanged (shot before/after identical); `tests/hub` + `tests/tv` pass; full tree passes.

## Out of scope
JY-314 (parked), JY-316/317, any TV change, new upstream calls.

## Accept checklist
Open an episode mid-season on desktop, iPad width and phone; scroll the carousel; use a season chip; press Next episode on the last aired episode (no button).

## Shipped notes
