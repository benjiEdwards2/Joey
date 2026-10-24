# JY-153 Watchlist count line refreshes only on reload

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/media_watchlist.py`, `hub/media_awards_pages.py`, `hub/templates/_award_ballot.html` (+ one small part template), `tests/hub/`
Needs: none
Options page: none: tiny change that follows an existing pattern (the Awards deferred-part routes)

## Problem
On the Awards ballot, the worded "Watchlist" button on a row swaps itself when pressed, but the "N on your watchlist" line in the progress head beside it stays stale until the page is reloaded.

## Acceptance criteria
1. A ballot-style add or remove response (`style=ballot`, htmx) carries an `HX-Trigger: watchlist-changed` header. Non-ballot buttons (title page, Discover) are unchanged.
2. A new part route `/media/{movies,tv}/awards/part/watchlisted` (same `body`/`year` query as the other parts) returns the count line fresh from the database, for the same edition as the page. Degraded (no snapshot or no database) or a page with no progress head: 204, so the old line stays. The route is private (not a guest route): friends never see the count line (Q20), so the media front answers its ordinary not-found.
3. The count line (`#awprog-wl`) re-fetches that part when `watchlist-changed` fires, and swaps itself in place. Its markup and words are unchanged: "<b>N</b> on your watchlist".
4. The count equals the page's own count after a reload (rows of the edition on the list; shorts are not counted).
5. No new visual design; no CSS change.

## Data
None. Reads the owner's watchlist (`media.db`), no new tables.

## Performance budget
Media list page, warm p95 <= 150 ms (unchanged; one extra attribute on the page). The new part is one watchlist read.

## Options and the pick
None needed (follows the Awards `part/rows` and `part/categories` deferred-request pattern, with the htmx `HX-Trigger` event).

## Out of scope
Count lines on other pages (the Watchlist page head line and the nav tab counts are not touched).

## Accept checklist
On the preview, open Awards, press "Watchlist" on a row: the button flips and the "N on your watchlist" number changes by one at once. Press again: it goes back.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #78, squash-merged as `5ba6859` (5ba6859a930be35d335e3f3f099948678691f53b).
- Deploy: `2026-10-24T02:50:41Z PASS prev=3b20517 new=5ba6859 suite green, smoke ok tv=current end=2026-10-24T03:14:56Z dur=1455s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
