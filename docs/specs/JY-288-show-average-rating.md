# JY-288 TV series: average the season ratings, highest first, like movies

Status: shipped (#300, live bf94e98, 2026-11-03)
Size: M
Live risk: none (reads media.db only; no schema change, no new writes)
Area: `hub/media_db.py` (`show_averages`), `hub/media_pages.py` (`_library_rows`, TV shows), `hub/media_film.py` (section 5, your rating), `hub/templates/media_film.html` (Scores card, TV hero facts), `hub/templates/_rate.html` (`avg_pill`), `tests/hub/`
Needs: none
Options page: no (orchestrator 2026-11-03: built with JY-282; the score uses the movie's existing look, so there is no new design to pick)

## Problem
B., 2026-11-02: "Can you average the rated season votings and show them as you would with movies. It would be nice to see my highest ratings first."

## What the code does today
- `rating` (media.db) holds one row per owner + key, with `level` show / season / episode. A season rating's key is `jf:<season id>` and its title `"Show · Season N"`; an episode's is `jf:<episode id>` and `"Show · S01E02 · Name"` (`media_item._rating_for`). The row has no show column.
- Show page (`/media/item/<series>`): the rating offered is the whole show (`jf:<series id>`, level show). The web Scores card shows "Yours 8" (`rate.rated_pill`) when that key is rated, else "Yours Rate". Season ratings never reach it. The TV draws no Scores card.
- JY-269 / JY-270 extras: the season chips and the rating strip show IMDb episode averages (`media_episode_ratings`, "8.2 avg"). Those are public scores, not yours; unchanged here.
- My shows (`/media/tv`): `media_library` reads `ratings[item_key]`; a library show's key is `tmdb:` / `tvdb:` (the connector), so neither a season rating nor the show page's `jf:` rating reaches the tile. The default sort is already "Your score" (highest first, unrated last), the same as My films.

## Rule
1. A show's score is the mean of your rated seasons. With no season rated, the mean of your rated episodes. One decimal ("8.5"); a whole number shows without ".0".
2. Your own whole-show rating, when there is one, wins over the mean.
3. Only the viewer's own ratings (owner: you, her, or the signed-in friend on the TV).
4. Season and episode rows are matched to the show by the title prefix `"<show title> · "` (the longest matching show title wins). One SELECT per page.

## Acceptance criteria
1. Show page, web and phone: the Scores card shows "Yours 8.5 avg" in the movie pill's style and grade colour; the hero Rate button still offers a whole-show rating.
2. TV show page: the hero facts line ends "Yours 8.5 avg" (the TV has no Scores card).
3. My shows tiles (grid) and rows (list) show the score like films; the default sort puts the highest first, unrated last.
4. A whole-show rating shows as today and wins over the mean, in the library too.
5. Season and episode pages unchanged.
6. Tests: the rule (seasons, episodes fallback, other owners, titles with " · "), the library order and badges, the show page pill, the own-rating precedence, the TV facts line.

## Performance budget
Media list / item page warm p95 <= 150 ms: one extra small SELECT on the show page and two on My shows.

## Out of scope
Home shelves' per-row scores, the diary, Wrapped, the "Because you rated" shelf, a schema column for the show key.

## Accept checklist
- [ ] A show with rated seasons shows "Yours x.x avg" on desktop, phone and TV.
- [ ] My shows lists my highest-rated shows first.

## Shipped notes

## Shipped notes (2026-11-03)

Merged #300 on B.'s accept (B. 2026-11-03: "accept all, except 293 does not need 'everything else"), one deploy, live bf94e98.
