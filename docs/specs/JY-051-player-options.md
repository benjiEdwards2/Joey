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

## Study harness (round 2, 2026-10-24)
Built on this branch; nothing here has touched Jellyfin or the TV except the read-only PC PlaybackInfo table
(`JY-051-inventory.md`, API key + joeytest `userId`, which 12.2 accepts).

| Part | Where | What it does |
|---|---|---|
| Study page | `hub/static/jy051/study.html` | W1 (`<video>` on `/Videos/{id}/stream?static=true`) and W2 (`<video>` + hls.js 1.5.17 on the HLS `TranscodingUrl`, PlaybackInfo with a DeviceProfile built from what this browser decodes, direct play off). Play on a row runs W1 then W2, 3 timed runs each, press to first frame (`requestVideoFrameCallback`, else the `playing` event), audio-decoded check, track and subtitle method. Stops each run's transcode at once (`DELETE /Videos/ActiveEncodings` for its own PlaySessionId) so the J4125 never holds two. Results: a JSON block with "Copy results"; resume check for row 1. |
| Joey Study app | `docs/joeyv2/research/jy051/android/` (package `net.joeyhome.study`, debug only) | Sign-in screen (joeytest), then T1 (the same page in a WebView, from the APK's assets), T2 (Media3 1.9.0 ExoPlayer on the direct file, Authorization header, no key in the URL), T2F (T2 + FFmpeg audio decoders, extension mode ON = platform first), T2H (ExoPlayer on Jellyfin HLS, only for files T2/T2F could not play or decode audio for). One logcat line per run (tag JY051): first rendered frame, decoders, selected audio/text track and whether supported, B.'s OK/Back verdict on rows 6, 7, 8, 11, 12. Then the resume test (row 1 with progress reports) and sign-out. |
| APK build | `.github/workflows/jy051-study.yml` | Separate debug workflow on pushes to `feat/JY-051-*` touching the app, the page or itself: JVM tests, `assembleDebug`, APK facts, the `tv_version.py` secret scan, artifact `joey-study-apk`. No tv/ files, no tv/VERSION, no signing secrets, no release job. |
| Runner | `scripts/jy051_sitting.py` | `fetch-apk`, `check`, `install`, `tv` (launch, collect logcat until the app signs out), `resume-tv`, `ingest` (pasted page results), `matrix` (fills `docs/specs/JY-051-matrix.md` between its markers), `uninstall`, `sitting`. `--dry-run` on all. Handles no credential. |

**FFmpeg extension (acceptance 5):** practical in Actions with no NDK build: Jellyfin publishes the prebuilt Media3
FFmpeg decoder on Maven Central (`org.jellyfin.media3:media3-ffmpeg-decoder:1.9.0+1`, built against Media3 1.9.0; the
same artefact Jellyfin's Android TV app ships). Cost: `libffmpegJNI.so` 1.36 MB (armeabi-v7a) to 1.55 MB (x86_64)
uncompressed per ABI, 2.9 MB AAR for all four; the study APK is 18.8 MB with all ABIs. Licence: the POM declares
GPL-3.0, so shipping it in Joey TV would put the distributed APK under GPL-3.0 terms (source offer to anyone given
the APK, friends included). First green build: run 40047690121.

**Where the study page is served, and why (decided 2026-10-24).** From the JY-012 preview slot:
`https://preview.joeyhome.net/static/jy051/study.html` (`python scripts/joey.py preview up 70`), behind Cloudflare
Access, once JY-014 adds the hostname. The page itself comes through the tunnel; every Jellyfin call and every video
byte goes straight to `https://jellyfin.joeyhome.net:8443`. The TV loads the same file from the APK (T1).
- A claude.ai artifact cannot do it: its CSP blocks fetch and media to every host but the script CDNs, so it could
  never reach the :8443 edge.
- The laptop cannot serve to the LAN (firewall), so the phone cannot open a laptop page.
- The preview slot is the one https origin on Joey's side the phone can open that needs nothing new.
- CORS: `deploy/swag/proxy-confs/jellyfin.subdomain.conf` neither adds nor strips CORS headers, so the answer is
  Jellyfin's own (server setting CORS hosts, default any origin). Not probed live this round; the page's first check
  (`GET /System/Info/Public`, anonymous) says in words if CORS or the geo gate (AU/NZ/LAN only) refuses it.
- PC fallback if the preview is not up: open `hub/static/jy051/study.html` from disk (origin null, same CORS answer).
  The phone has no fallback: its legs need the preview hostname.
- Outside this item's area (rule 5): `hub/static/jy051/` sits in the shipped hub tree because the preview serves only
  the hub image. It is a throwaway: remove it before merge (on main it would also be public on the guest front, where
  `/static` is open; it holds no secret, but it should not ship).

**Sign-in (B., 2026-10-24: joeytest).** The page and the app sign in with what B. types (AuthenticateByName); the
session token stays in memory, nothing about it is stored, printed or logged, and both sign out at the end (frees
joeytest's session slot; joeytest itself is never changed). The admin key never reaches the page, the app or the TV.
A stable per-device DeviceId means repeated sign-ins reuse one Jellyfin device entry.

## Hands bundle: one TV + phone sitting (2026-10-24, joeytest)
At most 35 minutes, one sitting, one state window (TV awake on the LAN, preview slot up). Files: the 12 in
`docs/specs/JY-051-inventory.md` ("Test-file set"). Claude drives the scripts; B. signs in, presses Play and says what
he sees. Account: joeytest (friend policy: remote capped at 20 Mbps, LAN unaffected; the remote rows 1, 2, 4 are
2 to 6.6 Mbps, under the cap).

**Before the sitting**
1. B.: the JY-014 hands item (add `preview.joeyhome.net` to the tunnel and the existing Access application), if not
   already done.
2. B.: tell Claude your phone (Android + Chrome, or iPhone + Safari): it changes what P1 can play.
3. Claude, no hands: `python scripts/jy051_sitting.py fetch-apk`, `python scripts/joey.py preview up 70`, then send the
   link `https://preview.joeyhome.net/static/jy051/study.html`.

**The sitting**
| Min | Where | What B. does | What is recorded |
|---|---|---|---|
| 0-2 | TV | Press the remote's power button, wait for the home screen. Say "TV awake". | Claude: `jy051_sitting.py check` then `install`. |
| 2-10 | PC | Open the link, type joeytest and its password, Sign in. Press "Play every row" (or Play per row); each row plays W1 then W2, 3 runs each, and holds the last run 6 s: for rows 4, 6, 7, 9, 12 say whether picture, sound and subtitles look right. Then open rows 2 and 7 in Jellyfin web (W3) once each. Copy results, paste into the chat, press Sign out. | First-frame median per file and engine, play method, audio decoded, subtitle method. |
| 10-17 | Phone, Wi-Fi | Open the link, Add to Home screen, open it from there, sign in as joeytest. Play rows 1 to 6. Rotate once and go full screen on row 2. | LAN first frame, fullscreen and rotation, HEVC on the phone. |
| 17-20 | Phone, mobile data | Wi-Fi off, set Network to Remote, play rows 1, 2 and 4. Network back to LAN, Wi-Fi on. Stay signed in. | Remote first frame (the 10 s budget), one transcode remotely. |
| 20-31 | TV | Claude runs `jy051_sitting.py tv`; "Joey Study" opens on its sign-in screen: type joeytest and the password with the remote, Sign in. It then plays each file under T1 (WebView), T2 (ExoPlayer), T2F (ExoPlayer + FFmpeg) and T2H where needed, timing itself. On rows 6, 7, 8, 11, 12 it asks: OK if picture and sound are right, Back if not. When it says "Matrix done", press OK for the resume test: press right on the progress bar until about 5:00 (30 s per press), then Back. Then open rows 1 and 7 in the Jellyfin app (T3). | logcat first frame per file per engine, decoders, track support, your OK/Back, the stop position. |
| 31-33 | Phone | On the study page press "Read saved position and resume". Then Copy results, paste into the chat, Sign out. | Resume across devices (within 10 s of the TV's stop). |

**After (Claude, no hands):** `jy051_sitting.py uninstall`; save the pasted results and `ingest` them; `matrix`; read
NAS CPU and available RAM for the transcode rows (must stay at or above 1,200 MB); `preview down`. joeytest stays as
it is (JY-040 owns it).

Test pin re-pointed 2026-10-24 (joeytest change): `tests/scripts/test_player_study.py::test_playback_needs_a_token_file` became `test_playback_without_a_token_file_uses_the_api_key_and_user_prefix`, because playback now runs with the API key + joeytest `userId` and a token file is optional; no token crosses ssh on that path.

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
