# JY-054 Joey's own web and phone player (look A, Classic overlay)

Status: shipped 2026-10-27
Size: L
Live risk: none while `PLAYER_API` is off (how this item ships). Turned on for the accept, the player writes the
household's playback progress to Jellyfin as each member (JY-053) and needs the two player tokens (secrets).
Area: `hub/media_watch.py` (new), `hub/templates/media_watch.html` (new), `hub/static/player.js`, `player.css`,
`hls.min.js`, `LICENSE-hls.js.txt` (new), one router line in `hub/main.py`, two PRIVATE entries in `hub/guest.py`, the Play
href switch in `hub/media_film.py` + `hub/templates/media_film.html`, the additive `resume` option in `hub/player_api.py`
+ `docs/playback-contract.md` (outside the area, see "Outside the area"), `tests/hub/test_player_page.py`,
`tests/hub/test_player_js.py` (new), this spec, `hub/README.md`, `hub/static/README.md`
Needs: JY-053 (shipped, e2ecc8d), JY-052 (look picked). The iPhone check needs JY-014's preview hostname.
Options page: `JoeyTV/review/JY-052-player-options.html` (JY-052), option A "Classic overlay".

## Problem
JY-050 (B., 2026-10-24, "all recommended"): Joey plays the film itself on the PC browser, then the phone, then the TV,
household only, replacing the hand-off to Jellyfin's own web client. JY-053 built the playback API behind `PLAYER_API`.
This item is the page that uses it, on desktop / iPad and phone only.

B., 2026-10-27: "JY-052: A" (the Classic overlay look), "JY-053: A A A A" (every JY-053 recommendation: one player token
per person, header only, routes private for now, browsers never direct-play) and "stop any tv development please".
So: no TV, no `tv.js` / `tv.css`, no TV shell change. TV-mode templates are not touched.

## What is built
- **The page** `GET /media/watch/<item>` (a Jellyfin item id, 32 hex, dashes and upper case accepted). Behind
  `PLAYER_API` (the JY-053 flag, read on every request). Off: every method on `/media/watch` and anything under it answers
  exactly what an unknown path answers (`404 {"detail":"Not Found"}`), never a 405 or a redirect. On: served only on the
  private front to `you` / `her`; anyone else (no Access identity, the media front, a friend) gets the same 404 (the
  media front's ordinary 404 page, through `hub/guest.py` PRIVATE). Only GET (and HEAD) serve the page.
- **Rule 7:** the page render calls nothing live. Title, episode line, year, runtime, rating and the up-next episode come
  from the item read the title / episode page has just cached (`media_item.peek`). A cold cache shows "Jellyfin item" and
  warms the cache after the response (a background task, as the film page's deferred reads do). The player calls the
  API only after the page has loaded.
- **The player** (`hub/static/player.js`), in order: check hls.js can run (`Hls.isSupported()`, true on iOS 17.1+ through
  `ManagedMediaSource`), else say so in words and start nothing; `POST /api/play/sessions` (kind `web` or `phone`, a
  DeviceProfile built from what the browser decodes, `resume: true`); `POST .../stream`; hls.js 1.6.19 loads the HLS URL
  and sends the `Authorization` header on every request through `xhrSetup`, only to the stream's own origin; the token
  stays in a closure (never storage, a cookie, a URL, the DOM, a log or an error); `video.disableRemotePlayback` and
  `x-webkit-airplay="deny"`; never native HLS, never a `<video src>`.
- **Progress:** `POST .../progress` every `heartbeat_s` (10 s) while playing, and at once on pause, play and seek. A
  failed heartbeat is ignored; `404 session_unknown` (hub restart, 30 min idle) starts a new session at the position.
- **Stop:** Back to Joey sends stop (fetch, `keepalive`) then leaves; `pagehide` sends stop with
  `navigator.sendBeacon` (text/plain JSON). One stop per session.
- **Track picker:** the start answer's `tracks`. Changing audio or subtitles stops this session and starts a new one at
  the current position with the new `audio_index` / `subtitle_index` (the contract's way). Image subtitles (PGS, VobSub)
  are labelled "burned in".
- **Resume:** `resume: true` asks the hub for the member's own saved position (see "Outside the area"); when it is used
  the overlay shows "Resumed at 23:41" for 4 s.
- **Look A** (JY-052): full-bleed picture; Back to Joey and the title / meta block (with the play-method word) top left,
  the resume toast top right; the chapter name and time left over the seek bar; the seek bar with buffer, fill, thumb
  and chapter ticks; one row: play/pause, back 10 s, forward 10 s, mute (desktop), the time, "Audio & subtitles",
  fullscreen. Touch screens get the big rewind / play / forward in the middle. Audio & subtitles is a pop-up above the
  row on desktop / iPad and a bottom sheet on a phone (under 600 px wide). The up-next card (an episode with a next
  aired episode) shows in the last 60 s, counts down 8 s after the end and plays it; Watch credits hides it.
- **Keyboard (desktop):** space / k play-pause, Left / Right 10 s, Up / Down volume, f fullscreen, m mute, Escape closes
  the pop-up. Keys on a focused button or the seek slider keep their own meaning.
- **Touch (phone, iPad):** a tap shows or hides the controls; a double tap on the left or right half seeks 10 s back or
  forward. Controls hide after 3 s of playing untouched.
- **The Play switch:** with the flag on, on the private front, for `you` / `her`, every Play / Resume / Next to watch
  link on a title or episode page (the hero buttons and the episode rows) points at `/media/watch/<id>`, opens in the same
  tab and is not htmx-boosted. Off, or anyone else, today's Jellyfin hand-off is unchanged byte for byte. The home
  shelves and the TV-mode episode button are not changed.
- **hls.js** is vendored, not loaded from a CDN: the hub has no CSP today, so a CDN would be allowed, but the page holds a
  member's full Jellyfin token in memory, a third-party script load would be a new privacy exception
  (`docs/connector-contract.md`), and htmx is vendored the same way. `hub/static/hls.min.js` is the npm build of hls.js
  1.6.19, byte for byte (sha256 `72b87a6e58db623feca73ab370970c1126ec06eb3dcd0a67fd14b47b6340b820`), 543,243 bytes,
  163,427 gzipped; Apache-2.0, `hub/static/LICENSE-hls.js.txt`. It loads on the player page only.

## Acceptance criteria
1. Flag off: GET (and every other method) on `/media/watch/<id>`, `/media/watch/<id>/`, `/media/watch` and junk under it
   answers byte for byte what an unknown path answers, for you, her and nobody; no Jellyfin call.
2. Flag on: you and her get the page (200, `no-store`); no Access identity gets the unknown-path 404; a bad id is 404;
   POST is 404, never 405.
3. Media front, flag on: a friend, the household alias and a visitor with no session get the ordinary Joey 404 page.
4. The page render makes no Jellyfin, Seerr or other upstream call; it carries no token, Jellyfin URL or key.
5. Title, episode line and up-next come from the cached item read; a cold cache still renders (200) with neutral words.
6. Play links: flag on + private front + household = `/media/watch/<id>` on the title page, the episode page and the
   episode rows, without `target="_blank"`, with `hx-boost="false"`; flag off = today's Jellyfin deep link, unchanged.
7. JS (node, fake hls.js + fake fetch): start sends kind, profile, `resume: true`; stream; hls.js gets the URL and
   `xhrSetup` sets the header only for the stream origin; progress on the heartbeat and on pause / seek; a
   `session_unknown` heartbeat restarts at the position; Back sends stop once; `pagehide` sends one `sendBeacon` with
   text/plain JSON; no token in any URL, storage or DOM attribute; a track pick stops and restarts at the position with
   the new indexes; unsupported hls.js shows words and starts nothing; native HLS is never used.
8. `resume: true` on the API: the member's position (not played, > 0) becomes `StartTimeTicks` when the player gave
   none, `resumed: true`, chapters returned; a failed read never fails the start. Without `resume`, nothing changes
   (every JY-053 test still passes unchanged).
9. Budgets: the page render p95 <= 50 ms warm (hub page budget), measured with the test client; numbers in the PR.
10. Desktop Chrome and iPhone 15 Pro checks pass on the preview (accept checklist).

## Data
No media.db change, no snapshot change. Reads `media_item`'s in-process item cache only. The API's start gains an
optional `resume` (bool) and always answers `resumed` (bool) and `chapters` (`[{name, start_ticks}]`, at most 100).

## Performance budget
- Hub page render, warm: p95 <= 50 ms for `/media/watch/<id>` (cache only). Measured in `tests/hub/test_player_page.py`.
- Press to first frame: 5 s LAN, 10 s remote (JY-050 Q8 A), measured on the devices in the accept window, flag on.
- joey-hub memory: unchanged (no new cache; the player is in the browser).
- Page weight: `hls.min.js` 163 KB gzipped, cached a year by `?v=`; `player.js` and `player.css` sizes in the PR.

## Options and the pick
`JoeyTV/review/JY-052-player-options.html`, option A "Classic overlay". B., 2026-10-27: "JY-052: A".
JY-053's four questions: B., 2026-10-27: "JY-053: A A A A". Scope: B., 2026-10-27: "stop any tv development please".

## Outside the area
- `hub/player_api.py` and `docs/playback-contract.md` (JY-053's): the additive `resume` option. Jellyfin's PlaybackInfo
  does not resume by itself, and the hub's item cache holds B.'s watch state only, so `her` would resume at B.'s point.
  With `resume: true` the start reads `GET /Users/{uid}/Items/{id}?Fields=Chapters` with the member's own token first
  (2 s / 2 s), so each member resumes at their own point and the chapter ticks need no other read. Off the flag nothing
  changes; without `resume` the start is exactly JY-053's.
- `hub/media_film.py` / `media_film.html`: the Play href switch only.

## Out of scope
The TV (JY-057, stopped: "stop any tv development please"); friends (JY-058); iOS below 17.1 and AirPlay (JY-053 Q4 B);
offline; casting; the transcode box. JY-055 (resume across devices) and JY-056 (track picker) keep their rows: this item
builds the basic resume and picker the brief asks for; anything more stays with them.
Not built here: the script that makes `JELLYFIN_PLAYER_TOKEN_YOU` / `_HER` with a Quick Connect code (JY-053 Q1 A). See
the questions.

## Accept checklist
Hands first (one state window, on the preview, the flag on there only):
- JY-014's `preview.joeyhome.net` hostname exists; the preview runs this branch with `PLAYER_API=on` and the two player
  tokens set in its env (never in a commit or a chat).

Desktop Chrome (PC on the LAN):
- [ ] A film page's Play opens `/media/watch/...` in the same tab; the picture starts within 5 s; the method word shows.
  Record the "First frame N s after Play" line under the title (time from the Play press, this page's navigation).
- [ ] Space, Left / Right, Up / Down, f and m do what they say; the seek bar shows chapter ticks where the file has chapters.
- [ ] Audio & subtitles lists the tracks; picking one carries on at the same point with the new track.
- [ ] Stop half way with Back to Joey; Play again shows "Resumed at ..." within 10 s of that point.
- [ ] An episode near its end shows the up-next card; it plays the next episode after the countdown.
- [ ] With the flag off on the preview, Play goes to Jellyfin as today and `/media/watch/...` is a 404.

iPhone 15 Pro (Safari, then the Home Screen app), needs JY-014's preview hostname:
- [ ] Play starts within 5 s on Wi-Fi and 10 s on mobile data (record the "First frame N s after Play" line each time); no AirPlay button.
- [ ] Tap shows / hides the controls; double tap left / right seeks 10 s.
- [ ] Audio & subtitles opens as a bottom sheet; a text subtitle shows; rotation and fullscreen work.
- [ ] Close the app mid-film; the position on the PC is within 10 s of it (the beacon or the last heartbeat).

## Questions for B.
**1. The player tokens.** JY-053 Q1 A said JY-054 makes `JELLYFIN_PLAYER_TOKEN_YOU` / `_HER` with a script that signs a
"Joey player" device in by a Quick Connect code you approve. A) A separate small item for the script (it touches Jellyfin
sign-in, a live write); this PR stays flag-off code. B) Add it to this PR. C) Make the two tokens by hand in Jellyfin's
dashboard (API keys are admin-only, so a Quick Connect sign-in is still needed). *Recommend A: it keeps this PR free of
live calls, and the accept window needs it only once.*

## Review round 1 (2026-10-27)
Both reviews passed. Should-fixes made: `Referrer-Policy: no-referrer` header and meta tag
(`test_the_page_sends_no_referrer`); `mount()` driven under node on a fake DOM (resume toast, chapter ticks, up-next,
`disableRemotePlayback` before hls.js attaches); a "First frame N s after Play" line (performance.now() at the first
`playing`, no token) for the device checks; a page restored from the back-forward cache destroys hls.js and starts a
fresh session at its position. Nits: one countdown at most, the up-next card hides again after seeking back, the
retry / recovery allowance resets once playing again, the right mouse button never toggles play.

## Opus verifier (2026-10-27)
Must-fix: with the flag off, TRACE, PROPFIND and made-up methods on `/media/watch*` (and JY-053's `/api/play*`) answered
405 with an Allow header. Fixed with `player_api.FlagOffRoute`, registered first in the router: off, any method on either
prefix raises the router's own 404 (byte for byte the unknown path's); on, it never matches. Red first:
`tests/hub/test_player_flag_methods.py` failed 3 of 6 before the fix. Nit: Watch credits clears the countdown to null.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #215, squash-merged as `f4d8c95` (f4d8c95b9bf0136f6219229d1346086b58c061c2).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
