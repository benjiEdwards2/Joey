# JY-307 TV UI overhaul, phase 5: the player overlay (option B)

Status: spec (draft 2026-11-06)
Size: M
Live risk: TV release (1.0.4 -> 1.0.5, `tv/` via the release runbook) plus an additive hub field; no NAS write
Area: `tv/app/src/main/res/layout/activity_player.xml`, `res/values/{dimens,styles,strings,colors}.xml`, `res/drawable/player_*` (+ new icon vectors), `PlayerActivity.kt`, `PlayerBar.kt`, `policy/PlayerUi.kt`, `policy/PlayerSupport.kt` (`PlayerText`), `policy/PlayerApi.kt`; hub: `hub/media_watch.py` (`up_next`), `hub/player_api.py` (start answer); tests below
Needs: JY-307 P1-P4 (live 6956375). JY-057 player (TV 1.0.4, JY-259 P4 restyle #271).
Options page: https://claude.ai/artifact/LSg1DfpC5fusr2Mm59kXMC (B.: "TV ui: Prefer option B.")

## Problem
Phasing table row 5 (option B): "Player overlay restyle in `tv/` (`activity_player.xml`, dimens, PlayerUi), TV release". Option B's player as mocked: "a left-aligned title block over a bottom gradient, a thin bar, and icon-only buttons under it with labels on focus. Up next becomes a 16:9 tile bottom-right"; what stays: "The ExoPlayer activity, the keys (KeyPolicy), Back -> title page".
Today the overlay is still JY-259 P4's look A at the pre-P2b scale: P2b made every browse page 25 % smaller (B.: "Seems too zoomed in"), the player was not touched, so it is now the one screen that still looks zoomed in. Title top-left on its own top scrim, a 64 px title, a diagnostic method line, five 112 px text chips, a resume card top-right, and an up-next card with a blank tile (no picture).

## What the code does today
- **Layout** (`activity_player.xml`): `player_top` (title + `player_meta` over `player_scrim_top`), `player_resumed` card top-right, `player_bottom` (chapter left + `progress` time right, `PlayerBar`, a row of five `JoeyPlayerChip` text buttons: Pause, Back 10 s, Forward 30 s, Audio & subtitles, Next episode), `player_popup` (two 360 dp columns), `player_upnext` (200 dp 16:9 `player_tile` with only the label, runtime or countdown, Play now / Watch credits stacked).
- **Sizes** (`dimens.xml`, 1 dp = 2 px at 1080 on the TCL's 960x540 dp): overscan 48/27 dp, title 32 sp (64 px), method + chips + floor 18 sp (36 px), buttons 56 dp (112 px), bar 40 dp tall with a 7 dp track (`PlayerBar.onDraw`), pop-up rows 56 dp (`rowHeight()`). The web root is now 24 px/rem at 1080 (tv.css P2b), so 3.5rem controls are 84 px there, not 112.
- **Words** (`PlayerText`): title = the WebView page title minus " · Joey" (`pageTitle`); meta = "Direct play · First frame 1.2 s after Play"; time "42:10 / 1:58:00"; `resumed()` "Resumed at 42:10" for `RESUMED_SHOW_MS` 4 s; countdown "Next episode in 8 s". No episode line (S/E) on the player: the start answer carries no title fields.
- **States and keys** (`PlayerUi`): `NONE / CONTROLS / POPUP / UP_NEXT`; hidden: Left/Right seek -10/+30 s and show the bar row, OK shows the buttons on Play/Pause, other keys show the bar; bar row: Left/Right seek, OK toggles, Down to buttons; buttons row: Left/Right move, Up to bar, OK presses; pop-up: Up/Down walk, Left/Right swap columns, OK picks (stays open); Back closes pop-up -> hides controls -> returns to Joey (`BackPolicy.player`). Media keys handled in `media()`.
- **Timing**: `HIDE_AFTER_MS` 5 s while playing (never while paused or in the pop-up); up-next card in the last `UP_NEXT_LEAD_MS` 60 s while controls are hidden; `COUNTDOWN_MS` 8 s at the end.
- **Hub**: `player_api.py` start answer `up_next` = `media_watch.up_next()` -> `{item_id, label, runtime}` from the item cache only. The cached episode rows already hold `still: "jf:<id>"` (`media_item.py`), and `media_watch.page_data()` already builds `title` + `line` ("S2 · E5 · Name") for the web overlay; neither reaches the TV.

## Change
1. **Scale to P2b.** Every player size x 0.75 so it matches the browse pages (px at 1920x1080, dp/sp = px / 2): margins 72 x 40 px (= `--tv-mx` 3rem, `--tv-my`); corners 12 px (`--tv-r`); focus ring 6 px white. Text: eyebrow 27 px amber uppercase, title 48 px, line/meta/time/chapter 27 px, button labels and pop-up rows 30 px (`--tv-fs-label`). Floor: nothing under 27 px (1.125rem at 24 px/rem), never under the 18 px hard floor.
2. **One bottom block, no top scrim.** Remove `player_top` and `player_scrim_top`; the bottom gradient grows to ~45 % of the height. Left-aligned, bottom up: buttons row, bar, time line (chapter left, time right), then the title block: eyebrow (episode: "S2 · E5"; film: year · runtime), title (show or film, one line, max 1100 px, ellipsis), line (episode name). Words come from the hub (step 6), falling back to today's `pageTitle`.
3. **Thin bar.** Track 8 px (was 14), thumb 16 px, focused thumb 24 px with the 6 px ring on the thumb only (no ring round the whole bar); chapter ticks 2 px. Bar row 48 px.
4. **Icon buttons, label on focus.** Five 84 px round icon buttons (icons 40 px, new vector drawables: play/pause, back 10, forward 30, audio & subtitles, next); the focused one turns white, ink icon, and widens into a pill showing its label (30 px). Same five actions and order; Next hidden when there is no next episode.
5. **Resume words.** The top-right card goes; for 4 s after a resumed start the line under the title reads "Resumed from 42:10 · 1h 16m left" (`PlayerText.resumed(startMs, durationMs)`), and the controls show for those 4 s.
6. **Next episode card.** Bottom right, 400 x 225 px 16:9 tile with the next episode's still, "Up next" eyebrow, label 30 px, runtime or "Next episode in 8 s" 27 px, Play now / Watch credits chips (72 px) side by side under it. Hub (additive, cache only): `up_next` gains `still` (the cached `jf:<id>` ref) and the start answer gains `title`, `line` from `page_data()`; the shell loads the still once through the existing `/img` proxy at the P1 16:9 height (`h=225`) when the card first opens, plain tile if it fails. Timing unchanged (last 60 s, 8 s countdown).
7. **Pop-up** on the same tokens: two 540 px columns, 84 px rows, max 6 rows, the tick on the playing track.
8. **Auto-hide and keys.** Timings unchanged (5 s playing; never while paused or in the pop-up); controls fade in/out in 150 ms. Key map unchanged (option B keeps the keys) except: Left/Right on the buttons row walk the icon buttons as today, and the label follows focus. `PlayerUi` stays pure; only `PlayerText` and the render code change.

## Acceptance criteria
1. Device shots on the TCL (1920x1080 `screencap`) of: controls on a film, controls on an episode (eyebrow S/E, title, episode name), each button focused (label pill), bar focused, the pop-up with 8+ subtitle tracks, the resumed line, the up-next card with its still, the end countdown. Each matches the step sizes within +/- 2 px.
2. Player audit (new `tv/tools/player_audit.py`, the P1-P4 audit's JSON keys: `tiny`, `outside`, `focus`): `uiautomator dump` bounds give no text view under 27 px tall, nothing outside the 72 x 40 px margins, exactly one focused element per state; plus the static floor test in item Tests.
3. D-pad drill unchanged: hidden Left/Right seek and show the bar; Down/Up between bar and buttons; pop-up Up/Down/Left/Right/OK; Back closes pop-up -> hides -> returns to the title page; media keys as today.
4. Auto-hide 5 s +/- 0.5 s while playing; stays while paused and in the pop-up; up-next card appears at 60 s left only while hidden; countdown plays the next episode at 8 s.
5. A film shows no Next button and no card; a cold cache shows today's page title and a plain up-next tile, never a blank title or a crash.
6. `tests/hub` + CI `tv` (JVM tests, `check_apk.sh`) green; full tree passes; release runbook drill passes on the TCL.

## Performance budget
- Overlay appears <= 100 ms after a key; >= 50 fps through the fade over 1080p HEVC (no dropped-frame burst in `gfxinfo`).
- Up-next still: one request per episode, decoded at 400x225 (<= 0.5 MB bitmap), on screen <= 1 s after the card opens on the LAN.
- Start answer p95 unchanged (two dict reads from the item cache, no Jellyfin call); no new network call during playback besides the one still.
- APK grows <= 50 KB (vector icons only; no font, no image library).

## Out of scope
Anything needing a new upstream call (episode synopsis, trickplay/scrub thumbnails, skip-intro markers, ratings); Geist in the shell (JY-259 P4 follow-up); option C's minimal overlay; seek acceleration or long-press; the web/phone player (`player.css`/`player.js`); friends' player (JY-058); casting.

## Tests to add/change
- `tv/app/src/test/.../policy/PlayerUiTest.kt`: key map and timings pinned unchanged; resumed-start shows controls for 4 s.
- `tv/app/src/test/.../policy/PlayerSupportTest.kt`: `PlayerText.resumed(startMs, durationMs)`, eyebrow words (episode / film / missing fields).
- `tv/app/src/test/.../policy/PlayerApiTest.kt`: `parseStart` reads `title`, `line`, `up_next.still`; old answers (missing fields) still parse.
- `tests/tv/test_player_dimens.py` (new): parses `dimens.xml`, `styles.xml`, `activity_player.xml`; every text size >= 13.5 sp (27 px), buttons 42 dp, margins 36/20 dp, no `player_scrim_top`.
- `tests/hub/test_tv_player_front.py`: start answer carries `title`, `line`, `up_next.still` from the cache with no extra Jellyfin call; null for a cold cache.

## Questions for B.
1. **Resume words**: "Resumed from 42:10 · 1h 16m left" for 4 s? *Default: yes, as written.*
2. **Time line**: elapsed / total ("42:10 / 1:58:00") or time left ("-1:15:50")? *Default: elapsed / total, as today.*
3. **Diagnostic line** ("Direct play · First frame 1.2 s"): keep it on the overlay? *Default: show it only while paused, 27 px muted, end of the time line.*
4. **OK while hidden**: show the controls (today) or pause at once? *Default: show the controls, as today.*

## Shipped notes
