# JY-119 Off-server shows get episode ratings

Status: spec
Size: S (A alone); M if B. picks B
Live risk: none
Area: `hub/media_film.py` (the off-server title page's ratings), `hub/media_episode_ratings.py`, `hub/media_warmup.py` (only with option B), `tests/hub/`
Needs: none
Options page: none: the off-server page would reuse the on-server "Seasons compared" block as it is (no new design)

## Problem
HITLIST row: "Warm-up does not prefetch them". The source line (archived BACKLOG, 2026-10-16 episode-flow round) holds two gaps: "Off-server shows (`/media/title/tv/…`) get no episode ratings; the warm-up does not prefetch ratings".

What the code does today (checked 2026-10-24 on origin/main):
- The media warm-up (`hub/media_warmup.py`) prefetches NO episode ratings, for any show. Its passes read Seerr bodies, film/show ratings (`media_film._ratings`), images and Jellyfin items. Episode ratings fill only from a show / season / episode page's BackgroundTask (`media_episode_ratings.build_ratings` → `_plan` → `fill`), so the first view of an on-server show has none and the next has them.
- An off-server show page (`/media/title/tv/{tmdb}`) never builds episode ratings: `media_film.py` sets `ratings` None unless Jellyfin has the series ("A show Jellyfin does not have … gets none for now").

So "extend the warm-up's prefetch to off-server shows" has nothing to extend, and a prefetch for off-server shows would fill ratings no page draws. The item needs a direction first.

## Acceptance criteria
Pending B.'s pick (see Questions). For option A they would be:
1. An off-server show page draws the same "Seasons compared" block and the current season's strip as an on-server show page, from what is stored (media.db `episode_rating`) and cached (the Jellyseerr season reads) only. No watch state (no "seen" marks, no episode links): the off-server page has no Jellyfin episodes.
2. The IMDb id is the Seerr body's `externalIds.imdbId` (the page's existing `imdb_id` rule); the TMDB fallback is the Seerr season read, as today. Seasons from Seerr's season list (specials left out), capped at `SEASONS_MAX`.
3. The reads run as the page's BackgroundTask through the existing `_plan` / `fill` (OMDb one call per season, ≤ 12 vote reads, the shared 800/day OMDb cap, FAIL_TTL memo, 401 stops OMDb for the day). Nothing before the render; read-only (rule 7).
4. Tests: a cold off-server page draws no block and queues the reads; the next view draws the block; no OMDb key and no IMDb id fall back to TMDB; the on-server page is unchanged.

## Data
media.db `episode_rating` (no schema change). The Jellyseerr meta cache (`/api/v1/tv/{tmdb}/season/{n}`).

## Performance budget
Media item page, warm p95 ≤ 150 ms: stored rows + cache peeks, as on the on-server page. With option B, the warm-up pass stays sequential and paced, inside the OMDb day cap.

## Options and the pick
None yet (see Questions).

## Out of scope
New designs for the block; ratings for films; changing the OMDb budget.

## Accept checklist
- Open a show that is not on the server (twice): "Seasons compared" shows its seasons with IMDb (or TMDB) ratings.
- An on-server show looks as before.

## Questions for B.
1. What should JY-119 do, given the warm-up prefetches no episode ratings today?
   - **A (recommended):** off-server show pages draw episode ratings the way on-server pages do (filled after the first view, by the existing BackgroundTask). No warm-up change. Small, no new API, no extra OMDb load beyond pages B. opens. A warm-up prefetch becomes its own HITLIST idea, if still wanted.
   - B: A, plus a warm-up prefetch of episode ratings for on-server shows on the Media home shelves and off-server shows on the watchlist and in requests: at most 10 shows per 3-hour pass, paced, and only while the OMDb day count is under half the 800 cap, so page views keep the rest. Size M.
   - C: warm-up prefetch for on-server shows only (the HITLIST title stays unmet for off-server shows).
2. (Only for B) Which off-server shows does the warm-up take? **A (recommended):** watchlist + requested. B: also followed people's new shows. C: watchlist only.

## Shipped notes
