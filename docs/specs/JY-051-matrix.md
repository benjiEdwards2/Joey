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
