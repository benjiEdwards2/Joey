# JY-051 measured matrix

Device x candidate x test file, from the one TV + phone sitting (`docs/specs/JY-051-player-options.md`, hands bundle).
Test files: `docs/specs/JY-051-inventory.md` ("Test-file set"). Everything between the markers is rewritten by
`python scripts/jy051_sitting.py matrix` from the collected results (TV logcat, the study page's copied results);
text outside the markers is kept.

Candidates: W1 = PC `<video>` on the direct file, W2 = PC `<video>` + hls.js on Jellyfin HLS, P1-W1 / P1-W2 = the
same page on the phone (PWA), T1-W1 / T1-W2 = the same page inside the TV's WebView, T2 = Media3 ExoPlayer on the
direct file, T2F = T2 with the FFmpeg audio extension, T2H = ExoPlayer on Jellyfin HLS (only for files T2/T2F could
not play). T3 (Jellyfin's own TV app) and W3 (Jellyfin web) are checked by eye in the sitting and noted below.
Account: joeytest (friend policy: 20 Mbps remote cap; LAN unaffected).

<!-- jy051:matrix:start -->
Not measured yet: the sitting has not run.
<!-- jy051:matrix:end -->

## Notes from the sitting
Not yet.

## Phone column: iPhone 15 Pro (B., 2026-10-26: "My phone type is an iphone 15 pro.")
Source: **M** measured by this study, **D** documentation (Apple, WebKit, Jellyfin), **V** to verify in the sitting.
All iPhone entries are D until the sitting; the library counts are M (inventory 2026-10-24). Detail, the per-row
predictions and the sitting script: `docs/specs/JY-051-player-options.md`, "iPhone 15 Pro". The PC and TV columns are filled
from the sitting, not from documentation.

| Area | Phone (iPhone 15 Pro, iOS 17/18, Safari/WebKit, A17 Pro) | Source |
|---|---|---|
| Containers | MP4, MOV, HLS (fMP4, TS) direct; MKV needs a remux to HLS | D |
| H.264, HEVC | Hardware; HEVC includes 10-bit and HDR10; Dolby Vision 5 / 8.1 via HLS | D, V |
| AV1 | Hardware on A17 Pro, Safari 17+ (about 85 % sure; none in the library) | D |
| VP9 | Limited or software; not planned on (none in the library) | D |
| Audio | AAC, AC-3, E-AC-3, FLAC in MP4; no DTS or TrueHD (transcode) | D |
| Subtitles | WebVTT in HLS; PGS, VobSub, ASS burn in (video transcode) | D |
| hls.js | Needs iOS 17.1+ (ManagedMediaSource); else native HLS | D |

Library on the iPhone (536 items, default audio, no subtitle selected, LAN; 508 exact, 28 unlisted bounded):
direct play 18 to 24, remux only 497 to 506, audio transcode 12 to 15, video transcode 0. An image subtitle turned on adds up to 165
video transcodes; 7.1 audio could add up to 9 audio transcodes (V); the 3 items over 20 Mbps transcode on mobile data (M for the counts, D for the rules).
