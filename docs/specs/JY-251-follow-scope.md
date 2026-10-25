# JY-251 Follow scope on the friends' front

Status: building
Size: M
Live risk: none
Area: hub/templates/_film_makers.html, tests/hub
Needs: none
Options page: none: removes a household control from the friends' front, the same pattern as the person, series and show Follow lines (Q19)

Live risk sets the review tier (see `docs/PROCESS.md`). Anything other than `none` is reviewed as L.

## Problem
In the 2026-10-25 TV session the phone-width TMDB title page for Lupin (`/media/title/tv/96677`), signed in as the friend test account `joeytest`, showed "Following George Kay ✓" under "Created by", next to "Follow François Uzan", "Follow Marie Roussin" and "Follow Florent Meyer" buttons. joeytest never followed anyone.

## Evidence
- Shot: `Desktop\Claude\JoeyTV\review\tv-ui-2026-10-25\shots\phone\phone_title_tmdb_full.png`. The user chip reads "joeytest"; the line under the Created by cards reads "Following George Kay ✓" (green) and three "Follow <name>" buttons.
- Log: `Desktop\Claude\JoeyTV\scripts\logs\tv_session_1025.log` line 110 (#38, phone/title_tmdb captured), and lines 25 and 59 (the session is signed in as joeytest).
- Follows are household-wide. `media_follows` (`hub/media_follow.py:58`, `FOLLOWS_DDL`) has no owner column. `followed(kind)` (`hub/media_follow.py:173`) returns every followed TMDB id. No `jf:` owner exists for follows.
- Friends cannot write follows. `POST /media/follow/{kind}/{tmdb_id}` and `.../unfollow` are in `hub/guest.py` PRIVATE, so GuestGate answers the 404 page before any handler runs. So the "Following George Kay ✓" row is the household's follow, not joeytest's.
- Root cause: `hub/templates/_film_makers.html:14-15`. The F5 "Created by" Follow row calls `followed("person")` and draws "Following <name> ✓" or a Follow form with no front check. Every other Follow control already checks: the person page (`media_person.html:28`, `guest_allows(base, "POST")`), Follow series (`_film_collection.html:18`) and Follow show (`hub/media_follow.py:690`, `show_ctx`).

## Pages checked (friend, media front)
| Page | Household follow state shown? | Follow control shown? |
|---|---|---|
| TMDB show title `/media/title/tv/{id}` (Created by row, a deferred `makers` part) | yes (bug) | yes, dead button that 404s (bug) |
| Library show item `/media/item/{jf_id}` (same `media_film.html` + `_film_makers.html` part) | yes (bug, same template) | yes (bug) |
| Show page Follow show line | no (`show_ctx` returns None) | no |
| Film page Follow series | no (`guest_allows`) | no |
| Person page | no (`guest_allows`) | no |
| Discover (`media_discover_guest.html`) | no Following tab or state | no |
| Home (guest home, `hub/media_guest_home.py`) | no follow shelf | no |
| `/media/following` | PRIVATE, 404 | n/a |

## Decision
Friends have no Follow feature (Q19: Follow is a household admin control; a follow requests titles through the household's Seerr). So the friends' front shows neither the household's follow state nor any Follow control. No `jf:` owner scoping is added.

## Acceptance criteria
1. As a friend, a show title page with a followed creator carries no "Following <name> ✓", no "Follow <name>" button and no `/media/follow` form. The show's library item page and its makers part (`/media/item/{jf_id}`, `/part/makers`) carry no follow state either (review round 1, 2026-10-25; in the test fixture the friend's item part renders empty). Tests: `tests/hub/test_guest_follow_scope.py`.
2. As a friend, with the household following the person, the series and the show, the person page, film page and show page carry no "Following" text and no `/media/follow` action.
3. As a friend, the home page and Discover carry no follow shelf and no Following tab or text.
4. A friend's POST to every follow and unfollow path (person, collection, show; with a same-origin Origin header) is the 404 page, and `media_follows` is unchanged afterwards (rows added or removed: none).
5. The private front is unchanged: B. still sees "Following Cass Creator ✓" on the Created by row (existing `test_created_by_row_follows_a_creator_as_a_tv_maker`, plus a control case in the new file).

## Data
None. `media_follows` is read only.

## Performance budget
No change: one template condition (`not guest()`, a front check), one fewer media.db read on the friends' front.

## Options and the pick
None: same pattern as the other Follow controls.

## Out of scope
Per-friend follows.

## Accept checklist
- Signed in as joeytest, open Lupin (`/media/title/tv/96677`) on the phone: Created by cards show, no Follow line under them.
- On private Joey, the same page still shows "Following George Kay ✓".

## Questions for B.
1. Friends get no Follow feature (recommended, as Q19), or a per-friend Follow later (a new item)?

## Shipped notes
