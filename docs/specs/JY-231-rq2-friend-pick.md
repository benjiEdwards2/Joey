# JY-231 RQ2 Friends pick quality and seasons when requesting (TV mode deferred)

Status: shipped 2026-10-27
Size: L
Live risk: arr/Seerr/qBittorrent write (Seerr: the friend's own pending POST, and the admin-key PUT that keeps the pick)
Area: `hub/media_discover.py`, `hub/media_guest_requests.py`, `hub/templates/_guest_request_panel.html`, `hub/templates/_request_block.html`, `hub/static/control-surface.css` (one tail block, no tokens), `hub/README.md` "Requests", `docs/hub-changelog.md`, `tests/hub/test_guest_request_picks.py`, `tests/hub/test_guest_requests.py`, `tests/hub/fake_seerr.py`. Not `hub/static/tv.js` or `hub/static/tv.css` (TV mode deferred, below).
Needs: none to merge. JY-230 (RQ1) shows the pick to B. on Activity › Requests. Until it merges, B. sees the pick in Seerr's own UI.
Options page: none: the panel reuses the title page's existing confirm-step recipes (Quality chips, season ticks), as B. asked ("like Seerr's request dialog"). See Questions for B. 1.

Source: the original build `joey-rq2-friendpick` 2428063 (2026-10-22, never reviewed), brought onto main by cherry-pick. B.'s asks and answers: `LifeDashboard\archive\DECISIONS_to_2026-10-23.md`, "Request approval, friend picks, everyone's watchlist (2026-10-22)". Review: `JoeyTV\review\morning-2026-10-27\RQ-review.md`, JY-231 section.

## Problem
B.'s ask, 2026-10-22: friends should "choose quality and seasons like Seerr's request dialog". His answers the same day: "friend picks quality (1080p / 4K) + seasons, B. can override at approval; approval happens in Joey and Seerr stays the record". The contract with JY-230 is the Seerr request itself, through its `profileId` and `seasons`. There is no Joey-side store.

Before this item, the media front sent no quality (Q19: "quality is an admin choice") and requested a show whole (`seasons=all`). This item reverses Q19 on purpose, for the friend's own request on desktop and phone. Approving stays B.'s job.

**4K policy.** The review found that nothing caps 4K: a friend can pick 4K on every request, and B.'s approval is the only control. B., 2026-10-27: "JY-231: go approve". So the 4K policy is approval only. Nothing auto-approves, and B.'s approval on Activity › Requests (JY-230) is the control. No 4K chip is hidden and there is no per-friend cap.

**TV mode deferred.** B., 2026-10-27: "stop any tv development please". RQ2's TV-mode work is left out of this item: `tv.js` (OK toggles a tick or chip, the scroll-in-box helper) and the `tv.css` panel rules. `tv.js` and `tv.css` stay exactly as on main. In TV mode the request flow stays as on main today: the panel is Request + Cancel and requests a show whole, the confirm step has no Quality chips, and no profile is sent. The original TV code is still on `joey-rq2-friendpick` 2428063. It can come back as its own item when B. restarts TV work.

## Acceptance criteria
1. On the media front, desktop and phone, the Discover request panel and the title page's confirm step show the Quality chips (`media_quality.profiles`, the default preselected). There is no chip row when only one profile exists.
2. For a show, the panel shows the season ticks: "All seasons" ticked, no "+ future", seasons already on disk disabled, Specials not offered.
3. The pick rides the friend's own request (`X-Api-User`, with the admin key beside it) as `profileId` and `seasons`. The request lands pending (status 1), requested by the friend.
4. An unknown or forged profile id falls back to the default. There is no 422 and no way to set an arbitrary arr setting.
5. Only ticked seasons the show has that are not on disk are sent. When none are left, nothing is sent and the friend sees "Pick a season that isn't here yet". When nothing at all is ticked, the panel comes back as the request form with "Pick at least one season" (it was a 422 the htmx panel swallowed), and nothing is sent.
6. If Seerr stored another profile (an override rule), `keep_pick` PUTs the pick back with the admin key alone. It acts only on a pending request and never touches the status. A refused PUT logs the HTTP status only.
7. **4K is marked for B.** A 4K + Seasons 1–2 pick is stored on the pending Seerr request as the 4K `profileId` and `seasons` [1, 2]. That is exactly what JY-230's row reads to show "4K · Seasons 1–2". The friend's answer reads "Requested in 4K · Seasons 1–2 — waiting for approval".
8. **Nothing auto-approves.** No friend request shape calls approve or decline, on the web or in TV mode. No body carries `status` or `is4k`: Joey's 4K is a profile on the one Seerr server, so Seerr's 4K auto-approve bits never apply. Every request stays pending, and the friend-path modules hold no approve or decline endpoint. A friend whose Seerr user could approve (ADMIN, MANAGE_REQUESTS, AUTO_APPROVE, AUTO_APPROVE_MOVIE / _TV, and the 4K bits AUTO_APPROVE_4K / _4K_MOVIE / _4K_TV) is refused before anything is sent ("Requests aren't set up for you yet").
9. No safety net (`media_quality.ensure`) and no Sonarr follow run on the media front.
10. **TV mode unchanged.** In TV mode (`hub.media_front.tv_mode`) the panel is main's Request + Cancel form (`seasons=all` hidden for a show, `data-first` on Request). The confirm step has no Quality chips. A posted `profile` is ignored: no `profileId` is sent and no PUT is made. `hub/static/tv.js` and `hub/static/tv.css` are byte-identical to main.
11. The panel and confirm step leak nothing: no Seerr URL, key, admin name or arr name, on the web or in TV mode.

## Data
No tables, no migrations, no snapshot change. Seerr writes: the friend's `POST /api/v1/request` (now with `profileId` and `seasons` off TV mode), and `PUT /api/v1/request/{id}` with the admin key, only when an override rule replaced the pick. Reads: `media_quality.choices(kind)`, which lists the arr quality profiles. It is cached 10 minutes and read only when a friend opens the request panel or the confirm step, never on a page render. The season ticks use the already cached title body.

## Performance budget
- Media list / item page, warm p95 <= 150 ms.
- Discover page <= 3 s, never blocks.

The panel and confirm step are explicit steps, not page renders. The profile read is cached 10 minutes, with a 60 s retry gate, and the last good list is kept. Measure in the full check on the NAS. Builders have no NAS access, so the PR states this instead of a number.

## Options and the pick
No options page: the panel reuses the title page's confirm-step recipes. B.'s words:
- "friend picks quality (1080p / 4K) + seasons, B. can override at approval" (2026-10-22);
- "JY-231: go approve" (2026-10-27: the 4K policy stays approval only);
- "stop any tv development please" (2026-10-27: desktop and phone only, TV mode deferred).

## Out of scope
- TV mode: the picks on the TV, the D-pad handling and the TV styling. Deferred by B. on 2026-10-27; the code stays on `joey-rq2-friendpick`.
- Showing the pick to B. on Activity › Requests, and Approve / Decline (JY-230).
- A per-friend 4K cap or pending cap, and hiding 4K from friends (B. chose approval only, 2026-10-27).
- Everyone's watchlist and Request all (JY-232).
- `tv/` (the Android shell).

## Accept checklist
On the preview, as a friend on the media front, at desktop and phone width:
1. Open Discover › a film › Request. The Quality chips show, with the default ticked. Pick 4K and send. The answer reads "Requested in 4K — waiting for approval".
2. Request a show with Seasons 1 and 2 ticked, in 4K. The answer reads "Requested in 4K · Seasons 1–2 — waiting for approval".
3. Ticking a season unticks "All seasons". Ticking "All seasons" clears the season ticks.
4. Open a show with a season on disk. That season's tick is disabled. Ticking only on-disk seasons gives "Pick a season that isn't here yet".
5. Check in Seerr, or on Activity › Requests once JY-230 is in. Both requests are pending, requested by the friend, and show 4K and Seasons 1–2. Nothing was approved.
6. With `?tv=1` in a browser (not on the TV), the Discover panel is the old Request + Cancel with no chips or ticks. A request from it sends no quality.

Deferred, not run in this item: an on-TV check (Discover panel, D-pad, OK on Request) belongs to the later TV item that brings RQ2's TV mode back. B. stopped TV development on 2026-10-27, so no adb and no TV session for JY-231.

## Questions for B.
1. Rule 2 gap: the 2026-10-22 build made no options page for the panel.
   - (A, recommended) Accept the panel as built, since it reuses the title page's confirm-step recipes.
   - (B) Ask for a four-size options page before accept.
2. Settled 2026-10-27 by B.'s "JY-231: go approve" (4K is approval only): Seerr's 4K auto-approve bits (AUTO_APPROVE_4K = 32768, _4K_MOVIE = 65536, _4K_TV = 131072) are now in `NEVER`. A friend whose Seerr user holds any of them is refused on the same NOREQUESTS path until the permission is removed in Seerr (runbook R1). Joey also never sends `is4k` (pinned).

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #205, squash-merged as `bcfd1c4` (bcfd1c4bf082a55be620075ea0711a0ed4f93ec9).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
