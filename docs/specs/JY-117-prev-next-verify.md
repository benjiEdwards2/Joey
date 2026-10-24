# JY-117 Previous / Next cards: verify on a real episode

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `docs/specs/` only (verification; no code change)
Needs: none
Options page: none: no screen change

## Problem
The Previous / Next episode cards (WP-E2, 2026-10-16) were not seen in the preview. Check that a real episode page draws them, and say why the preview did not.

## Acceptance criteria
1. On a real show with several episodes in a season, an episode page in the middle of the season draws both cards (`epnav-card is-prev` and `is-next`), each with "E<n> · <name>" and a link to that episode.
2. The first episode of a season draws Next only; the last draws Previous only (a missing side leaves its half empty).
3. Result: verified, no change.

## Data
None. Read-only GET requests to `localhost:8000` inside `joey-hub` on the NAS (2026-10-24, no identity header, so the "both" household view). Jellyfin reads only, as for any page view; nothing written, restarted or configured.

## Performance budget
Not applicable (no code change).

## Options and the pick
None needed.

## Out of scope
Changing the cards' look or wording. Any other episode-page block.

## Accept checklist
Open any mid-season episode on the live hub: "‹ Previous" and "Next ›" cards sit under "Where this sits in Season N". Open the first and last episode of a season: one card each.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #133, squash-merged as `9207882` (92078820a78b1d475e3170f34a1403382614e42c).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
