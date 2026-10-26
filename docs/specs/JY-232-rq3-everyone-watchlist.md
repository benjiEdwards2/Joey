# JY-232 Everyone's watchlist + Request all (RQ3)

Status: shipped 2026-10-27
Size: L
Live risk: arr/Seerr/qBittorrent write
Area: `hub/media_watchlist_everyone.py` (new), `hub/media_watchlist_db.py` (`all_rows`), `hub/guest.py` (PRIVATE rows), `hub/main.py` (router), `hub/templates/media_watchlist_everyone.html` + `_wl_request_all.html` (new), the link line in `media_watchlist.html` and `media_requests.html`, a commented tail block in `hub/static/control-surface.css` (no token change), `docs/hub-changelog.md`, `tests/hub/test_media_watchlist_everyone.py`
Needs: none
Options page: none. The screen was built 2026-10-22 (branch `joey-rq3-everyone-wl`, dbc18b1), before this spec, from B.'s asks; it reuses the existing row, chip, confirm and request-block recipes. B. reviews it on the preview at the four sizes.

Live risk sets the review tier (see `docs/PROCESS.md`). Anything other than `none` is reviewed as L.

## Problem
B., 2026-10-22 (ask 3): everyone's watchlist visible to B., "with a request button per row and one for the collective group", then B.'s normal request step (quality + seasons).

B.'s answers the same day (archive `LifeDashboard\archive\DECISIONS_to_2026-10-23.md`, "Request approval, friend picks, everyone's watchlist (2026-10-22)"):
- Watchlists = Joey's own: you, Georgina and every `jf:` friend, grouped by person.
- "Request ahead" is sent as B. (admin key, so Seerr auto-approves).
- Assumption (not asked then): "one for the collective group" = one "Request all" button for the whole list as currently filtered. Filtering to one person gives that person's group.

The 2026-10-26 review (`JoeyTV\review\morning-2026-10-27\RQ-review.md`, JY-232) found the build sound but flagged that Request all sent every show as all seasons. With auto-approve, one click could queue up to 20 whole series (the 2026-10-06/07 download flood). It offered three choices: all seasons, a lower TV cap, or Season 1 only.

B., 2026-10-27, in chat: **"JY-232: go s1"**. Go, with Request all sending shows as **Season 1 only**. Films are unchanged.

## Acceptance criteria
1. `GET /media/watchlist/everyone` shows every watchlist in media.db, grouped You, Georgina, then friends by Jellyfin display name ("Friend" while the name cache is cold). Person chips (All, each person) and Films / TV chips filter it. Each row has its status word (On disk, Requested, Processing, Not on server), kind and "Added <date>". A title on several lists is a row under each person. Empty: "Nothing on anyone's watchlist.", or "Nothing matches this filter." when a filter is on.
2. A row Not on server has Request. It opens the normal private confirm step (`_request_block.html`: quality chips, season ticks) inside the row. That single path is unchanged: B. still picks seasons per show there.
3. Request all covers the list as filtered: titles Not on server and not already requested, each once however many lists hold it. It opens an inline confirm panel, never a browser dialog.
4. **The confirm panel says plainly what will be sent**, for example "Request 12 films · 8 shows (Season 1)?", "Request 3 films?" or "Request 1 show (Season 1)?". Each show in its list reads "TV · Season 1". The words "all seasons" do not appear.
5. **Request all sends a show as Season 1 only** (`seasons: [1]`). Films go as before (no seasons). One quality chip row per kind in the batch, Seerr's default preselected.
6. Request all sends at most 20 titles per submit (`CAP`), one by one through `media_discover._send` as B. (admin key, no `X-Api-User`). Already requested, Processing and On disk titles are skipped. The page comes back with words: "Requested 7 · 1 failed: Already requested · 3 left · Request all again". A sent title reads Requested for an hour, until the jellyseerr snapshot has it. One Request all runs at a time: a second POST while one is sending (a double-click) answers "Already sending…" and sends nothing (review fix, 2026-10-27).
7. Privacy:
   - Owner "her" (Georgina) and every media-front visitor, including a signed-in friend, get the 404 page for all three routes. The routes are PRIVATE in `hub/guest.py`, and the handler refuses on its own as well (owner "you", private front only).
   - Friends never see each other's lists: a friend's own Watchlist page on the media front holds only that friend's rows, never another friend's or the household's, and never the "Everyone's watchlist" link.
   - The "Everyone's watchlist" link shows on Watchlist and Activity > Requests for owner "you" on the private front only.
   - Friend names come from Jellyfin `/Users`, kept in memory only and never logged. A failed read logs the exception type only.
8. No live calls on render. The page and the Request all panel read media.db and the snapshots only. The Jellyfin `/Users` read runs after the handler has built the response (a `BackgroundTask`), at most hourly, with a 60 s gap after a failure. The panel's quality rows read the arr profiles (cached) only after B.'s explicit click.
9. Main's newer behaviour is kept: JY-251 (friends never see household follow state), JY-190 / JY-247 (friend privacy) and JY-248 (the friends' nav; the household nav is unchanged). This page is private and draws no follow controls.

## Data
Reads the `watchlist` table for every owner (`media_watchlist_db.all_rows`, behind the owner gate). No schema change, no migration. Reads the jellyfin and jellyseerr snapshots. In-process only: friend names (1 h) and titles sent by Request all (1 h).

## Writes
Seerr `POST /api/v1/request` as B. (admin key), through the existing `media_discover._send`, only from Request all's POST (same-origin) and only after the confirm panel. No Sonarr follow. For a non-default quality the existing quality safety net (`media_quality.ensure`) runs after the answer. Tests use the Seerr fake; nothing calls a real Seerr.

## Performance budget
Media list page, warm: p95 <= 150 ms (`/media/watchlist/everyone`). Measured in the full check on the NAS; not measured by the builder.
The Request all POST makes up to 20 sequential Seerr calls in a worker thread. A slow Seerr means a long wait for that page, not a stalled hub.

## Options and the pick
- 2026-10-22: B.'s asks and answers above. No options page (built before the options rule was applied to it).
- 2026-10-27: Request all for shows, from the review's three choices (all seasons as built, a lower TV cap per click, Season 1 only). B.: "JY-232: go s1". Pick: **Season 1 only**. Films unchanged.

## Out of scope
- Per-show season choice inside Request all. B. picks other seasons on the show's own request step (the per-row Request, or the title page).
- Request approval in Joey (JY-230) and friends' quality / season picks (JY-231).
- Georgina's access to this page (B. asked for himself only).

## Accept checklist
On the preview, as B. (owner "you", private front), at desktop, iPad, phone and TV sizes:
1. Activity > Requests and Movies / TV > Watchlist each show an "Everyone's watchlist" link. It opens a page grouped You, Georgina, then friends by name.
2. The person and Films / TV chips filter the page, and "Request all · N" follows the filter.
3. Request all opens an inline panel that reads, for example, "Request 2 films · 1 show (Season 1)?" and marks each show "TV · Season 1".
4. Cancel closes it and nothing is sent.
5. In the her view, the page is the 404 page and neither link shows.
6. Signed in as `joeytest` on the media front, `/media/watchlist/everyone` is the 404 page and the Watchlist page shows only joeytest's own titles.

Only with a Seerr test target: send a small Request all and check in Seerr that each show was requested as Season 1 only.

## Questions for B.
None.

## Change log
- 2026-10-27: The tests that asserted shows go as all seasons (`test_request_all_sends_each_once_with_the_picked_quality`, `test_request_all_reuses_the_single_send`) and the panel heading "Request 3 titles?" / "Shows: all seasons" (`test_request_all_panel_lists_deduplicated_titles_and_quality_rows`) now assert Season 1 and the new heading. This follows B.'s "JY-232: go s1"; no test was removed or skipped.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #201, squash-merged as `bf482db` (bf482db4c4093514a1de7a556f4ef768a3154c54).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
