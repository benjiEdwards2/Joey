# JY-050 Media player: spec + questions

Status: spec
Size: S
Live risk: none
Area: `docs/specs/` only (writing; no code, no live system touched)
Needs: JY-002
Options page: none: this item fixes scope only. JY-052 makes the player-screen options page after JY-051.

## Problem
B. decided (2026-10-23) that "Joey gets its own media player on every device (web, phone, TV), replacing the hand-off to the Jellyfin app", and that it can wait: "After pilot is fine". He has seen ffmpeg, Jellyfin and ExoPlayer and wants the options investigated before choosing (JY-051), so this spec names no player technology. It fixes who watches on what, how files play, and what "done" means. A transcoding box will be bought (JY-049), but the player must work on direct play without it.

## What Joey plays today
- **Web and phone:** the film page's Play button (Resume / Play again / Next to watch) is the only Jellyfin hop. It opens `/web/#/details?id={jf_id}&serverId={server_id}` in Jellyfin's own web client. Joey plays no video itself.
- **TV shell (Kotlin WebView on the TCL Google TV and a Google TV stick):** `JellyfinLauncher.open(itemId)` starts the official Jellyfin Android TV app with the item id, and one OK press plays or resumes. If the app is missing, a card links to the store. Media keys belong to Jellyfin. Back from it lands on the TV home screen, not Joey.
- **Streams** come from the `https://jellyfin.joeyhome.net:8443` edge. Video never goes through the Cloudflare tunnel; pages stay behind Access.
- **Limits:** upload is 32.5 Mbps, so one friend stream at a 20 Mbps cap. The NAS (Asustor, Celeron with Quick Sync) must keep 1,200 MB RAM available. The JY-049 box takes transcoding later (JY-059).

## Acceptance criteria
Done for this spec:
1. B. has answered every question below, and each answer is in DECISIONS.md, dated.
2. The device list is final, each with a role (household or friend) and an order.
3. A direct play / remux / transcode policy and bitrate cap is written per device.
4. Status moves to `ready` (Round 2 first if answers change the design), and JY-051's device and test-file list comes from it.

Done for the player programme, checked per device on the JY-051 test files (H.264, HEVC 10-bit HDR, AV1; DTS/TrueHD; PGS/ASS subtitles):
5. Every in-scope device plays every test file as direct play, remux or transcode, recorded in the JY-051 matrix.
6. Press Play to first frame is measured on the LAN and from outside it, against the target from Q8.
7. Stop on one device, resume within 10 s of that position on another.
8. Every audio and subtitle track in the test files is selectable.
9. `CLAUDE.md` budgets hold, NAS available RAM stays at or above 1,200 MB during a transcode, and no stream exceeds its cap.
10. TV: D-pad playback works, Back returns to Joey, and the update drill passes on the TCL.

## Out of scope
Choosing the player technology (JY-051); the screen's look (JY-052); buying or installing the box (JY-049, JY-059); library, Seerr or arr changes; streaming through Cloudflare; Samsung/LG native apps; casting.

## Questions for B.
**1. Which devices first?** A) PC browser, then phone, then TV. B) TV first. C) PC and phone together, TV last. *Recommend A: it matches JY-054 then JY-057, and the TV shell ships once.*

**2. Household only, or friends too?** A) Household only now; friends keep the official Jellyfin app and JY-058 stays parked. B) Household first, friends after JY-057 (the pilot friend's Google TV). C) Friends from the start. *Recommend A, reopen after JY-057: friends add a security gate and the 20 Mbps cap.*

**3. Direct play or transcode?** A) Direct play first, remux when only the container is wrong, transcode only when a codec or audio cannot play, remote cap 20 Mbps. B) Always transcode remote streams to 1080p. C) Never transcode; show "can't play here". *Recommend A: it keeps the NAS CPU idle and works before the box arrives.*

**4. Offline downloads?** A) None, online only. B) Phone downloads later, as its own item. C) In v1. *Recommend A: a separate feature with storage and licence questions.*

**5. Subtitle and audio defaults?** A) Follow each Jellyfin user's saved setting. B) Original audio, subtitles off unless forced. C) English audio and subtitles always on. *Recommend A: Jellyfin already stores it, so Joey adds nothing to maintain.*

**6. Resume across devices?** A) Jellyfin is the single record; Joey reads and writes progress and watched there (JY-055). B) Joey keeps its own progress and syncs occasionally. *Recommend A: one source of truth, and friends' official apps stay in step.*

**7. What happens on the TV shell?** A) A new signed release replaces the hand-off after the TV UI round (JY-042), so the shell changes once, with the Jellyfin app kept as fallback for one release. B) Ship the player before JY-042. C) Keep the hand-off on TV for good; build web and phone only. *Recommend A.*

**8. What is the success measure?** A) A film starts within 5 s on the LAN and 10 s remote, resumes across two devices, and you don't open the Jellyfin app for a week. B) Only the JY-051 matrix passes. C) Your sign-off per device. *Recommend A: measurable, and it mirrors how Joey TV's production gate worked.*

## Shipped notes
Not yet.
