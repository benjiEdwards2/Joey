# JY-100 Episode pages: "N to watch" becomes "N left"

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/media_film.py`, `tests/hub/test_show_hero_progress.py`
Needs: none
Options page: none: follows an existing pattern (the show page already says "N left")

## Problem
HITLIST: "Episode pages: 'N to watch' → 'N left'. Wording matches show pages." The status line of an episode page read "On server · 6 episodes · 2 to watch · S4 E4 next". The show page reads "2 left" (E5/E6 progress words). The episode page has no progress words (no hours on an episode page), so it fell back to the old "N to watch" text in `hub/media_film.py`.

## Acceptance criteria
1. An episode page's status line says "N left" where it said "N to watch" (for example "On server · 6 episodes · 2 left · S4 E4 next"), with no hours.
2. "all watched" and the show page's progress words are unchanged.
3. Test: `test_episode_page_keeps_its_own_line` pins the new wording (failed on the old code). Dated pin change: 2026-10-24, the old assertion only said "no left"; wording now matches show pages per HITLIST JY-100.

## Data
None.

## Performance budget
None affected (one string).

## Options and the pick
None: follows an existing pattern.

## Out of scope
The Movies list head line "N films · W watched · N to watch" (films, not episodes).

## Accept checklist
Open an episode page: the status line says "N left".

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #76, squash-merged as `d2ce00b` (d2ce00b7e63a94a9b5a24cf7692ed87ff39e3d55).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
