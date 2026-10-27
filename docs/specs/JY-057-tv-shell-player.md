# JY-057 Joey TV shell player (look A, Classic overlay)

Status: building
Size: L
Live risk: deploy (a TV release). Merging publishes Joey Media 1.0.3: `tv.yml`'s `release` job cuts GitHub Release
`tv-2026102701` on `main`, and the next `deploy.sh` offers it to every TV. So the PR merges only in a TV session with B.
With `PLAYER_API` off (today), the release changes nothing anyone sees: every Play is still the Jellyfin hand-off.
Area: `tv/` (the shell: player, policies, resources, Gradle, `VERSION`, `NOTES.txt`, `README.md`, `ci/check_apk.sh`,
`ci/check_store_apk.sh`), `hub/guest.py` (the media-front gate for the player routes), `hub/media_front.py` +
`hub/media_film.py` (the TV Play mark), `hub/player_api.py` + `hub/media_watch.py` + `docs/playback-contract.md` (the
additive `up_next` field), `tests/hub/test_tv_player_front.py` (new), this spec, `docs/tv-release.md`, `hub/README.md`
Needs: JY-053 (shipped, e2ecc8d), JY-054 (shipped, f4d8c95), JY-052 (look A picked). JY-051 (open, PR #70) has no
engine verdict yet: see Question 1.
Options page: `JoeyTV/review/JY-052-player-options.html` (JY-052), option A "Classic overlay", TV frames.

## Problem
JY-050 (B., 2026-10-24, "all recommended"): Joey plays the film itself on the PC, then the phone, then the TV, household
only, replacing the hand-off to the Jellyfin app; on the TV "a new signed release replaces the hand-off after the TV UI
round (JY-042), so the shell changes once, with the Jellyfin app kept as fallback for one release" (Q7 A). JY-042 shipped
2026-10-25. JY-054 stopped TV work ("stop any tv development please", 2026-10-27). B., 2026-10-27: "Go for tv change
again." He picked look A, "Classic overlay" (JY-052).

So the Joey TV shell gets its own player. Today Play on a Joey Media page hands the item id to the official Jellyfin app
(`JellyfinLauncher`, route 1b), and Back from Jellyfin lands on the TV's home screen, not Joey. After this item, for a
household member with the flag on, Play opens Joey's own player inside the shell, and Back returns to Joey.

## What is built
**Engine: Media3 ExoPlayer 1.9.0** (`media3-exoplayer`, `-exoplayer-hls`, `-ui` for the `PlayerView` surface only), no
FFmpeg extension. See Question 1.

**The hub (media front, behind the same `PLAYER_API` flag):**
- `hub/guest.py`: `HOUSEHOLD_PLAYER` names the five JY-053 routes (POST start / stream / progress / stop, GET tracks).
  With the flag on, `GuestGate` serves them on the media front to a signed-in household member (`you`, which includes
  the household alias, or `her`) with that member's own session token (JY-053 Q1 A on the media front, Q2 A header only,
  Q3 A). A friend, a visitor with no session, a session Jellyfin refused, or any other method gets the ordinary Joey 404
  page, exactly as today. The routes stay in `PRIVATE`, so `allows()` still says no and no nav link derives from them.
  Flag off: nothing changes (the 404 page for everyone).
- `hub/media_front.py` `tv_player(request)`: true when the flag is on, on the media front, the user agent is the Joey TV
  shell at versionCode 2026102701 (1.0.3) or later (the user agent, never the `tv=1` cookie), and a household member is
  signed in. `hub/media_film.py` then adds the mark `&player=joey` to every Play / Resume / Next to watch link and every
  episode card (the same Jellyfin deep link, one more fragment parameter). Anyone else keeps the deep link byte for byte.
- `hub/player_api.py`: the start answer gains `up_next` (additive, 2026-10-27): `{item_id, label, runtime}` of the next
  aired episode, from the hub's item cache only (`media_watch.up_next`, the same rule as JY-054's card), or `null`. No
  Jellyfin call. `docs/playback-contract.md` has the dated line.

**The shell (`tv/`, 1.0.3, `versionCode` 2026102701):**
- `UrlPolicy`: a Jellyfin link whose fragment carries `player=joey` and a well-formed item id is `UrlDecision.Play`;
  without the mark (flag off, a friend, an older hub) it is today's `HandOff`. An old shell never sees the mark (the hub
  checks the version), and would hand off anyway (it reads only `id=`).
- `PlayerActivity` (not exported, item id the only extra, never a token): starts a session on the media front
  (`POST /api/play/sessions`, kind `tv`, a DeviceProfile from the TV's own decoders, `resume: true`), then the stream
  (`POST .../stream`). Hub calls carry the WebView's own cookies for the UI host (read from `CookieManager` per call,
  never stored) and the UI origin as `Origin`. The `Authorization` header from `/stream` is kept in memory only and sent
  only to the Jellyfin origin (`PlayerHttp`: OkHttp with redirects off, the header added per request on that origin
  only and removed on any other), never to the hub, never logged, never in a URL. A stream URL off
  the Jellyfin origin, or a header that is not `MediaBrowser ...`, is refused (fallback).
- Direct play when Jellyfin allows it (the file as is, range requests), else Jellyfin's HLS (remux or transcode).
  Start position from the answer (the member's own resume point). External text subtitles are side-loaded.
- **Look A on TV.** Over the picture: the title block top left (title, episode line, the method word Direct play /
  Remux / Transcode), "Resumed at 23:41" top right for 4 s. Two focus rows: the seek bar (chapter name and time above
  it, chapter ticks on it), then the buttons Play/Pause, Back 10 s, Forward 30 s, Audio & subtitles and, when there is
  one, Next episode. Audio & subtitles is one pop-up with two columns. The up-next card bottom right.
- **Keys** (`PlayerUi`, pure Kotlin): any key shows the controls. Controls hidden: Left −10 s, Right +30 s (bar
  focused), OK or Up/Down show them. On the bar: Left −10 s / Right +30 s (held keys repeat), Down to the buttons, OK
  play/pause. On the buttons: Left/Right walk them, Up to the bar, OK presses. Pop-up: Up/Down walk a list, Left/Right swap
  Audio and Subtitles, OK picks, Back closes it (focus back on Audio & subtitles). Media keys: play/pause, play, pause,
  fast-forward +30 s, rewind −10 s, next = next episode, stop = back to Joey. Controls hide after 5 s of playing.
- **Back** (`BackPolicy.player`): pop-up open = close it; controls up = hide them; otherwise (nothing up, or the
  up-next card) = stop the session and return to Joey, on the page Play was pressed on (reloaded, so progress is fresh).
- **Up next:** with an `up_next` episode, the card shows in the last 60 s while the controls are hidden, focus on Play
  now; OK plays it at once, Right is Watch credits (hides it), Back returns to Joey. At the end it counts down 8 s and
  plays it (a new session, its own resume point). A film, or a last episode, returns to Joey at the end.
- **Progress** (contract endpoint 3): every `heartbeat_s` while open, and at once on pause, play and seek. A failed
  heartbeat is ignored; `404 session_unknown` starts a new session at the position. Stop (endpoint 4) on Back, Stop, the
  end, Home (the player closes when the TV leaves it) and before Next, best effort. Back before the first frame stops
  too, at the position the session was asked to start at (the member's resume point, or 0), so the hub forgets it at
  once and Jellyfin's saved position does not move; a start that answers after Back is stopped the same way.
- **Tracks:** direct play switches inside the player (the n-th embedded track of that type, or the side-loaded
  subtitle); remux / transcode stop the session and start a new one at the position with the new `audio_index` /
  `subtitle_index` (the contract's way). Image subtitles in an HLS stream are burned in by Jellyfin.
- **Fallback (JY-050 Q7 A, the Jellyfin app for one release):** any failure before the first frame (the flag off, 401,
  403, 404, 409 `cannot_play`, 503, a sign-in redirect, a refused stream URL, a second network error or 502 / 504) or a
  fatal player error hands the same item to the Jellyfin app (route 1b, as today) with a toast saying so. A first
  network error, or a first 502 / 504 with `retry: true`, is retried once.
- `KeyPolicy`: unchanged for the WebView (media keys still go to the system there); the player owns its keys.

## Acceptance criteria
1. Flag off: every player route on the media front answers the ordinary Joey 404 page for everyone (unchanged tests),
   and no Play link carries the mark, on any device.
2. Flag on, media front: the household alias and `her` reach the five routes and play with their own session token; a
   friend and a visitor with no session get the ordinary 404 page; a wrong method is the 404 page; `allows()` still
   denies every player route.
3. The mark is added only for flag on + media front + Joey TV user agent at 2026102701 or later + household; a 1.0.2
   shell, the `tv=1` cookie on a desktop browser, a friend and the private front keep today's link byte for byte.
4. The start answer carries `up_next` from the cache only (no extra Jellyfin call), `null` for a film, the last aired
   episode or a cold cache; every JY-053 / JY-054 test still passes unchanged.
5. Shell JVM tests (red first): UrlPolicy's Play decision; BackPolicy.player; the PlayerUi state machine and keys
   (seek −10 / +30, two rows, pop-up, up-next, auto-hide, countdown, media keys); the start / stream / error parsing
   (stream URL on the Jellyfin origin only, the header shape); the fallback rules; track plans; the DeviceProfile; time
   words and chapters. `tv/VERSION` is 1.0.3 (`2026102701`), checked by the existing VersionFileTest rules.
6. `tv.yml` green: lint, JVM tests, debug APKs, APK checks (permissions now INTERNET + ACCESS_NETWORK_STATE + WAKE_LOCK,
   which Media3 declares, + REQUEST_INSTALL_PACKAGES on sideload), the secret scan. `ci.yml` green.
7. No token in a URL, a log, an intent extra, `SharedPreferences` or an error; the header goes only to the Jellyfin
   origin.
8. The TV device checklist below passes in the TV session, before the merge.

## Data
No media.db or snapshot change. The start answer gains `up_next` (additive). The shell stores nothing new (the
"returning from playback" mark it already has).

## Performance budget
- Hub: the media-front gate adds one session resolve per player call (the same `guest_auth` read every media page
  does). The `up_next` lookup is a dict read. The JY-053 overhead budget (p95 <= 50 ms) holds; the existing
  `test_hub_overhead_is_inside_the_page_budget` runs unchanged.
- Press to first frame on the TV: 5 s on the LAN (JY-050 Q8 A), measured in the TV session (see the checklist).
- APK size: Media3 adds about 2 MB; reported from the CI APK in the PR.

## Options and the pick
`JoeyTV/review/JY-052-player-options.html`, option A "Classic overlay" (B., 2026-10-27, "JY-052: A"). Its TV frames:
"Two rows (bar, buttons) plus one pop-up"; "Left/Right on the bar seeks back 10 s / forward 30 s; Down drops to the button
row; Back hides the controls, a second Back returns to Joey's episode page"; the pop-up "Up/Down walks a list, Left/Right
swaps Audio and Subtitles, OK picks, Back closes the pop-up"; up next "OK plays E4 at once, the 8 s countdown plays it
anyway; Right is Watch credits; Back returns to Joey".
Scope: B., 2026-10-27: "Go for tv change again."
Not built from the frames: a Chapters button (the chapter name and ticks on the bar instead, as JY-054 did).

## Out of scope
Friends (JY-058: a friend keeps the Jellyfin app); the FFmpeg extension (Question 1); HDR / Dolby Vision tuning beyond
what the TV's decoders do; the private front on TV; turning the flag on in production (the TV session does it on the
preview first); casting; offline.

## TV device checklist (the TV session, before the merge)
One state window: the TV awake on the LAN, `PLAYER_API=on` with the two player tokens on the joey-media front of the
preview (or production, B.'s call), the debug APK from this PR's `tv` run installed next to the release app
(`net.joeyhome.media.debug`). B. signs in as himself (the household alias) unless a row says otherwise.
1. [ ] A film page's Play opens Joey's player (not Jellyfin); the picture starts within 5 s on the LAN; the method word shows.
2. [ ] Controls: they show on any key, hide after 5 s of playing; the bar's Left/Right seek −10 s / +30 s; held keys repeat.
3. [ ] Down to the buttons; Play/Pause, Back 10 s, Forward 30 s work; Up returns to the bar.
4. [ ] Audio & subtitles: both columns list the file's tracks; a second audio track and a text subtitle play (row 10 and row 2 of the JY-051 test files); Back closes the pop-up.
5. [ ] Back with the controls up hides them; Back again returns to the same Joey page, with the progress updated.
6. [ ] Stop half way, then Play again on the same page: "Resumed at ..." within 10 s of where it stopped; the phone's player resumes there too.
7. [ ] An episode near its end: the up-next card shows; Watch credits hides it; at the end the countdown plays the next episode.
8. [ ] Remote media keys: play/pause, fast-forward, rewind, stop.
9. [ ] A DTS file (JY-051 row 7 or 8) plays with sound (Jellyfin transcodes the audio; the word says Transcode or Remux).
10. [ ] A PGS subtitle (row 4): shown (in the player for direct play, burned in for HLS).
11. [ ] Fallback: with `PLAYER_API` off on the front, Play opens the Jellyfin app as today (no mark on the link).
12. [ ] A friend (joeytest) on 1.0.3: Play opens the Jellyfin app as today.
13. [ ] Home during playback, reopen Joey Media: the Joey page, not a stuck player; Jellyfin shows the stop position.
14. [ ] The update drill: 1.0.2 offers 1.0.3 after the merge and deploy (`release_check.py`).
Record each first-frame time from the title block's "First frame N s after Play" line (time from the press to the
first rendered frame, as JY-054's web line; no token, no URL).

## Accept checklist
- The TV device checklist above, rows 1 to 13 on the debug APK, then merge (the release), deploy, row 14.
- The PR shows `tv` and `ci` green and the hub test output.

## Questions for B.
**1. TV engine.** JY-051's TV sitting has not run, so the study has no engine verdict (PR #70 is open, its matrix empty).
A) Media3 ExoPlayer in the Kotlin shell, without the FFmpeg extension: native HLS, sends the header on every request,
D-pad keys are plain Android keys, and look A is "closest to Media3's stock controller"; DTS and TrueHD audio are
transcoded by Jellyfin (about 2 % of the library on the J4125, JY-051 inventory). B) ExoPlayer with the FFmpeg audio
extension (`org.jellyfin.media3:media3-ffmpeg-decoder`): DTS / TrueHD decode on the TV, but the POM is GPL-3.0, so the
APK friends install would carry GPL terms. C) An HTML `<video>` in the WebView (reuse JY-054's player): no native work,
but TCL WebView codec reach and HDR are unknown and the header path needs hls.js for everything.
*Recommend A, and built: the same engine Jellyfin's own TV app uses, no licence change, and C's unknowns are what the
study was to measure. The sitting can still run on this build; if it shows a gap, B is one dependency line.*

## Review round 1 (2026-10-27)
Both Sonnet reviews PASS. Fixes asked for before the Opus verifier:
- The token on a redirect: Media3's `DefaultHttpDataSource` follows same-protocol redirects with the same headers, so a
  cross-host redirect would have carried the token. Streams now go through `PlayerHttp` (`media3-datasource-okhttp`,
  OkHttp 4.12.0): no redirect is followed and the header is set only on the Jellyfin origin. `PlayerHttpTest` proves it
  against two local servers (a 302 to the other host is never requested; the other host never sees the header).
- `up_next` per viewer: `test_up_next_on_the_media_front_is_each_viewers_own` (two members, two cached reads, each gets
  their own next episode, no watch state in it, a viewer with nothing cached gets none).
- Back before the first frame now sends a best-effort stop (see Progress above).

## TV session fixes (2026-10-27)
The TV session ran on the TCL with the debug APK at `0bd7e5b`, the household alias and `PLAYER_API` on. Rows 1, 2, 3, 5, 8,
11 and 13 PASS; three FAILs fixed here (tv/ only, no hub change: the hub passes the profile to Jellyfin, which decides the
method):
- **Row 4, audio & subtitles.** OK in the pop-up closed it, and the harness's reopen key sequence went astray, so the
  tick read None; its two Backs then left the player (the "subtitles []" and "still playing False"). Now OK picks and the
  pop-up stays open with the tick on the pick; Back closes it; a pick that restarts the session (remux / transcode) keeps
  the pop-up open on its column. The "Subtitles" entry in the audio list is the harness's dump slice running from
  `player_audio_list` to `player_subs_scroll`, which takes in the column header; the screenshot shows two clean columns.
  Test change, dated: `okPicksAndClosesWithFocusBackOnItsButton` became `okPicksAndThePopUpStaysOpenOnThePick`, and
  `anEmptyAudioListPicksNothing` now expects the pop-up to stay open.
- **Row 7, Watch credits.** Right on the card only moved the focus to a Watch credits button, so the card stayed. Now
  Right is Watch credits at once (look A: "Right is Watch credits"): the card hides and a running countdown stops for
  this episode; at the file's end the card and its countdown return and play the next one. Test change, dated:
  `theCardOkPlaysNowRightIsWatchCreditsBackIsJoey` asserts the one-press dismissal; new
  `rightDuringTheEndCountdownCancelsItForThisEpisode`.
- **Row 9, DTS.** The TCL lists a DTS decoder in MediaCodecList but stalls on DTS, so the profile said `dts` and
  Jellyfin answered Direct play. Now AAC / MP3 / Opus / FLAC / Vorbis come from the decoders, AC-3 / E-AC-3 from a
  decoder or an HDMI / ARC / eARC passthrough sink, and DTS / TrueHD only from such a sink (AudioDeviceInfo encodings),
  never from a listed decoder. On the TCL's own speakers Jellyfin then converts the audio and the meta says Transcode
  (or Remux). Test change, dated: `codecsComeFromTheTvsDecoders` now asserts a listed DTS decoder does not count; new
  `aListedDtsOrTrueHdDecoderIsNotTrusted` and `passthroughToAnHdmiSinkAddsDtsTrueHdAndDolby`.
- Re-run on the TV: rows 4, 7 and 9.

## Shipped notes
Not yet.
