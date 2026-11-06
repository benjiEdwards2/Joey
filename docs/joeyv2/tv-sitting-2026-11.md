# TV sitting (JY-040 W7 + JY-307 phase 5 device check)

One hands bundle at the TCL, B. only. Tick each line and paste the list back to the orchestrator. No secrets anywhere.

## 0. Update
- [ ] Open Joey TV; it offers 1.0.5 (build 2026110601). Update. Version shown in Settings = 1.0.5.

## 1. Player overlay (JY-307 phase 5, TV 1.0.5)
Play an episode, then a film. Note anything that looks wrong or still "zoomed in".
- [ ] Controls appear on any key, hide after 5 s while playing, never while paused.
- [ ] Title and line read at the new size (about a shelf heading, not a banner); nothing clipped at the screen edges.
- [ ] Seek bar: Left/Right scrubs, the time reads elapsed and remaining, the bar stays inside the bottom block.
- [ ] Icon buttons: labels show only on the focused one; D-pad reaches every button in order (Pause, Back 10 s, Forward 30 s, Audio & subtitles, Next episode).
- [ ] Audio & subtitles pop-up opens over the bar, closes on Back, selection sticks.
- [ ] Resume from a saved position: the "Resumed from … · …m left" line shows once, then goes.
- [ ] Up next: in the last minute of an episode the card shows with the next episode's still; OK plays it; Back dismisses.
- [ ] Film: same overlay without Next episode; credits countdown at the end.

Optional numbers (PC on the same network, adb debugging on the TV): run the audit tool from the repo root with `--serial` set to the TV's address and port, labels `controls_episode`, then `hidden --expect-focus 0` (see the header of tv/tools/player_audit.py). Paste the summary line.

## 2. W7 items (from the Joey TV plan)
- [ ] Soak: leave an episode playing 20 min; no stall, no bar drift.
- [ ] Test-account revoke drill: on the hub, revoke the test friend's access; the TV signed in as that account loses the library within a minute and lands on the sign-in screen; re-grant and it comes back.
- [ ] Transcoded stream during a deploy (JY-173): start a 4K title (the 20 Mbps cap forces a transcode), ask the orchestrator to run a deploy, playback survives the swap.
- [ ] 4K bitrate cap read (JY-171): the Jellyfin dashboard shows the stream transcoding at or under 20 Mbps.

## 3. Title pages on the TV (regression after JY-316/317)
- [ ] A show page: season chips, episodes row, Play/Resume; D-pad from Play lands on E1.
- [ ] A season page: same, with the season's poster.

Paste back the ticked list plus free-text notes. Anything untickable becomes a HITLIST row.
