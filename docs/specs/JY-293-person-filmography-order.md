# JY-293 Person page filmography order

Status: shipped (#298, live bf94e98, 2026-11-03)
Size: M
Live risk: none
Area: `hub/media_person.py` (`_credits`, `build_person`), `hub/media_discover.py` (`_row`, only if it must carry extra credit fields), `hub/templates/media_person.html`, `tests/hub/test_media_person.py`
Needs: none
Options page: no

## Problem
B., 2026-11-02: "Movies with actual releases as the top, films that are proper film series below, then any bonus, feature or otherwise. Anything on the server should be at the top." Platforms: desktop, phone, TV.

## What the code does today
- `build_person` reads the Seerr `person/{id}` and `person/{id}/combined_credits` (10 min cache) and the Jellyfin snapshot library (`_library`, keyed `tmdb:<id>`).
- `_credits` merges cast and crew into one row per (kind, tmdb id), joins the roles, and sorts by release date alone, newest first, capped at `CREDITS_MAX` (200). A row with no date sorts last (empty string).
- `shelf` = rows with a Jellyfin id (carousel, "On server"); `films` and `shows` = the rest, split by `kind` into the "Films" and "TV" grids (first 24, then "Show more").
- `md._row` keeps only title, year, poster, status word and href. It drops every field that could tell a theatrical film from a featurette. `combined_credits` rows also carry (Seerr camelCase of TMDB) `releaseDate`, `voteCount`, `voteAverage`, `popularity`, `genreIds`, `mediaType`, `video`, `character`, `job`, `department`, `order`, `episodeCount`.
- There is no collection field in `combined_credits`. A film's collection comes only from the per-title read (`media_film._collection_id`), one request per title; that is too costly for 200 rows.
- "On server" is already known: a Jellyfin match in `_library` (`jf_id`), or a status word in `md.ON_DISK`.
- The page is the same markup on all platforms; TV uses the same grid cards. This spec changes order and grouping only.

## Proposed grouping and sort
Tier of each row (first match wins), then order inside a tier:
1. **On server**: has `jf_id` (any kind). Carousel as today, now ordered by the sort key below.
2. **Released films**: `kind == movie`, has a `releaseDate` on or before today, `video` false, genre ids do not include Documentary (99) unless `voteCount` >= 100, and `voteCount` >= 10. Newest first.
3. **Film series**: `kind == movie`, passes the tier 2 tests, and is a sequel or series entry. With no collection in the credits, the proxy is the title shares a leading word run (at least 2 words) with another title in this person's credits. Shown as its own sub-heading "Film series", newest first.
4. **Bonus and other**: movies with `video` true, no release date, a future date, `voteCount` < 10, or Documentary with low votes (featurettes, "making of", self appearances).
5. **TV**: `kind == tv`, grid as today, newest first, below the films.
Tie-breaks inside any tier: `releaseDate` desc, then `voteCount` desc, then title A to Z, then tmdb id.

## Acceptance criteria
1. A person with an on-server film, a released film, a series sequel and a featurette renders them in that order (fixture credits with those four).
2. A row with a `jf_id` is always in the first group, whatever its date or votes.
3. A movie with `video: true`, or `voteCount` below 10, lands in "Bonus and other", below the series group.
4. A movie with no `releaseDate` or a date after today lands in "Bonus and other" (not first, not dropped).
5. Two titles sharing a 2-word prefix go to "Film series"; a single unique title does not.
6. Inside a tier, order is date desc, then votes desc, then title; a fixture with equal dates proves the tie-breaks.
7. TV rows keep their grid below the films; the cast and crew role text and the status words are unchanged.
8. Every credit still appears exactly once; `head` counts (`N titles · M on server`) are unchanged.
9. The cap of 200 is applied after ordering so on-server and released films survive it.
10. Phone, desktop and TV render the same order; no new horizontal scroll; `test_tv_*` untouched.
11. Existing person tests stay green; the old "newest first" test is updated to the new order.

## Data
No new tables. `_credits` keeps `voteCount`, `video`, `genreIds` and the raw date from each credit (via `_row` or a side dict). No new upstream requests.

## Performance budget
Person page p95 <= 150 ms warm (cached credits), no extra Seerr or Jellyfin calls; sorting 200 rows is trivial. Measured on the preview with a 200-credit fixture.

## Out of scope
Per-title collection lookups, the TV ordering, the awards block, the biography, Follow.

## Accept checklist
- [ ] A prolific actor: on-server films first, real releases next, series, then bonus items.
- [ ] A director with featurettes: those sit at the bottom.
- [ ] Same order on phone and TV.

## Questions for B.
1. "Film series" test. A. title-prefix proxy, free (recommended), B. true TMDB collection, exact, but about one extra request per film (could be capped to the top 30), C. skip the series group and just order released then bonus.
2. Tier 1 (on server): A. one carousel of everything on server, ordered by the key (recommended), B. split it into released / series / bonus too.
3. Bonus threshold. A. `video` true or under 10 votes or no date (recommended), B. stricter: under 50 votes, C. looser: only `video` true.
4. Documentaries and self appearances (talk shows, awards): A. send to Bonus unless 100+ votes (recommended), B. treat as real releases.
5. TV below the films as today (recommended), or A. keep TV out of the new order entirely, B. interleave by tier.

## Shipped notes

## Shipped notes (2026-11-03)

Merged #298 on B.'s accept (B. 2026-11-03: "accept all, except 293 does not need 'everything else"), one deploy, live bf94e98. Group labels are plain ("Films", "Film series", "Bonus and other", "TV"); the "Everything else" prefix was dropped on B.'s note.
