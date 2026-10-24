# JY-190 Server fixes for friends on Joey TV (U4)

Status: shipped 2026-10-25
Size: M
Live risk: Jellyfin write (sign-out deletes the friend's own device, admin key)
Area: hub/guest_signin.py, hub/guest_auth.py, hub/guest.py, hub/media_wrapped.py, tests/hub
Needs: none
Options page: none: server fixes, no new screen (the 404 and the Diary card keep their existing markup)

Live risk sets the review tier (see `docs/PROCESS.md`). Anything other than `none` is reviewed as L.

## Problem
Three faults from the TV UI review of 2026-10-23 (`JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md`, plan row U4 in `JoeyTV\TV_UI_PLAN.md`):

- **L4.** The web sign-out leaves the friend's Jellyfin device behind. A friend capped at `MaxActiveSessions 2` then holds two devices, and the next Quick Connect approval answers 403 until a device is removed. A friend with two TVs hits the same wall.
- **F1.** On the friends' front the 404 page says "Not signed in" in the top bar although the session is valid.
- **Y1.** The Diary's "This month" card on a friend's TV shows the household's numbers (films, episodes, hours, "mostly Wednesday evenings"), while the line under it says "0 this week · 0 this month". A friend must never see household numbers.

## Acceptance criteria
1. L4: `POST /signout` with a friend's session revokes the token (`/Sessions/Logout`), then deletes this browser's Jellyfin device (`DELETE /Devices?id=<__Host-jm_dev>`, admin key). Test: `test_signout_deletes_the_friends_own_device_after_the_logout`.
2. L4: the device is deleted only when Jellyfin's `/Devices/Info` says it was last used by the friend whose session is signing out, through Joey Media. A household user's sign-out (`you` / `her`) never deletes a device; a device cookie naming a household device, another friend's device or another app's device deletes nothing. Tests: `test_a_household_users_signout_never_deletes_a_device`, `test_a_device_last_used_by_someone_else_is_never_deleted`, `test_a_device_of_another_app_is_never_deleted`.
3. L4: a failed delete or an unreachable Jellyfin never fails the sign-out (303 /signin, cookie cleared). The log line says `guest: device not removed (...) jf:<id>`, with no name, token, key or device id. Tests: `test_a_failed_delete_still_signs_out_and_logs_no_secret`, `test_jellyfin_unreachable_for_the_device_check_still_signs_out`, `test_no_session_no_device_call`.
4. F1: on the media front the 404 page's user chip names the signed-in friend or household user. Denied and unknown paths still give the same page for the same visitor; no session still renders as not signed in. Tests: `test_the_404_names_who_is_signed_in[friend|household]`, `test_the_404_without_a_session_stays_not_signed_in`, and the existing `test_signed_in_friend_gets_the_same_404`.
5. Y1: the Diary month card (and Wrapped's summary under it) for a friend reads only rows owned by that friend's `jf:<id>`: diary rows and recorded plays. With no rows of their own the card says "<Month> · nothing yet", never the household's month. The private front's you / her / both views are unchanged. Tests: `tests/hub/test_guest_month_card.py` (privacy: `test_the_friends_diary_page_never_shows_household_numbers`).

6. Review should-fixes (2026-10-25): the device lookup and delete run as a BackgroundTask after the 303, and the identity read before the logout waits at most 3 s (`test_the_device_calls_run_after_the_response_is_sent`, `test_the_signout_identity_read_has_a_short_timeout`); a friend's shows in Wrapped's summary carry no household progress words (`test_a_friends_shows_carry_no_household_progress_words`).

## Data
No schema change. Reads `diary` and `play` in media.db, filtered by `owner = 'jf:<id>'` for a friend. Jellyfin calls added: `GET /Devices/Info?id=` and `DELETE /Devices?id=` with `JELLYFIN_API_KEY` (already in `deploy/media.env`).

## Performance budget
Hub page render, warm, p95 <= 50 ms: the 404 on the media front now resolves the session (the cached 60 s verdict, so one `/Users/Me` call per minute at most). Sign-out adds two Jellyfin calls after the logout; it is not a budgeted page.

## Options and the pick
None: no new screen. L4 takes the plan's default (delete the device on sign-out). The alternative, raising the friend template to `MaxActiveSessions 3`, is B.'s call and not this item.

## Out of scope
- `MaxActiveSessions 3` on the friend template (`nas_scripts/joeytest_policy.py`).
- The TV styling of the 404 and the Diary (other U rows).
- Wrapped stays PRIVATE on the media front (Q18); its link on the card stays hidden there.

## Accept checklist
- Grouped TV run (one window, with the other U rows): `python tv_ui_capture.py signin --allow-write` PASS without its stale-device step (sign out, sign in, approve: no 403, joeytest holds one Joey Media device).
- On the TV as joeytest: open a missing page; the top bar shows joeytest's chip, not "Not signed in".
- On the TV as joeytest: the Diary's month card shows joeytest's own numbers (or "nothing yet"), never the household's.

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #149, squash-merged as `7a4e1da` (7a4e1dae4d4660ceae0f7e3c33fccb7520c595d1).
- Deploy: `2026-10-24T22:21:28Z PASS prev=81524f3 new=7a4e1da suite green, smoke ok tv=current gate=-n2 avail=1963 end=2026-10-24T22:28:43Z dur=435s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
