# JY-299 History tied to the connecting user (only the owner sees everything)

Status: shipped (#307, live pending, 2026-11-04)
Size: M
Live risk: none
Area: `hub/media_pages.py` (`/media/history`), `hub/media_home.py` (`view_jelly`, `_ratings`, `_to_rate`), `hub/media_plays.py` + `hub/media_plays_db.py` (`/media/server/history`), `hub/media_db.py` (owner helpers), `hub/guest.py` (allow-list), `hub/templates/media_history.html`, `media_server_history.html`, the TV history view in `hub/static/tv.js` / TV templates, `tests/hub/`
Needs: B.'s answers to Questions 1-3
Options page: no
Platforms: desktop, phone, TV

## Problem
B., 2026-11-02: "Ensure History is linked to the user connecting to the hub media. I am the only one that can see everything." Privacy item. Related: JY-298 (remove To rate, rate from History) changes the same page; this item covers whose rows appear, JY-298 covers the rating controls.

## What the code does today
- Identity: on the media front the view IS the signed-in identity's owner key (`shell.resolve_owner_view`): `you`, `her`, or a friend's `jf:<id>`. No identity gives no view, and the owner helpers fail closed (`media_db.owner_of`, `owner_filter`).
- Web Activity History, `/media/history` (`media_pages.media_history_page`): reads the Jellyfin snapshot through `media_home.view_jelly(data, view)`. B. sees the snapshot's history; `her` sees her own block; a friend or any non-household view gets `history: {}` (scrubbed), so a friend sees an empty list plus their own ratings and skips (`media_db.get_ratings` / `skips` by owner). Nothing is leaked, but a friend also never sees what they watched. Listed in `guest.GUEST` ("the play log stays PRIVATE" comment is about the server log, below).
- Play stats, `/media/server/history` (`media_plays.history_context`): `media_db.owner_filter(view)` filters `play` rows by `owner`. A friend gets only their `jf:<id>` rows; `you` / `her` get their own; the "both" view (private front only) is the household. The page is in the `GUEST` list, so friends can open it. Totals, busiest day and hours are aggregates of the filtered rows. No user name is shown, and the owner has no "everyone" view on the media front (it only reaches "both" off the media front).
- Diary, `/media/diary` (related, not History): `media_db.diary_scope` lets only `you` list everyone, naming rows "You" or the her-name; friends are always "mine". Friend rows are not named (the label is her-name for any other owner).
- `view_jelly` never lets a friend's play rows reach B.'s views (`household_sql` excludes `jf:%`), so today the owner cannot see a friend's plays either.
- TV: no history page of its own was found in `hub/`; `tv.js` only handles the browser history stack. Whether TV reuses `/media/history` is Question 3.

## Acceptance criteria
1. A friend sees only their own plays and ratings on every history surface: Activity History (`/media/history`) lists their own watched items (not an empty page), and `/media/server/history` counts only their plays.
2. The owner (`you`) sees every user's rows on both surfaces, each row naming the user; a per-user filter or "Mine / Everyone" switch is in the pick (Question 1).
3. `her` sees only her own rows (unchanged), unless Question 2 says otherwise.
4. TV follows the same rule as desktop and phone: same owner key, same data, no wider scope.
5. Any request with no signed-in identity returns nothing (fail closed), never everyone's rows. A friend cannot widen scope with a query string, cookie or `?owner=`.
6. Ratings, skips and the "rate now" rows on History stay per owner (JY-298 owns their UI; no overlap).
7. A user's name appears only to the owner; friends never see another user's name or counts.
8. No friend or household name, id or hostname in the repo, logs or fixtures; rows are keyed by the owner key only.
9. Existing tests stay green (`test_guest_*`, `test_history_nav`, plays and diary tests).
10. A test per surface: friend sees own rows only and none of another user's (Activity History, `/media/server/history`, TV); owner sees all with the user named; no identity gives empty.

## Data
Reads only: the Jellyfin snapshot (per-user history needs it keyed per user, not only B. and `her`; builder checks what the connector stores) and the `play` table (`owner`, `user_name`, `jf_id`, keyed per owner key). No schema change expected; if the snapshot lacks a friend's plays, the builder either reads them from `play` or reports it (Question 4). No writes, no new secrets.

## Performance budget
History page p95 <= 50 ms on the Hub render, no new blocking calls; at most one extra `play` query per request. Measured on the preview.

## Out of scope
Rating UI and the To rate removal (JY-298), the Diary, Wrapped, watchlist, and changing what is recorded.

## Accept checklist
- [ ] Signed in as a friend on desktop, phone and TV: History shows only my own plays and ratings.
- [ ] Signed in as the owner: History shows everyone's, each marked with who.
- [ ] A second friend's plays never appear for the first.

## Questions for B.
1. Owner view: A. everyone by default, each row named (recommended), B. "Mine / Everyone" switch defaulting to Mine (matches the Diary's setting).
2. Should `her` also see only her own (recommended), or everything like you?
3. TV: does it have its own History page, or reuse `/media/history`? I found no separate TV history view; confirm what you meant.
4. If a friend's watched items are not in the Jellyfin snapshot, is it fine to build their History from the recorded plays (so it starts from when recording began)?

## Shipped notes

## Shipped notes (2026-11-04)

Merged #307 on B.'s review-page answer (Accept, 2026-11-04 morning), live pending.
