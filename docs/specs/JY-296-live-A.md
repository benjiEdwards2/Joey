# JY-296 / JY-297 Live page, Option A: now-playing wall + Health rail

Status: shipped (live 91c73ab 2026-11-04)
Size: M
Live risk: low (owner-only page; snapshot reads only)
Area: `hub/media_pages.py` (`/media/playing` + two part routes), `hub/templates/media_playing.html`, `hub/templates/_live_now.html`, `hub/templates/_live_health.html`, `hub/static/control-surface.css` (`.live*` rules), `hub/guest.py` (PRIVATE entries), `tests/hub/test_live_jy296.py`
Needs: none
Options page: done (`JoeyTV/review/JY-296-live/options.md`); B. picked A on 2026-11-04

## Problem
JY-296: Activity > Live should feel live. JY-297: Health moves into Live, on the right side, owner only.
B., 2026-11-04, on the Option A mock-up: "you need to fix it as it looks to be going off the page to the right."
The mock overflowed because of a bare `1fr` column, grid items without `min-width: 0` and a non-shrinking tile row.

## What it builds
- Left column (`_live_now.html`): one backdrop card per stream (title, who, play method, progress bar and %); Downloading (qbittorrent `active`: name, state, %, speed, ETA); Up next and Latest additions as poster tile rows that scroll sideways.
- Right rail (`_live_health.html`): services summary, CPU, RAM, each disk with free space and the cached disk forecast, every app Up/Down in words, the backup line. At <= 1100 px the rail moves to the top.
- Empty state: "Nothing playing" plus the last watched row from `history.recent[0]` when the snapshot has it; Up next follows below either way.
- Refresh: `/media/playing/part/now` and `/media/playing/part/health`, `hx-trigger="every 30s [!document.hidden]"`, outerHTML swap. Each poll reads snapshots and the in-memory forecast only; no Jellyfin or qBittorrent call.
- Not in this item: time left, device, 4K/HDR, transcode reason (the jellyfin snapshot does not hold them); TV Live page; removing the separate Health tab.

## Acceptance criteria
1. No horizontal overflow at 2560, 1024 and 390 px wide: `document.documentElement.scrollWidth == clientWidth`.
2. The Live grid uses `minmax(0, 1fr)` columns with `min-width: 0` on its items; the tile rows have `overflow-x: auto` (CSS test).
3. Owner-only: a friend gets 404 on `/media/playing`, `/media/apps` and both part routes; the guest nav has no Live tab. The part routes are PRIVATE in `hub/guest.py` (route classification test passes).
4. Both fragments render alone with their poll attributes; the page includes both.
5. Empty state shows "Nothing playing" and the last watched title when present.
6. Health words: Up/Down as words, the forecast words on their volume.

## Performance budget
Each fragment render under 50 ms warm; `/media/playing` warm p95 <= 150 ms. About 240 small requests an hour per open tab.
