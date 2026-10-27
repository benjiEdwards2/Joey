# JY-258 Hub half of the JY-057 TV shell player (flag off)

Status: shipped 2026-10-27
Size: M
Live risk: low (everything stays behind PLAYER_API, off by default)
Area: hub (`hub/player_api.py`, `hub/guest.py`, `hub/media_front.py`, `hub/media_film.py`, `hub/media_watch.py`)

## Why
The JY-057 TV device checks need the hub half live on joey-media first. But merging PR #219 as a whole would publish
TV app 1.0.3 (tv.yml) before those checks run. So the hub half was split out of #219 into PR #238, unchanged, and
merged on its own. #219 keeps only the `tv/` part and merges after the TV session.

B., 2026-10-27: "I'll keep the TV free. Tell me when the hub half is live and the session is ready to start."
JY-057 direction: "Go for tv change again."

## What
The design, tests and checklist are in [JY-057](JY-057-tv-shell-player.md). The code was reviewed there: two Sonnet
reviews and an Opus verifier passed #219 at 0bd7e5b. #238 carries the same change to each of its 9 files, and the
orchestrator checked this before merging.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #238, squash-merged as `afd521c` (afd521cd83265c41726a7bfe67d219d441887a01).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-27: "I'll keep the TV free. Tell me when the hub half is live and the session is ready to start." (hub half of JY-057, split as JY-258; JY-057 direction: "Go for tv change again.")"
- Follow-ups: none
