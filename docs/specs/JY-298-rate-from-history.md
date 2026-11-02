# JY-298 Activity: rate from History, drop "To rate"

Status: spec
Size: M
Live risk: none
Area: `hub/media_nav.py` (Activity tabs), `hub/media_pages.py` (`/media/diary`, `/media/history`), `hub/templates/media_diary.html`, `media_history.html`, `_to_rate.html`, `_rate.html`, `hub/media_write.py`, `hub/media_db.py` (only if Question 1 picks a new store), `hub/guest.py` allow-list, `tests/hub/`
Needs: B.'s answers to Questions 1 and 2
Options page: no

## Problem
B., 2026-11-02: "History and to rate contain the same. Could you remove 'to rate' and allow people to rate through History with a button to clear all recent rating requests."

## What the code does today
- Activity tabs (`media_nav.py`): Live, History (`/media/diary`), To rate (`/media/history`), Library. The To rate tab carries the waiting count (`waiting["to_rate"]`), and the hub card and Media front reuse that same count.
- `/media/history` (`media_history_page`) lists the inbox from `media_home._to_rate(recent, ratings)`: unrated titles watched in the last `TO_RATE_DAYS` (30), one per rating key (show / season / episode per the owner's level), minus skipped keys. Each row is rendered by `_to_rate.html` with the 1-10 strip from `_rate.html`, plus Skip and Skip show buttons. A "Skipped" group below has Unskip.
- `/media/diary` rows already show a score via `rate.score_key` / `score_for`, so a rated title is visible on History; the page has no way to set a rating on an unrated row today (to confirm in the build).
- Stored data: ratings are rows in `media.db` table `rating` (`set_rating`, owner + item_key). "Skip" is the table `rating_skip` (owner, key, kind, forever, title, poster; `skip` / `unskip` / `skips` in `media_db.py`). There is no separate "rating request" record: the inbox is computed on each load from Jellyfin recent history minus ratings minus skips.
- So "clear all recent rating requests" has nothing to delete as such; it would mean bulk-writing skips for every row currently in the inbox.
- Write routes: `POST /media/rate/skip`, `/skip-show`, `/unskip` in `media_write.py`; the guest allow-list in `guest.py` lists them as "the To rate inbox's own buttons".
- TV: `media_history.html` already hides empty sections on the TV and folds each row's strip under "OK to rate" (JY-195, JY-196). TV has its own rating templates for titles; whether the TV Activity page needs a History rating control is Question 3.

## Acceptance criteria
1. The Activity tab strip is Live, History, Library on desktop, phone and TV; no "To rate" tab.
2. `/media/history` still resolves (old links, bookmarks, the hub card) and goes to History, not 404.
3. On History, an unrated row inside the 30-day window shows the rating control; picking 1-10 saves via the existing rating write and the row shows its score without a full reload failure.
4. A rated row shows its score and lets it be changed or cleared, as the To rate rows do today.
5. TV rows follow the owner's rating level (show / season / episode) exactly as `_to_rate` does; one rating per key, never two for the same show.
6. Skip, Skip show and Unskip stay reachable from History (they replace nothing else) and behave as today.
7. A "Clear all rating requests" button sits on History, shows the number it will clear, asks once before acting, and afterwards the waiting count is 0 on the hub card, Media front and Activity.
8. Clear touches only the viewer's own requests and never writes a rating (no row gets a score).
9. Clear follows Question 1's answer, and the same action restores them if "undo" is chosen.
10. The waiting count no longer appears on a removed tab; it moves to the History tab (or is dropped, per Question 2).
11. Phone: strip and button reachable at 390 px without horizontal scroll. TV: D-pad reaches the control and the button; focus rings as existing.
12. Guests: allow-list updated so a guest can rate and clear their own; the play log stays private.
13. Tests: no To rate tab in the nav; `/media/history` redirects; clear leaves count 0 and no rating rows; clear is owner-scoped; existing skip tests stay green.

## Data
Question 1 decides. Preferred: reuse `rating_skip` (no schema change, no migration). A new table would need a `media.db` step in `media_store.STEPS`.

## Performance budget
History page <= 3 s and never blocks; Hub page p95 <= 50 ms; no new requests per row. Clear is one write transaction, not one per row.

## Out of scope
JY-299 (History per connecting user, only B. sees everything). This spec uses whatever owner scoping History has when it ships and does not change who sees which rows. Also out: Movies / TV Shows "To rate" tabs, Awards, the 30-day window length, the rating widget design.

## Accept checklist
- [ ] Activity has no To rate tab on desktop, phone and TV.
- [ ] I can rate an unrated title straight from History.
- [ ] The clear button empties my waiting count and rates nothing.

## Questions for B.
1. What does "clear all" do to stored data? A. soft-dismiss: write a skip for every current request, shown under Skipped and restorable with Unskip (recommended, no schema change), B. delete: remove the requests for good (needs a new "dismissed" store because the inbox is computed, so it would return on reload otherwise).
2. The waiting count: A. show it on the History tab (recommended), B. drop it.
3. TV: A. History on the TV gets the same rating control and clear button (recommended), B. phone and desktop only for now.
4. Should the button also clear titles already skipped, or only the open ones? Recommended: only the open ones.

## Shipped notes
