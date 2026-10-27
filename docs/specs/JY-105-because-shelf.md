# JY-105 "Because you rated these 9 or 10" shelf

Status: shipped 2026-10-27
Size: M
Live risk: none (Seerr is read only, by the warm-up; nothing writes upstream)
Area: `hub/media_because.py` (new), `hub/media_warmup.py` (one call in `run_pass`), `hub/media_home.py` (`build_shelves`), `hub/media_guest_home.py` (`build`), `hub/templates/area_shelves.html` (the card tag line, the section marker), `hub/static/tv.js` (first focus skips the row), tests in `tests/hub/`
Needs: none
Options page: `C:\Users\b.edwards\Desktop\Claude\JoeyTV\review\JY-105-options.html` (look B + the five small questions)

## Problem
A shelf on Media Overview that suggests titles because of the ones the viewer loved. B., 2026-10-27: "Accept every recommendation on the Joey decisions page": A (the warm-up fills a cache, the shelf reads only that cache).

## Options and the pick
B., 2026-10-27: "JY-105: look B; ratings 9-10; 5 sources; refresh daily; friends: their own ratings; TV: row, never first focus".

- Look B: one merged shelf, round-robin across the sources; each card says which title it came from.
- Ratings 9-10: a source is a title-level rating (movie or show, not season or episode) of 9 or 10.
- 5 sources: the viewer's top 5, highest rating first, newest rating breaking ties.
- Refresh daily: rides the warm-up's 24 h library pass.
- Friends: on the media front a friend's shelf comes from their own ratings only.
- TV: a normal row, reached with Down; it never takes first focus.

## Acceptance criteria
### Warm-up (`hub/media_because.py` `refresh`, called from `media_warmup.run_pass`)
1. It runs inside the 24 h library pass (`library_enabled() and library_due()`), so at most once a day. Without Seerr keys it does nothing and leaves the cache as it is.
2. For each viewer (owner) with ratings in `media.db`, the sources are that owner's rows with `level = 'show'`, `score >= 9` and a `tmdb:` key, ordered `score DESC, rated_at DESC`, top 5. Keys Seerr cannot look up (`tvdb:`, `jf:`) are not sources.
3. Per source it reads `GET /api/v1/{kind}/{tmdb}/recommendations` once per pass (a source two viewers share is read once), paced. A failed read keeps that source's rows from the last cache, if any.
4. Dropped from each source's rows: any title the same owner has rated (any score, any level, by its `tmdb:` key), and any title the same owner has watched on the server: the owner's play history and diary (`play`, `diary`; an episode counts for its show), plus, for `you` and `her`, the Jellyfin snapshot's played films and shows of that profile.
5. The cache is one JSON file in the meta cache dir (`because_shelf.json`, shared by joey-hub and joey-media), keyed by owner. An owner with no sources has no entry.

### The shelf
6. It reads only the cache: no Seerr, Jellyfin or other network call on render. An absent or empty entry = no shelf, no heading, no placeholder.
7. Title "Because you rated these 9 or 10". It sits directly below Continue watching (first when there is no Continue watching shelf). No "All" link.
8. Cards: round-robin across the sources in source order (1st of each, then 2nd of each ...), a title already placed is skipped, at most `SHELF_MAX` (15).
9. Each card: poster, title, a small `<source title> ★<n>` line, and an "On server" (in the library, or Seerr says available) or "Request" tag. An on-server title with a Jellyfin id opens its item page; anything else opens `/media/title/<kind>/<tmdb>`.
10. Viewer isolation: the page reads the entry of the page's owner (`media_db.owner_of(view)`) only. You see yours, Georgina's view hers, a friend theirs. A friend never gets a household entry, and no owner's shelf appears on another's page.

### TV
11. A normal row reached with Down. `tv.js` first focus skips the posters of a section marked `data-tv-later`; when nothing else is on the page, first focus goes to the top bar, never to this row.

## Data
- Reads `rating`, `play`, `diary` (media.db). No schema change.
- Writes `<meta cache dir>/because_shelf.json`: `{"at": <epoch>, "viewers": {owner: [{"title", "score", "kind", "tmdb", "rows": [discover row, ...]}]}}`. Pruned like every meta file after 7 days without a refresh.

## Performance budget
- Hub page render, warm, p95 <= 50 ms / Media list <= 150 ms: the render adds one small JSON read, memoised on the file's mtime, and pure list work.
- The warm-up: at most 5 Seerr reads per viewer per day, de-duplicated, paced `LIBRARY_PAUSE_S`.

## Out of scope
- Season and episode ratings as sources; shows rated under a `tvdb:` / `jf:` key.
- Dropping a title rated after the day's refresh (it leaves at the next refresh).
- A "See all" page.

## Accept checklist
- Overview (you): rate two films 9 and 10, wait for (or trigger) the library pass; the shelf shows under Continue watching with "Film ★10" lines and On server / Request tags.
- Georgina's view shows her own sources, or no shelf.
- A friend on the media front sees only a shelf from their own 9-10 ratings, or none.
- TV: Home opens on the first Continue watching (or Recently added) poster; Down reaches the shelf.

## Questions for B.
None open: all five answered 2026-10-27 (quoted above).

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #239, squash-merged as `1912cb2` (1912cb2251f21db48d0ba1ce9eae662f6ec6af95).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-27: "JY-105: look B; ratings 9-10; 5 sources; refresh daily; friends: their own ratings; TV: row, never first focus""
- Follow-ups: none
