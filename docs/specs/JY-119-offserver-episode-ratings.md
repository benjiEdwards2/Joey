# JY-119 Off-server shows get episode ratings

Status: building
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
Not shipped. Draft, built on `feat/JY-119-offserver-episode-ratings`:
- `media_film.py`: a TV page with no Jellyfin seasons and a Jellyseerr season list (`t["seasons"]`) now calls `build_ratings` with the show's IMDb id (`imdb_id(raw, item)`), its TMDB id and `offserver_seasons()` (Specials left out, capped at `SEASONS_MAX`, no episodes, so no watch state). The render reads stored rows and cache peeks only; the missing reads ride the page's existing BackgroundTask (`ratings_later`). `media_episode_ratings.py` is unchanged.
- The new branch also fires when Jellyfin lists the show but holds no seasons for it; tested: one "Seasons compared" block, one strip, unique `season-N` ids.
- Review round (2026-10-24): friends (`guest.is_media()`) never start the ratings job. `guest_controls` drops `ratings_later` for both the off-server and the on-server branch (one line), so a friend's view draws stored rows only and OMDb's day cap stays the household's. A failed Seerr season read with no 404 is now remembered FAIL_TTL (`tmdbep:` memo, shared by the on-server TMDB fallback), so a failing Seerr is asked once per season, not on every view.
- `media_film.html`: the off-server season rows get `id="season-N"`, so the compare rows' `?season=N#season-N` links land on the Seasons list. The page ignores `?season`; the strip shows the latest aired season.
- Compare rows read "avg · 0 of N seen" on an off-server show: nothing is seen, and the block is the on-server one as it is.
- One existing test changed, 2026-10-24: `test_media_discover.py::test_title_page_lazy_hooks_per_season_and_no_episodes_inline` asserted no `/season/` call at all through the TestClient, which also runs the BackgroundTask. The page's background job now makes those Jellyseerr season reads (TMDB fallback), so the test stubs the job to keep pinning "no season call from the page itself", and now also asserts the household view schedules it.
- Tests (`tests/hub/test_episode_ratings.py`): cold page draws nothing and the background job is handed the Seerr seasons; the render makes no episode read; the next view draws "Seasons compared"; TMDB fallback with no IMDb id and with no OMDb key; Specials left out and the cap; a failing OMDb never fails the page; the on-server page is unchanged.
- Follow-up for HITLIST (not edited here): a warm-up prefetch of episode ratings (on-server shows on the Media home shelves, off-server shows on the watchlist and in requests, paced, under half the OMDb day cap) is its own idea if still wanted.
