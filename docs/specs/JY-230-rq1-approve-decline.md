# JY-230 Approve / Decline pending Seerr requests on Activity > Requests (RQ1)

Status: shipped 2026-10-27
Size: L
Live risk: arr/Seerr/qBittorrent write
Area: `hub/media_requests_approve.py` (new), `hub/media_requests.py` (two error words), `hub/media_pages.py` (the Requests route), `hub/templates/media_requests.html`, `hub/templates/_request_seasons.html` (new), `hub/guest.py` (PRIVATE rows, ROW_DROP), `hub/main.py` (router), `hub/static/control-surface.css` (one dated tail block), `connectors/feeds/jellyseerr.py` + schema + fixtures + `config/sample_snapshots/jellyseerr.json`, `docs/connector-contract.md`, `docs/hub-changelog.md`, `hub/README.md`, `tests/hub/test_media_requests_approve.py` (new), `tests/connectors/test_jellyseerr.py`, `tests/connectors/test_contract_doc.py`, `tests/hub/conftest.py` (cache clear list)
Needs: none. JY-231 (RQ2, friend picks) builds on it: B. only sees a friend's pick in Joey once this is in.
Options page: none. Built 2026-10-22 before this spec existed; the panel reuses the Request confirm's Quality chips + season ticks and the Remove row's inline confirm (existing patterns). The four-size look is part of the accept checklist below.

Source: the original build `joey-rq1-approve` @ 37032e8 (2026-10-22, Opus, never reviewed), brought onto main 2026-10-27; the read-only review `JoeyTV/review/morning-2026-10-27/RQ-review.md` (JY-230 section); B.'s asks and answers in `LifeDashboard/archive/DECISIONS_to_2026-10-23.md`, "Request approval, friend picks, everyone's watchlist (2026-10-22)".

B., 2026-10-27, in chat: "JY-230: go".

## Problem
B., 2026-10-22: every Seerr request should be visible on the private Activity › Requests page (owner `you`), "where B. can change quality and seasons before approving". B.'s answers the same day: approval happens in Joey and Seerr stays the record. Joey edits the pending Seerr request (`PUT /api/v1/request/{id}` with `profileId` / `seasons`), then approves it (`POST /api/v1/request/{id}/approve`), with Decline beside it. Today B. has to open Seerr's own UI to decide a friend's or Georgina's request.

## Acceptance criteria
1. The Requests page lists every Seerr request (friends', Georgina's, B.'s), pending first. Each pending row says what was asked for in words, for example "4K · Seasons 1–2" (profile named from the cached quality list; a null `profileId` reads as the server default).
2. On the private front, owner "you" only, each pending row carries **Approve** and **Decline**. Non-pending rows carry neither (Remove stays as today).
3. Approve opens an inline panel: Quality chips with the asked profile checked (the default when null), and for TV the season ticks with the asked seasons ticked. Opening a TV panel lazy-loads the show's full season list (`GET /media/requests/{rid}/seasons`) from the cached Seerr title body. Specials are left out. A season on disk or held by another request is shown but cannot be ticked. If the title body is unreadable, the asked seasons alone are shown.
4. Decline is an inline confirm ("Decline the request for X?" / "Seerr keeps it as Declined. Nothing is downloaded."), never a browser dialog.
5. Approve reads the request live first (`GET /api/v1/request/{id}`). If it is no longer pending, nothing is written and the page says "That request is no longer pending".
6. Approve sends `PUT /api/v1/request/{id}` only when the profile or the seasons differ. The PUT carries the stored `serverId`, `rootFolder`, `tags` and (TV) `languageProfileId`, `seasons` as an int array, and no `userId`. A 202 ("no seasons available") approves nothing and says "Seerr has no seasons left to request".
7. Then `POST /api/v1/request/{id}/approve`. After a non-default profile, `media_quality.ensure` checks that the Radarr or Sonarr entry carries it; a warning line shows if it cannot confirm.
8. Decline reads the request live first, as Approve does (JY-230 review, 2026-10-27): a request already approved or
   declined in Seerr writes nothing and says "That request is no longer pending". Otherwise it sends
   `POST /api/v1/request/{id}/decline`; a 409 reads the same.
9. A profile id the app does not offer is a 422. A TV approve needs 1 to 100 seasons, each >= 1 (422 otherwise). Nothing is sent to Seerr in either case.
10. A decision shows at once: the row reads Approved / Declined and the counts follow, until a jellyseerr snapshot taken after it lands. The film page cache, the Search now lookups and the friend's own-request list (`media_guest_requests.forget_mine`) are dropped.
11. **Owner "you" only.** Georgina ("her") sees the page with no Approve / Decline and gets **403** on both POSTs and on the season list. The routes are PRIVATE in `hub/guest.py`, so the media front **404s** them before the handler for every visitor, signed-in friends included. The handler's own backstop (`_owner_only`) also returns 404 on the media front, even for owner "you".
12. Both writes need `same_origin`; a cross-site POST is 403. GET on the write paths is not a write (404/405).
13. **Cache-only render.** The page never calls Seerr on a render: no request read and no title read, on the first view or later, and it still draws with Seerr unreachable. The quality list fills after the response (the existing `media_quality.later`). Seerr is called only on the lazy season fragment and on the two POSTs.
14. Failures are words ("Couldn't reach Seerr", "Seerr refused (HTTP 500)", "Seerr is not connected"). Logs carry an HTTP status or an exception type only: never a URL, key or user name.
15. The media-front scrub drops `requested_by_id` (ROW_DROP) as it already drops `requested_by`.
16. **Decision overlay on restart: accepted as is.** The Approved / Declined overlay is in memory (`_decided` + `media_hidden`, one uvicorn process). A hub restart forgets it, so a decided row reads Pending again until the next hourly jellyseerr sweep. This is safe and accepted, not fixed: a second Approve reads Seerr live, finds it decided and writes nothing; a second Decline gets Seerr's 409. Both say "That request is no longer pending". Pinned by `test_a_restart_forgets_the_decision_and_a_second_click_writes_nothing`. A persisted overlay would add a media.db table for at most an hour of stale display; not worth it.
17. Phone (< 640 px): the three buttons (Approve, Decline, Remove) sit on their own line under the row (`.reqbreak`).
18. (Review, 2026-10-27) "Requested by" on the Requests page is "you" / "her" for the household, else the friend's
    name, never an email (connector: displayName, jellyfinUsername, username, skipping any with "@"; new
    `requested_by_jf` Jellyfin id, dropped on the media front).
19. (Review, 2026-10-27) A second approve or decline of the same request while one is being sent says "Already
    sending that one" and sends nothing. The decision notes are pruned once the sweep shows the request decided.
    Crafted non-ASCII digits in the flash params never 500 the page.

## Data
- Connector `jellyseerr`: reads the pending list on its own (`GET /api/v1/request?filter=pending&take=200`) beside the newest 100 of every status. Keeps every pending request, caps the rest at 60 (was 30 of 50). Adds per row `profile_id`, `requested_by_id` and, TV only, `seasons` (int list). One extra Seerr read per hourly sweep. Schema, fixtures (`raw_pending.json` new), sample snapshot and `docs/connector-contract.md` (jellyseerr block, and the **twentieth exception**: Approve / Decline live writes; renumbered from "nineteenth" on the merge, since P4 Quiet mode took that number on main) updated.
- Hub: no media.db change. In memory only: `media_requests_approve._decided` (request id -> decided fields) and `media_hidden` group `request-decided`.
- Seerr writes (live system, rule 7): `PUT /api/v1/request/{id}`, `POST /api/v1/request/{id}/approve`, `POST /api/v1/request/{id}/decline`. Only from B.'s same-origin POSTs. Tests fake every call; no test reaches Seerr.

## Performance budget
- Media list page, warm: p95 <= 150 ms for `/media/requests` (the render adds `overlay` + `attach`, caches only). Measured inside joey-hub on the NAS in the full check; numbers go in the PR.
- Hub page render, warm: p95 <= 50 ms, unchanged (the hub card does not use this module).
- joey-hub memory <= 200 MiB: the overlay holds at most one small dict per decided request until the next sweep (`media_hidden` caps a note at 6 h).

## Options and the pick
No options page (see the header). B.'s choices, 2026-10-22: friends pick quality (1080p / 4K) and seasons; B. can override at approval; approval in Joey, Seerr stays the record; Decline beside Approve. B., 2026-10-27: "JY-230: go".

## Out of scope
- Friends picking quality and seasons (JY-231 / RQ2).
- Everyone's watchlist and Request all (JY-232 / RQ3).
- A faster pending list than the hourly sweep. A brand-new request can take up to an hour to show.
- Persisting the decision overlay across a restart (criterion 16).
- Approve / Decline on the media front or in TV mode.

## Accept checklist
At four sizes (desktop 1440, iPad 1024, phone 390, TV 1920 × 1080) on the preview, as owner "you":
1. Activity › Requests: a pending friend request says what was asked ("4K · Seasons 1–2" or similar) and shows Approve and Decline; an approved row shows neither.
2. Open Approve on a TV request: the asked seasons are ticked, held / on-disk seasons are greyed with their word, Specials are absent, the asked quality chip is checked.
3. Decline opens an inline confirm, not a browser pop-up. Cancel closes it.
4. Phone: Approve, Decline and Remove sit on their own line, nothing overflows.
5. As Georgina: the page shows no Approve or Decline.
6. Signed in as a friend on the media front: `/media/requests` is a 404.
7. Live (B.'s go, rule 7): approve one real pending request with a changed quality, then check Seerr shows it approved with that profile and Radarr / Sonarr carries it. Decline one test request and check Seerr shows Declined.

## Questions for B.
None open. Criterion 16 (overlay lost on restart) is the builder's call, accepted as is with the reason given; say if you want it persisted instead.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #202, squash-merged as `d675f8f` (d675f8f2c483d4458a9f7b2e6cc6471a76777841).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-27: JY-246: A · JY-120: A · JY-151: A · JY-150: A · JY-121: A · JY-133: A · JY-134: A · JY-052: A · JY-053: A A A A · JY-230: go · JY-231: go approve · JY-232: go s1 · deploy"
- Follow-ups: none
