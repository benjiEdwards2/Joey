# JY-321 Person page backdrop prefers an on-server credit

Status: review
Size: S
Live risk: none (no new upstream call)
Area: `hub/media_person.py`, `hub/media_person_photo.py`, `tests/hub/test_person_hero_jy291.py`
Needs: JY-291 (merged)

## Problem
B. 2026-11-04: "Potentially the backdrop of a movie they are in? If it is in the server. Otherwise, nothing."
JY-291 falls back to the backdrop of the person's most-voted credit, on the server or not.

## Build
Fallback order when no TMDB tagged image applies: the highest-voted credit that is "On server" and has a backdrop;
else the highest-voted credit with a backdrop; else no backdrop layer (plain hero). "On server" is the person page's
own `on_server` flag on each credit row. Tagged image first (unchanged). No new upstream call.

## Acceptance criteria
1. An on-server credit wins over a more popular off-server one.
2. When none is on server, the most popular credit with a backdrop is used.
3. When no credit has a backdrop, no backdrop layer.
4. TV person page unchanged (round crop, no backdrop).
