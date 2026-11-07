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
2. Phone: answered, B., 2026-10-26: "My phone type is an iphone 15 pro." So P1 runs on iOS Safari/WebKit (A17 Pro); see "iPhone 15 Pro" below. hls.js needs iOS 17.1 or later (ManagedMediaSource); on older iOS the page falls back to native HLS.
3. Claude, no hands: `python scripts/jy051_sitting.py fetch-apk`, `python scripts/joey.py preview up 70`, then send the
   link `https://preview.joeyhome.net/static/jy051/study.html`.

**The sitting**
| Min | Where | What B. does | What is recorded |
|---|---|---|---|
| 0-2 | TV | Press the remote's power button, wait for the home screen. Say "TV awake". | Claude: `jy051_sitting.py check` then `install`. |
| 2-10 | PC | Open the link, type joeytest and its password, Sign in. Press "Play every row" (or Play per row); each row plays W1 then W2, 3 runs each, and holds the last run 6 s: for rows 4, 6, 7, 9, 12 say whether picture, sound and subtitles look right. Then open rows 2 and 7 in Jellyfin web (W3) once each. Copy results, paste into the chat, press Sign out. | First-frame median per file and engine, play method, audio decoded, subtitle method. |
| 10-17 | iPhone 15 Pro, Wi-Fi | Safari: open the link, Share > Add to Home Screen, open it from the Home Screen icon, sign in as joeytest. Play the six iPhone rows (script in "iPhone 15 Pro" below). | LAN first frame, seeking, HDR, subtitles, fullscreen and rotation. |
| 17-20 | iPhone, mobile data | Wi-Fi off, set Network to Remote, play rows 1, 2 and 4. Network back to LAN, Wi-Fi on. Stay signed in. | Remote first frame (the 10 s budget), one transcode remotely. |
| 20-31 | TV | Claude runs `jy051_sitting.py tv`; "Joey Study" opens on its sign-in screen: type joeytest and the password with the remote, Sign in. It then plays each file under T1 (WebView), T2 (ExoPlayer), T2F (ExoPlayer + FFmpeg) and T2H where needed, timing itself. On rows 6, 7, 8, 11, 12 it asks: OK if picture and sound are right, Back if not. When it says "Matrix done", press OK for the resume test: press right on the progress bar until about 5:00 (30 s per press), then Back. Then open rows 1 and 7 in the Jellyfin app (T3). | logcat first frame per file per engine, decoders, track support, your OK/Back, the stop position. |
| 31-33 | Phone | On the study page press "Read saved position and resume". Then Copy results, paste into the chat, Sign out. | Resume across devices (within 10 s of the TV's stop). |

**After (Claude, no hands):** `jy051_sitting.py uninstall`; save the pasted results and `ingest` them; `matrix`; read
NAS CPU and available RAM for the transcode rows (must stay at or above 1,200 MB); `preview down`. joeytest stays as
it is (JY-040 owns it).

Test pin re-pointed 2026-10-24 (joeytest change): `tests/scripts/test_player_study.py::test_playback_needs_a_token_file` became `test_playback_without_a_token_file_uses_the_api_key_and_user_prefix`, because playback now runs with the API key + joeytest `userId` and a token file is optional; no token crosses ssh on that path.

## iPhone 15 Pro (B., 2026-10-26)
B., 2026-10-26: "My phone type is an iphone 15 pro." (iOS 17/18, Safari/WebKit, Apple A17 Pro.) P1 (the web player as a Home Screen app) is
tested on this phone. iOS WebKit is the only engine on an iPhone: every iPhone browser, Chrome included, is WebKit underneath.

Source key (here and in `docs/specs/JY-051-matrix.md`): **M** = measured by this study (library inventory 2026-10-24, PC PlaybackInfo
2026-10-24); **D** = from Apple, WebKit or Jellyfin documentation, not tested on this phone; **V** = to verify in the sitting.
Nothing about the iPhone itself is M yet: every decode and play-method statement below is D until the sitting.

**Capability column, iPhone 15 Pro** (all devices side by side: `docs/specs/JY-051-matrix.md`)
| Area | iPhone 15 Pro | Source |
|---|---|---|
| Containers, direct | MP4, MOV; HLS with fMP4 or TS segments. MKV does not play in Safari: it needs a remux to HLS (Jellyfin does this, video and audio copied). | D |
| H.264 | Hardware; 8-bit High profile. | D |
| HEVC | Hardware, Main and Main 10, including 10-bit SDR and HDR10. In MP4 it needs the `hvc1` tag; an `hev1`-tagged file may not play. | D, tag V |
| Dolby Vision | Profile 5 and 8.1 in HLS and MP4, on the phone's HDR display. A DV 8.1 file carries an HDR10 base layer. | D, V |
| AV1 | Hardware decode on A17 Pro (the first Apple phone with it); Safari 17+ enables AV1 only where hardware decode exists. About 85 % sure: Apple's HLS mailing-list note and a vendor compatibility table say so, and I found no WebKit status page. The library has 0 AV1 items, so it changes no count. | D |
| VP9 | Do not plan on it: iOS Safari support is partial, software or limited. Library: 0 items. | D |
| Audio | AAC, AC-3 and E-AC-3 (Atmos plays as its E-AC-3 core), FLAC, ALAC, MP3 in MP4/fMP4. No DTS, DTS-HD or TrueHD: they transcode. | D |
| Multichannel | The phone is stereo. Whether Jellyfin's Safari profile caps channels at 6 or downmixes a 7.1 AAC is unknown. | V |
| Subtitles | WebVTT in HLS (and as a sidecar track). SRT, mov_text and external SRT become WebVTT at no video cost. PGS and VobSub (image) and ASS cannot be rendered: burn-in, which is a full video transcode. | D |
| MSE / hls.js | `ManagedMediaSource` since iOS 17.1: hls.js 1.5 uses it. Earlier iOS has no MSE on iPhone and the page falls back to native HLS. The page records which ran (`r.hls`). | D |
| AirPlay | The native `<video>` controls include AirPlay. Optional in the sitting. | D |

**Library on the iPhone: how many of the 536 items take each path** (default audio track, no subtitle selected, LAN).
The inventory lists 508 of the 536 items exactly (its top 15 combinations); the other 28 sit in 13 unlisted combinations. The count is
exact for the 508 and bounded for the 28. Rules: MP4 with H.264/HEVC and AAC/AC-3/E-AC-3 = direct; MKV with the same codecs = remux;
DTS default audio (no TrueHD in the library) = audio transcode; a video transcode only when video or range forces it.
| Path on the iPhone | Items | Share | How |
|---|---|---|---|
| Direct play | 18 to 24 | 3.4 to 4.5 % | 18 exact (the two MP4 combinations: HEVC 10-bit AAC 5.1, H.264 AAC 2.0) + 0 to 6 of the 6 unlisted MP4s |
| Remux only (container) | 497 to 506 | 92.7 to 94.4 % | 480 exact (every MKV with H.264/HEVC and AAC, AC-3 or E-AC-3) + 17 to 26 of the 28 unlisted |
| Audio transcode (video copied) | 12 to 15 | 2.2 to 2.8 % | 10 exact (MKV, H.264, DTS 5.1 core) + 2 to 5 unlisted DTS defaults (test rows 7 and 12 are among them) |
| Video transcode | 0 | 0 % | nothing in the library forces one with subtitles off: no AV1, no H.264 10-bit; the 3 DV 2160p files are D (copy in HLS) |
| Added by an image subtitle | up to 165 | up to 30.8 % | the 157 PGS + 8 VobSub items burn in (video transcode, 1080p HEVC on the J4125 is the worst case) when that track is on. Text subtitles (401 SRT, 2 mov_text) cost nothing. |
| Added by 7.1 audio, if the profile caps channels | up to 9 | up to 1.7 % | the 11 items with a 7.1 track, minus the DTS ones counted above (V) |
| Added on mobile data | 3 | 0.6 % | the 3 items over 20 Mbps exceed joeytest's remote cap and would transcode remotely |

Source: library counts M (inventory 2026-10-24); iPhone rules D. The exact split of the 28 unlisted items needs one read-only re-run of
`python scripts/player_study.py inventory --json`; it was not run for this note (no live call). Reading: on the iPhone about 94 % of the
library is "remux to HLS, copy video and audio"; any transcode is rare (under 3 %) until an image subtitle is switched on.

**iPhone predictions per test row** (D until the sitting; the sitting's matrix replaces them)
| Row | Predicted on the iPhone | Why | Source |
|---|---|---|---|
| 1 | Direct play | MP4, H.264, AAC | D |
| 2, 3 | Remux | MKV to HLS fMP4, E-AC-3 copied, SRT to WebVTT | D |
| 4 | Remux with the subtitle off; video transcode with PGS #2 on | PGS cannot render | D |
| 5 | Direct play if the file is `hvc1` | HEVC Main 10 in MP4 | D, V |
| 6 | Direct play or HLS copy, with HDR | DV 8.1 MP4, E-AC-3, mov_text becomes WebVTT | D, V |
| 7 | Remux + audio transcode; video transcode with PGS #5 on | DTS-HD MA; 2160p DV copied | D |
| 8 | Remux + audio transcode | DTS core to AAC; external SRT is free | D |
| 9 | Remux with the subtitle off; video transcode with VobSub #3 on | burn-in | D |
| 10 | Remux | default is Italian, the study picks English #2 | D |
| 11 | Remux, possibly an audio downmix | AAC 7.1 | D, V |
| 12 | Video transcode | PGS default on, 45.6 Mbps over the remote cap | D |

**iPhone sitting script** (replaces the generic phone rows; about 10 of the 35 minutes)
Dependency: it needs `https://preview.joeyhome.net/static/jy051/study.html`, so the JY-014 hands item (`preview` hostname on the tunnel and
the Access application) and `python scripts/joey.py preview up 70` must be done first. Without them the iPhone cannot run the sitting
(no laptop fallback: the laptop's firewall blocks the LAN). Do it in the same state window as the TV legs.
Setup: same Wi-Fi as the NAS, Low Power Mode off, Auto-Lock Never, silent switch off, volume up, Home Screen icon added. On the page:
Device = Phone, Network = LAN, runs per engine 3.
| Row | Open | Look for |
|---|---|---|
| 1 (control) | MP4 H.264 AAC | Start time (first-frame median, W1 then W2); seek to the middle and to 90 %: how long until the picture returns; rotate once, go fullscreen. |
| 2 (top combination) | MKV H.264 E-AC-3, SRT #2 | W1 should fail (MKV), W2 should play as a remux. Start time against the 5 s LAN budget; seek; subtitles on and off (WebVTT, no stall); audio decoded. |
| 5 (HEVC MP4) | MP4 HEVC Main 10 | W1 direct play works, or fails on the tag; colours correct. |
| 6 (DV/HDR) | 2160p DV + HDR10 MP4 | HDR: picture brighter than SDR, and the page reports the dynamic range; the second audio track; mov_text subtitles; start time at 15.6 Mbps. |
| 4 (PGS burn-in) | MKV HEVC AAC, PGS #2 | Method is Transcode; start time during a J4125 transcode; subtitles burned in and readable; seeking while transcoding. Claude reads the NAS CPU. |
| 8 (DTS) | MKV H.264 DTS, external SRT | Sound present (audio transcode); lip sync after a seek; page says audio decoded. |
Then at minutes 17-20: rows 1, 2 and 4 on mobile data with Network = Remote. Optional if time allows: AirPlay row 1 to the TV from the
native controls (does it start and keep playing). After each row say: picture OK, sound OK, subtitles OK. Copy results and paste to Claude at the end.

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
