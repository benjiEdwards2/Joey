# JY-055 Progress, resume and watched synced to Jellyfin

Status: review
Size: M
Live risk: none while `PLAYER_API` is off (how this item ships). Turned on, the player's reports write each member's
resume point and watched mark to Jellyfin as that member (JY-053, JY-054); nothing new writes anywhere else.
Area: `hub/player_api.py`, `hub/static/player.js`, `docs/playback-contract.md`, `tests/hub/test_player_sync.py` (new),
`tests/hub/test_player_js.py`, this spec, `hub/README.md`
Needs: JY-053 (shipped, e2ecc8d), JY-054 (shipped, f4d8c95)
Options page: none: no screen changes. The player looks as JY-054 built it.

## Problem
HITLIST: "Stop on one device, resume on another." JY-050 (B., 2026-10-24, "all recommended"), Q6 A: "Jellyfin is the
single record; Joey reads and writes progress and watched there". Criterion 7 of the player programme: stop on one device,
resume within 10 s of that position on another. JY-053 built the reports and JY-054 the `resume` read; this item checks
what they already do, closes the gaps, and makes sure Joey's own pages (Continue watching, progress words, Diary, History)
see plays made in Joey's player exactly as they see plays made in Jellyfin's apps.

## What was already there (checked 2026-10-27)
| Need | Where | Verdict |
|---|---|---|
| Position on pause, seek and stop | `player.js`: `pause`, `play`, `seeked` beat at once; 10 s heartbeat; stop on Back (keepalive), `pagehide` (sendBeacon), the end, a track change | covered, but see gap 1 |
| Watched at the end | Contract endpoint 3: Jellyfin keeps the watched mark. Jellyfin applies its own server rule to the stop's `PositionTicks` (past 90 % = played). The end sends a stop at the runtime | covered: Jellyfin's own rule, no `PlayedItems` call (same rule as Jellyfin's apps) |
| Resume from Jellyfin, each member's own user | JY-054 `resume: true`: `GET /Users/{uid}/Items/{id}` with the member's own token | covered |
| The recorder sees Joey plays | `media_plays.poll_once` reads `/Sessions` (admin key) and keys a play by `UserId`; the reports make a Jellyfin session for the member's user like any client | covered, if the token is the member's own user (gap 3) |
| Continue watching, progress words, Diary | Jellyfin sweep: `/Users/{uid}/Items/Resume`, NextUp, history `IsPlayed` by `DatePlayed`, per member | covered: client-agnostic; Joey plays show after the next sweep (about 2 min), as Jellyfin plays do |
| Title page after Back to Joey | `media_item` cache, stale-while-revalidate up to 10 min fresh | gap 2 |

## Gaps closed
1. **Position before the first frame.** A `<video>` holds 0 until hls.js seeks to the start point. The `play` beat, a
   heartbeat, a track pick, a hub-restart restart or a Back in that window reported 0 (JY-054's own test pinned the
   `play` beat at 0), and Jellyfin clears a resume point it is told is under 5 %: a quick Back after "Resumed at 23:41"
   lost the member's place. Now, until the picture reaches the session's start point (`playing` or a `seeked`), the
   player reports that start point.
2. **Stale title page after Back to Joey.** A stop the hub accepted drops `media_item`'s cache (whatever Jellyfin
   answered), as Mark watched and Reset progress do, and Back waits for the stop's answer (at most 1.5 s) before it
   leaves, so the page it lands on reads the new position and watched state.
3. **A player token on the wrong person.** If `JELLYFIN_PLAYER_TOKEN_HER` were made while signed in as B. (or the
   reverse), every play, resume point, watched mark, Continue watching row, Diary and History line would land on the
   other person, silently. A start on the private front now refuses a token whose Jellyfin user is not the member's own
   (`503 not_configured`, before PlaybackInfo), checked against the household ids the recorder has already read. The start
   never reads `/Users` itself; while the ids are unknown it goes ahead.

## Acceptance criteria
1. Before the first frame, every progress, stop, track-pick restart and session restart reports the session's start
   point; after `playing` or a `seeked`, the picture's time.
2. The end sends one stop at the runtime (Jellyfin's rule marks it watched); every stop carries a position (400 without:
   Jellyfin would mark an item played on a stop with none); the chosen audio and subtitle indexes ride on every report.
3. A stop of the caller's own session drops `media_item`'s cache, also when Jellyfin answers an error; a refused stop
   (someone else's session) keeps it. A heartbeat keeps it.
4. Back to Joey navigates once, after the stop answers or after 1.5 s, whichever comes first; the stop is `keepalive`.
5. A start whose player token is the other member's Jellyfin user is `503 not_configured` with no PlaybackInfo call and
   no token or id in the answer; the member's own token passes; unknown household ids never block a start or cause a
   `/Users` read.
6. With a fake Jellyfin that keeps sessions from the reports: the recorder records `her`'s Joey player play as `her`'s,
   moves it to finished at 95 %, and adds no row after the stop; `you` and `her` are recorded apart.
7. Every JY-053 / JY-054 test still passes; no live Jellyfin call in any test; nothing changes while the flag is off.

## Data
No media.db change, no snapshot change, no new env. Reads `identity`'s cached household ids (no new read).

## Performance budget
No page render changes (rule 7 holds: no live call on render). The API's hub overhead stays inside p95 <= 50 ms per
endpoint (`test_hub_overhead_is_inside_the_page_budget`, unchanged): the owner check is an in-memory lookup and the cache
drop is a dict clear. Back to Joey can wait up to 1.5 s longer for a slow stop; a normal stop answers in one LAN round trip.

## Options and the pick
None: no screen. JY-050 Q6 A (B., 2026-10-24, "all recommended").

## Out of scope
The TV player (JY-057, stopped); friends (JY-058); offline; changing Jellyfin's resume settings; a hub-side copy of
progress (Q6 B, not chosen).

## JY-056 check (audio and subtitle track picker)
JY-056 is covered by JY-054; no build here. Checked against JY-050 (Q5 A "follow each Jellyfin user's saved setting",
criterion 8 "every audio and subtitle track is selectable"):
- **Pick audio and subtitles:** JY-054's Audio & subtitles pop-up (bottom sheet on a phone) lists every audio and subtitle
  track from the start answer, plus subtitles Off; image subtitles are labelled "burned in". A pick restarts at the same
  point with the new indexes (the contract's way).
- **Defaults from each member's Jellyfin settings:** the start sends no index unless the member picked one, and PlaybackInfo
  runs with the member's own token and user id, so Jellyfin's `DefaultAudioStreamIndex` / `DefaultSubtitleStreamIndex`
  come from that member's language and subtitle-mode settings; the hub uses them as the session's indexes.
- **The choice remembered:** within a session the pick survives a hub restart and a back-forward-cache restore (JY-054
  tests). Across sessions JY-050 asks for nothing of Joey's own (Q5 A: "Joey adds nothing to maintain"): every report
  carries `AudioStreamIndex` / `SubtitleStreamIndex` (pinned here by `test_every_stop_carries_the_position_and_the_chosen_tracks`),
  so Jellyfin's per-user "remember audio / subtitle selections" keeps it per item, as for its own apps.
The orchestrator can close JY-056 as covered by JY-054.

## Accept checklist
Nothing to try while the flag is off. In the JY-054 accept window (flag on, player tokens set, on the preview):
- [ ] Play a film on the PC, stop half way with Back to Joey: the title page shows the new position at once.
- [ ] Open it on the iPhone: "Resumed at ..." within 10 s of the PC's point (JY-050 criterion 7). Then the reverse.
- [ ] Press Play and Back before the picture appears: Play again still resumes at the old point.
- [ ] Watch past 90 % (or to the end): the film shows watched in Joey and in Jellyfin; it leaves Continue watching after
  the next sweep (about 2 min), and the Diary has it.
- [ ] Server > History lists the play under the right person.

## Still to verify live (JY-054's accept window)
- Jellyfin 12.2's resume settings on the server are the defaults (5 % / 90 %); a different value changes when Joey marks
  watched, exactly as it does for Jellyfin's apps.
- The resume read (`/Users/{uid}/Items/{id}`, 2 s read timeout) answers in time on an item Jellyfin has not touched
  lately (the tech notes measured 2.5 to 9.6 s first-touch reads). A timed-out read starts from the beginning, and gap 1's
  rule then reports 0. Follow-up if it shows: raise that timeout, or skip reports until the member seeks.

## Test changes (rule 4)
- 2026-10-27: `test_progress_on_the_heartbeat_and_at_once_on_play_pause_and_seek` expected the `play` beat at 0 on a
  resumed start; that 0 was gap 1. It now expects the resume point (14,210,000,000). The other assertions are unchanged.
- 2026-10-27: the JS harness scenarios `happy`, `backStops`, `forgotten`, `pickTracks` and `reviveAfterPagehide` now fire
  the video's `playing` before they move the picture's time, as a real player does; their assertions are unchanged. The
  fake fetch gained an optional `stop` answer (for the Back wait).

## Questions for B.
None: every direction comes from JY-050's answers.

## Shipped notes
