# JY-031 P1b: disk forecast on the hub card and in Discord

Status: shipped 2026-10-24
Size: L
Live risk: deploy (Discord posts from production)
Area: `hub/server.py`, `hub/server_alerts.py`, `hub/server_history.py`, `hub/tasks.py`, `hub/main.py` (hub card data), `hub/server_digest.py` (option B only), `tests/hub/`; added in the fix round (orchestrator, 2026-10-23): `hub/server_space.py`, `hub/README.md`, `docs/hub-changelog.md`
Needs: Phases 1–3 (shipped)
Options page: https://claude.ai/artifact/GD2DE6D3PiPkxd1UC8eiBN (private)

Phase 4 pilot item 2: a screen item through the whole loop (options, pick, ready, build, review, preview, accept).
Source: SERVER_REVIEW 2026-10-19 §2 P1; old BACKLOG (archived 2026-10-23): "Disk forecast reaches the Server page's Attention only; to reach the hub card + Discord, `check_once` must take `server_history.recent()` samples — Decision needed on the Discord noise."

## Problem
The NAS is RAID0 and fills at a known rate. Joey already works out when the fullest volume will reach 85 % ("/volume1 reaches 85% in 23 days at this rate"), but only the Server page's Attention list shows it. B. finds out only if he opens that page. The forecast should reach the hub's Server card and Discord, without noise.

## How it works today (read-only research, main 059b528)
- Samples: `hub/server_history.py:62` stores a row each time the `system` snapshot moves on (5-minute hub loop, `hub/tasks.py:45-54`, and each `/server` render, `hub/main.py:231`); kept 8 days, `recent()` returns 7 days.
- Maths: `disk_days` (`hub/server.py:509`), least-squares slope over wall-clock time; None under 24 h of span, at or over 85 % (`DISK_TARGET_PCT`, `:472`), flat or shrinking, or 10 years or more. Only the fullest volume is forecast (`:573`).
- Attention: under 30 days (`FORECAST_ATTENTION_DAYS`, `:475`), key `forecast:<path>`.
- The split: `hub/server.py:626-630` adds the forecast to the page only. `attention_items` (`:634`) feeds the render-time `sync` (`main.py:230`) and `server_alerts.check_once` (`:145`) without samples. If only one path carried the key, the other would delete its seen-row and the next tick would post it again: **all three paths (render, loop, hub card) must build the same key set.**
- Hub card: `server.hub_card` (`server.py:446`) via `_server_hub_card` (`main.py:146`, 60 s cache) → `_kpi.html`. All fine: "All up" · "Services · disk 74%". Warning: amber `.badge-wait` "Needs attention".
- Discord: "Joey Server: <text>", deduped on `server_attention_seen.key`; an episode lasts while the key stays in Attention; at most 5 posts a cycle; no resolved message; nothing posts while the NAS is off (22:00–07:00).
- Tests that pin it: `tests/hub/test_server_cleanup.py:24,34,41` (`:41` pins the split and must be re-pinned with a dated line), `test_server_history.py`, `test_server_alerts.py`, `test_server.py:281-295`, `test_hub_core.py`, `test_server_space.py`.

## Acceptance criteria
From B.'s pick (1A 2a 3a 4a, 2026-10-23):
1. The forecast is computed once per hub loop tick and cached in memory; the hub render, the `/server` render and `check_once` read the cache, so all three build the same key set. No `recent()` call on a hub render.
2. Hub Server card: the meta line gains "reaches 85% in about N days" and the amber "Needs attention" badge shows while the forecast is an Attention item.
3. Discord: one post per episode, "Joey Server: Disk: reaches 85% in about N days (Volume 1, 412 GB free)". No resolved post.
4. Hysteresis: an episode starts under 30 days and ends only when the projection is over 45 days, or the disk is flat or shrinking. A projection moving between 30 and 45 days does not post again.
5. The "collecting" state (fewer than 2 samples in 24 h, e.g. after a long NAS outage) keeps an open episode open instead of ending it, so a return does not post again.
6. Tests: the key set is identical on all three paths; one post per episode across a 30 → 35 → 28 day wobble; collecting keeps the episode; the card wording; the old split test re-pinned with a dated reason (rule 4). The suite only grows.
7. Budgets measured with `scripts/budgets.py` before and after: hub page p95 ≤ 50 ms not made worse; `/a/server` (JY-226, already 52–56 ms) not made worse.

## Data
No schema change expected: `server_attention_seen` already holds the key. The episode end rule needs the last projection in memory or a column on the seen row: decide in the build, note it here.
Build decision (2026-10-23): no schema change. The episode state (open, path, last projection, item) lives in memory (`hub/server_history.py`). Because the hub restarts every morning (NAS off 22:00–07:00) and on every deploy, the first step after a start treats an existing `forecast:<path>` seen row as an open episode, so a projection between 30 and 45 days after a restart does not post again.
Fix round (orchestrator decisions, 2026-10-23): at or over 85 % an open episode stays open and silent (words "at or over 85%") while the disk still grows, so 84.9 → 85.1 → 84.9 posts once; it ends on a flat or shrinking disk, or once below 85 % with a projection over 45 days. An episode restored after a restart that lands in "collecting" stays open even with no 7-day projection (words "filling fast"). A failed first compute skips the forecast for that tick and keeps its seen row (`server_alerts.sync(keep=)`). N days are whole days rounded down, at least 1 (29.6 → "29 days"). Any path under `/volumeN` reads "Volume N". Free space's "(≈ N days)" follows the cached item.

## Performance budget
Hub page render, warm p95 ≤ 50 ms (row 1); measured inside joey-hub with `scripts/budgets.py`.

## Options and the pick
Options page: https://claude.ai/artifact/GD2DE6D3PiPkxd1UC8eiBN
- A (recommended): amber card + one Discord post per episode, hysteresis 30 / 45 days.
- B: words on the card, forecast in the 07:30 digest, one alert under 7 days.
- C: posts at 30, 14 and 7 days, plus a "no longer filling fast" post.
B.'s pick, 2026-10-23, in the orchestrator session: "go with all recommended please." = 1A (amber card + one Discord post per episode), 2a (say "reaches 85%"), 3a (episode ends over 45 days or flat/shrinking), 4a (no resolved post). Marked ready the same day.

## Out of scope
The "free space" list of biggest watched films (SERVER_REVIEW P1 part 2). Forecasts for every volume (only the fullest, as today). JY-226 (the `/a/server` speed).

## Accept checklist
- On the preview (`preview up feat/JY-031-disk-forecast`): the hub Server card shows the forecast words (or, if the live disk is not forecast under 30 days, the test page in the PR shows the card with a forced forecast).
- Discord: the PR shows the exact message from a test against a fake webhook; the first real post after deploy matches it.

## Questions for B.
1. Which option? **A (recommended):** amber card and one Discord post per episode. **B:** words on the card, the forecast in the 07:30 digest, one alert under 7 days. **C:** posts at 30, 14 and 7 days, plus a "no longer filling fast" post.
2. What does "full" mean in the words? **a (recommended):** keep the 85 % target and say it: "reaches 85% in about 23 days". **b:** say "full in about 23 days" while the maths still aims at 85 %. **c:** project to 100 %: "full in about 41 days".
3. When does a warning end, so it can post again later? **a (recommended):** only when the projection is over 45 days, or the disk stops growing. **b:** today's rule, as soon as it is over 30 days (it can flap and post twice).
4. Should Discord say when it clears (A and B only)? **a (recommended):** no, like every other Server alert. **b:** yes, one post: "Joey Server: Disk: no longer filling fast (Volume 1)".

Reply in one message, e.g. "JY-031: 1A 2a 3a 4a, ready".

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #60, squash-merged as `3a7270b` (3a7270b9a9498f901b482aefdd654b0449377b9f).
- Deploy: `2026-10-24T00:01:29Z PASS prev=d5c9530 new=3a7270b suite green, smoke ok tv=current end=2026-10-24T00:18:37Z dur=1028s`
- Accept: in chat: "B., orchestrator session, 2026-10-24, after reviewing the JY-031 screenshots: Looks good."
- Follow-ups: none
