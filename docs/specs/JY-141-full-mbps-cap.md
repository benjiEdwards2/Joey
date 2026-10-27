# JY-141 Quiet-mode cap vs the live qBittorrent cap

Status: building (built ahead on the recommended option A; B. has not picked yet)
Size: S
Live risk: none in this PR (the hub already writes the cap; the NAS env line goes in later through `nas_scripts/append_env.sh` in a deploy window)
Area: `hub/server_quiet.py`, `tests/hub/test_server_quiet.py`, `deploy/.env.example`, `docs/`
Needs: none
Options page: none: no new screen, one setting and one line of text. Options are in `JoeyTV/review/decisions-2026-10-27/options.md` (JY-141).

## Problem
Server > Downloads has Quiet (5 Mbps) and Full speed. Full writes a qBittorrent limit of 0 (no cap). The cap that fixed the slow pages (evaluation 2026-10-12) is B.'s hand cap of about 41 Mbps, so pressing Full removes the fix.

## Acceptance criteria
1. `FULL_MBPS` (hub env, a positive number of Mbps) sets what Full writes. Unset, empty, junk or negative falls back to 41. `0` is allowed on purpose and means unlimited (the old behaviour).
2. Pressing Full writes `limit = round(FULL_MBPS * 1e6 / 8)` bytes/s (41 Mbps = 5,125,000), reads `transfer/info` back and confirms by the words ("41 Mbps"), like Quiet.
3. The Full confirm text names the cap, taken from the setting: "This caps qBittorrent's download speed at 41 Mbps ...". It no longer says "removes the cap" unless `FULL_MBPS=0`.
4. Mode reading: a live cap that reads as the Quiet value is `quiet`; one that reads as the Full value is `full`; anything else is `custom`. A live cap of 0 (unlimited) is `full` only when `FULL_MBPS=0`; otherwise it is `custom` and shows "Unlimited" with both chips as links. So B.'s existing 41 Mbps hand cap now shows as Full speed.
5. Quiet is unchanged (5 Mbps, `QUIET_MBPS`). Chip labels, flashes and routes are unchanged.
6. `deploy/.env.example` lists `FULL_MBPS=41`; the contract doc, hub README, changelog and preview README mention it.

## Data
No tables. One new env var, `FULL_MBPS`, read by the hub only. NAS: append `FULL_MBPS=41` to the hub env later with `nas_scripts/append_env.sh` (trailing-newline guard), in a deploy window. The default is already 41, so the line is optional and only makes the value visible.

## Performance budget
None apply: no new render work, no new calls.

## Options and the pick
Options A, B, C in the options file. Recommended: A. B.'s pick: not yet. This PR stays a draft until he picks.
Deviation from the option text: A said "default 0 = today's behaviour, set 41 on the NAS". The brief for this build sets the default to 41, so the code is safe without the env line, and `FULL_MBPS=0` gives the old behaviour back.

## Out of scope
Changing Quiet, the chip labels, or touching the NAS.

## Accept checklist
1. Server > Downloads: with the live cap at about 41 Mbps the Full speed chip is the filled one.
2. Press Full speed: the confirm says "caps qBittorrent's download speed at 41 Mbps", and the button writes 41 Mbps (read back "Capped at 41 Mbps").
3. Press Quiet, then Full again: the cap returns to 41 Mbps, never unlimited.

## Questions for B.
1. Pick for JY-141: A (this PR), B (env only, `QUIET_MBPS=41`) or C (leave it). Recommended: A.

## Shipped notes
Not shipped.
