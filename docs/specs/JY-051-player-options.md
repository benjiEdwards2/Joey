# JY-051 Player options study (per-device matrix)

Status: building
Size: M
Live risk: none (read-only playback tests against Jellyfin with a test account)
Area: `docs/joeyv2/research/` (the study write-up), a throwaway test harness outside the repo's shipped code
Needs: JY-050 (ready)
Options page: the study is the options page; JY-052 designs the screen after it.

## Problem
B. wants Joey's own player on every device, replacing the Jellyfin-app hand-off, and wants the options investigated (he has seen ffmpeg, Jellyfin and ExoPlayer) before choosing. JY-050 fixed the scope: household only; PC browser, phone, then the TCL Google TV via the Joey TV Kotlin shell; direct play, then remux, then transcode; Jellyfin is the resume record; start within 5 s on the LAN, 10 s remote. This item picks one approach per device from measured evidence.

## Candidates per device
Anything not certain is marked "to verify in the study" (V).

**PC browser**
- **W1. Native `<video>` on a direct stream URL** (`/Videos/{id}/stream?static=true`). Simplest; plays only what the browser supports (HEVC and AV1 vary, V).
- **W2. `<video>` + hls.js on Jellyfin's HLS** (`/Videos/{id}/master.m3u8`). What Jellyfin's own web client does; covers remux and transcode. Needs a DeviceProfile in PlaybackInfo (V).
- **W3. Jellyfin's own web client** (deep link, as today). The baseline.

**Phone**
- **P1. Same web player (W1/W2) as an installed PWA.** One code path with the PC; fullscreen, orientation and phone HEVC support to verify (V).
- **P2. Native player in an app.** Better codec reach but needs an app and distribution; paper study only unless P1 fails.

**TV shell (TCL Google TV, Android 14, WebView)**
- **T1. HTML5 `<video>` inside the WebView** (W1/W2 reused). No native work, but WebView codec reach and HDR are unknown (V), and the shell's media-key handling must change.
- **T2. Media3 ExoPlayer in the Kotlin shell**, fed Jellyfin direct or HLS URLs; with and without the ffmpeg decoder extension (software DTS/TrueHD; build and licence cost V). Same engine as Jellyfin's Android TV app.
- **T3. Keep the hand-off** to the Jellyfin app (today; passed 12/12 on the TCL). The control.
- **T4. libVLC or mpv** (broadest codec reach, heavier, native libs). Test only if T2 fails a test file.

## What each needs from Jellyfin
- `POST /Items/{id}/PlaybackInfo` with a DeviceProfile: returns MediaSources, the play method (DirectPlay / DirectStream / Transcode) and a TranscodingUrl. (Shape on 12.2: V.)
- Direct: `/Videos/{id}/stream?static=true&MediaSourceId=...`. HLS: `/Videos/{id}/master.m3u8` with bitrate and track-index parameters (V).
- Progress: `/Sessions/Playing`, `/Sessions/Playing/Progress`, `/Sessions/Playing/Stopped`, so resume stays in Jellyfin (needed for JY-055).
- Auth: `Authorization: MediaBrowser Client=..., Token="..."` only (12.2 rejects the old headers). Streams go to `jellyfin.joeyhome.net:8443`, never the Cloudflare tunnel.

## Test-file set
From what the library really has. List it read-only with the test account: `GET /Items?Recursive=true&IncludeItemTypes=Movie,Episode&Fields=MediaSources,MediaStreams` (paged; first-touch queries are slow on 12.2), then group by video codec (H.264, HEVC 8/10-bit, AV1), HDR (SDR, HDR10, Dolby Vision), container, audio (AAC, AC3/EAC3, DTS, TrueHD) and subtitle type (SRT, PGS, ASS). Pick 5 to 8 files, one per combination that exists, including an H.264+AAC MP4 control, HEVC 10-bit HDR, AV1 if present, DTS or TrueHD, PGS and ASS, and one multi-audio file. Record sizes and bitrates. A missing combination is reported, not imported.

## Measurement method
Same procedure per device, per file, per network (LAN, then remote on mobile data or outside Wi-Fi):
1. **Outcome:** direct play, remux or transcode, read from PlaybackInfo and Jellyfin's Dashboard session.
2. **Time to first frame:** Play press to first frame, 3 runs, median. Browser and phone: `performance.now()` from click to the `playing` event. TV: logcat timestamps from the test build.
3. **Tracks:** every audio and subtitle track selectable; burn-in vs sidecar noted.
4. **Resume:** stop at a known position, resume on another device within 10 s of it.
5. **NAS load** during one transcode: CPU, available RAM (must stay at or above 1,200 MB) and stream bitrate against the cap, via the NAS dashboard.

## Acceptance criteria
1. The test-file list is written, with the Jellyfin query used.
2. A filled matrix: device x candidate x file -> outcome, first-frame time on LAN and remote, tracks, resume, with every V above resolved or marked unsupported.
3. A recommendation per device (PC, phone, TV) with the reason, and what JY-053 (contract) needs from it.
4. No write beyond the test account's own playback progress.
5. ffmpeg-extension size and licence cost recorded if T2 is carried forward.

## Needs B.'s hands (one TV window)
One sitting: install the throwaway test APK on the TCL by adb (as in `tv/README.md`), play every test file under T1, T2 and T3 in one pass, uninstall. Phone and PC need a short session with the test account. Wake the TCL first (deep standby drops it off the LAN).

## Hands bundle: one TV + phone sitting (draft, 2026-10-24)
At most 30 minutes, one sitting, one state window (TV awake on the LAN, study account live). Files: the 12 in
`docs/specs/JY-051-inventory.md` ("Test-file set"). Claude drives the timing; B. presses Play and says what he sees.

**Before the sitting (B., about 5 minutes, any time earlier)**
1. Jellyfin web (`jellyfin.<domain>:8443`) > Dashboard > Users > + : user `joeystudy`, a password of your choice, Library access: all libraries; Features: allow media playback, allow video transcoding and remuxing; no admin, no deletion, no downloads. Save.
2. Sign in as `joeystudy` in a private Chrome window. Press F12 > Console, type `ApiClient.accessToken()` and Enter. Copy the 32-character value into a new file `C:\Users\b.edwards\.joey\jy051_token.txt` (outside the repo). Close the window without signing out (signing out kills the token).
3. Tell Claude "study account ready". Claude then runs the PC PlaybackInfo table (`scripts/player_study.py playback --token-file ...`) and builds the test page and test APK. Nothing else is needed from you until the sitting.
4. Tell Claude your phone (Android + Chrome, or iPhone + Safari): it changes what P1 can play.

**The sitting**
| Min | Where | What B. does | What is recorded |
|---|---|---|---|
| 0-2 | TV | Press the remote's power button, wait for the home screen. Say "TV awake". | Claude checks adb sees the TV, installs the test APK. |
| 2-9 | PC | Open the study page link (sent before). Press Play on each of the 12 rows; the page plays W1 then W2 and times click to first frame 3 times by itself. For rows 4, 6, 7, 9, 12 say whether picture, sound and subtitles look right. Then open row 2 and row 7 in Jellyfin web (W3) once each. | First-frame median per file and engine; play method from PlaybackInfo and the Dashboard session. |
| 9-16 | Phone, Wi-Fi | Open the same link, Add to Home screen, open it from there. Run rows 1, 2, 3, 4, 5, 6 (auto-timed). Rotate once and go full screen on row 2. | LAN first frame, fullscreen and rotation, HEVC on the phone. |
| 16-19 | Phone, mobile data | Turn Wi-Fi off. Run rows 1, 2 and 4. Turn Wi-Fi back on. | Remote first frame (the 10 s budget), one transcode remotely. |
| 19-28 | TV | Open "Joey Study" from the apps row. It plays each file for 10 s under T1 (WebView), then T2 (ExoPlayer), then T2 + ffmpeg, timing itself. Watch rows 6, 7, 8, 11, 12 and press OK if picture and sound are right, Back if not. Then open rows 1 and 7 in the Jellyfin app (T3). | logcat first-frame per file per engine; your OK/Back per hard file. |
| 28-30 | TV, then phone | Stop row 1 on the TV at about 5:00. Open row 1 on the phone and check it offers to resume within 10 s of 5:00. | Resume across devices. |

**After (Claude, no hands):** uninstall the test APK by adb; read NAS CPU and available RAM logged during the transcode rows (must stay at or above 1,200 MB); fill the matrix. Delete `joeystudy` and the token file once B. accepts the study (B. clicks Dashboard > Users > joeystudy > Delete, or OKs Claude doing it by API).

## Out of scope
Choosing the screen's look (JY-052); the hub playback endpoints (JY-053); any shipped player or signed release; friends' devices, downloads, casting; the transcode box (JY-049/059: transcode numbers here are J4125 worst case); library, arr or Seerr changes.

## Questions for B.
Answers: B., orchestrator session, 2026-10-24: "JY-051: 1A 2A 3A, ready".
Change to answer 2 (B., 2026-10-24): "Could you just use joeytest instead of study?" → the study uses the existing `joeytest` user (id prefix 0dd9fd89, ENABLED until the JY-040 revoke drill; never toggled here), not a new `joeystudy` user. Its friend policy caps remote streams at 20 Mbps (LAN unaffected), which matches the friend case.
**1. TV engines in the study?** A) T1, T2 (with and without ffmpeg extension) and T3; T4 only if T2 fails a file. B) Also test libVLC and mpv up front. *Recommend A: it keeps the TV sitting short, and Jellyfin's own app already uses ExoPlayer.*

**2. Test account?** A) A new read-only household-policy Jellyfin user made for the study, deleted afterwards. B) Use your own account (progress writes land on your history). *Recommend A: stops test plays polluting your resume and watched records.*

**3. Transcode numbers before the box?** A) Measure on the NAS now, and flag them as a worst case. B) Wait for the box. *Recommend A: the player must work on direct play without it, and the J4125 baseline is useful.*

## Shipped notes
Not yet.
