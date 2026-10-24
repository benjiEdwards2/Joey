# JY-117 Previous / Next cards: verify on a real episode

Status: accept
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
Live evidence, 2026-10-24 (GET `/media/item/<episode id>` from inside `joey-hub`, HTTP 200 each time; no secrets, cookies or user names read or printed):

| Show (season) | Episode | Eyebrow | Cards drawn |
|---|---|---|---|
| Ted Lasso S4 | first | "Ted Lasso · S4 · E1 of 10" | Next "E2 · Curiouser and Curiouser!" only |
| Ted Lasso S2 | mid-season | "Ted Lasso · S2 · E3 of 12" | Previous "E2 · Lavender" and Next "E4 · Carol of the Bells" |
| Ted Lasso S3 | last | "Ted Lasso · S3 · E12 of 12" | Previous "E11 · Mom City" only |
| Slow Horses S1 | first | "Slow Horses · S1 · E1 of 6" | Next "E2 · Work Drinks" only |
| Slow Horses S4 | first | "Slow Horses · S4 · E1 of 6" | Next "E2 · A Stranger Comes to Town" only |
| Slow Horses S6 | last | "Slow Horses · S6 · E6 of 6" | Previous "E5 · Sayonara" only |

Why the preview did not show them: the cards need `film.nav` from `episode_nav()` (`hub/media_film.py`), which needs the show's seasons read from Jellyfin (`media_item`). The code conditions are sound: `nav.prev` / `nav.next` are set from the episode's place in its season's list, `prevnext()` in `hub/templates/_episode_flow.html` draws nothing only when both are empty, and `media_film.html` calls it when `film.episode and epnav`. The demo snapshots (`hub.seed_demo`) hold only a Jellyfin summary line (no shows), and a demo hub has no `JELLYFIN_URL`, so a demo-data preview has no seasons and no neighbours to link. This is preview data, not a condition bug. Not reproduced in a preview hub (machine rule: builders run no hub), so the cause is read from code and from the live result.

Existing tests that pin the behaviour: `tests/hub/test_episode_flow_nav.py` (first episode has no Previous, last has no Next) and `tests/hub/test_episode_flow_templates.py`.

Result: verified, no change. Closes as "verified, no change".
