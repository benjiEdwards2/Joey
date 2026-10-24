# JY-119 Off-server shows get episode ratings

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/media_film.py` (the off-server title page's ratings), `hub/templates/media_film.html` (one `id` on the off-server season rows), `tests/hub/test_episode_ratings.py`
Needs: none
Options page: none: the off-server page would reuse the on-server "Seasons compared" block as it is (no new design)

## Problem
HITLIST row: "Warm-up does not prefetch them". The source line (archived BACKLOG, 2026-10-16 episode-flow round) holds two gaps: "Off-server shows (`/media/title/tv/…`) get no episode ratings; the warm-up does not prefetch ratings".

What the code does today (checked 2026-10-24 on origin/main):
- The media warm-up (`hub/media_warmup.py`) prefetches NO episode ratings, for any show. Its passes read Seerr bodies, film/show ratings (`media_film._ratings`), images and Jellyfin items. Episode ratings fill only from a show / season / episode page's BackgroundTask (`media_episode_ratings.build_ratings` → `_plan` → `fill`), so the first view of an on-server show has none and the next has them.
- An off-server show page (`/media/title/tv/{tmdb}`) never builds episode ratings: `media_film.py` sets `ratings` None unless Jellyfin has the series ("A show Jellyfin does not have … gets none for now").

So "extend the warm-up's prefetch to off-server shows" has nothing to extend, and a prefetch for off-server shows would fill ratings no page draws. The item needs a direction first.

## Acceptance criteria
B. picked A (2026-10-24):
1. An off-server show page draws the same "Seasons compared" block and the current season's strip as an on-server show page, from what is stored (media.db `episode_rating`) and cached (the Jellyseerr season reads) only. No watch state (no "seen" marks, no episode links): the off-server page has no Jellyfin episodes.
2. The IMDb id is the Seerr body's `externalIds.imdbId` (the page's existing `imdb_id` rule); the TMDB fallback is the Seerr season read, as today. Seasons from Seerr's season list (specials left out), capped at `SEASONS_MAX`.
3. The reads run as the page's BackgroundTask through the existing `_plan` / `fill` (OMDb one call per season, ≤ 12 vote reads, the shared 800/day OMDb cap, FAIL_TTL memo, 401 stops OMDb for the day). Nothing before the render; read-only (rule 7).
4. Tests: a cold off-server page draws no block and queues the reads; the next view draws the block; no OMDb key and no IMDb id fall back to TMDB; the on-server page is unchanged.

## Data
media.db `episode_rating` (no schema change). The Jellyseerr meta cache (`/api/v1/tv/{tmdb}/season/{n}`).

## Performance budget
Media item page, warm p95 ≤ 150 ms: stored rows + cache peeks, as on the on-server page. OMDb load comes only from pages B. opens, inside the existing day cap. No warm-up change.

## Options and the pick
Picked 2026-10-24. B.: "JY-119: A" (A: off-server show pages draw episode ratings the way on-server pages do, filled after the first view by the existing BackgroundTask; no warm-up change, no new API, no extra OMDb load beyond pages B. opens).

## Out of scope
New designs for the block; ratings for films; changing the OMDb budget.

## Accept checklist
- Open a show that is not on the server (twice): "Seasons compared" shows its seasons with IMDb (or TMDB) ratings.
- An on-server show looks as before.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #124, squash-merged as `3ff5f63` (3ff5f63032053430aa8fc1abba953868e725c3e5).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
