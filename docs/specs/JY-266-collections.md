# JY-266 Collections page (franchise grid)

Status: building (B. 2026-11-06 picker: PUSH; rec A on defaults)
Size: M (three phases, S/M)
Live risk: low (read-only pages; the background pass reads Seerr; the one write is a request through the existing
Seerr request path)
Area: `hub/media_collections.py` (new: table, pass, owned/missing computation, pages), `hub/media_store.py` (one
STEPS entry), `hub/tasks.py` (one loop), `hub/main.py` (one router line), `hub/guest.py` (route classes),
`hub/media_nav.py` (one tab), `hub/templates/media_collections.html` + `media_collection.html` (new),
`hub/templates/_film_collection.html` (banner link), `hub/static/control-surface.css` (non-token lines),
`tests/hub/test_media_collections_jy266.py` (new)
Needs: none
Options page: https://claude.ai/artifact/C1vBLRmwWPf7ryCwERteKG (rec A: grid page on top of C's franchise page)
Date: 2026-10-29 (draft), 2026-11-06 (final)

B., 2026-10-28: "File collection page as an idea." (reference screenshots of a friend's site, shared in chat 2026-10-28)
B., 2026-11-06 (picker): PUSH. The options page's recommendation A applies, every question on its default:
A (grid page + franchise page), TMDB ids via Seerr, a Collections tab in the Movies row.

## Problem
Franchises (Alien, John Wick) are scattered across the Movies list. A Collections page gathers them: one card per
franchise, so B. can see what he has and what is missing.

## Data (P1)
- Membership comes from TMDB `belongs_to_collection`, read through Seerr: the movie body `/api/v1/movie/<tmdb>`
  (`collection.id`) and the collection body `/api/v1/collection/<id>` (`name`, `posterPath`, `backdropPath`, `parts`
  = every film with its release date and poster). No new key, no direct TMDB call.
- Two new tables in `media.db` (media_store STEPS step 8, `media_collections.migrate`):
  - `collection(id INTEGER PRIMARY KEY, name, poster, backdrop, parts_json, fetched_at)`; `parts_json` is a compact
    list `[{id, title, date, poster}]`.
  - `collection_member(movie_tmdb INTEGER PRIMARY KEY, collection_id INTEGER NULL, checked_at)` = the index
    movie_tmdb -> collection; a film with no collection keeps a row with NULL so it is not asked again.
  - `collection_state(key, value)`: `kick_at` (the manual kick), `last_pass_at`.
  - `collection_gone(id, gone_at)`: a tombstone for a collection TMDB answered 404 for; not asked again for 30 days.
- The pass (`media_collections.tick`, hub loop, first run ~4 min after start, then hourly): owned films = the movie
  library of the jellyfin snapshot (`tmdb:<id>` keys). Due = an owned film with no member row, or one checked over
  30 days ago (monthly), or before the last kick; a collection is due when a member names it and its row is missing,
  over 30 days old or older than the kick. At most PER_PASS (40) Seerr reads per tick, so a first fill of a few hundred
  films spreads over a few hours. A failed read (no answer) stops the pass (backoff: the next tick, an hour on); a 404
  is an answer: a film with no Seerr body gets NULL; a collection TMDB drops loses its row and gets a tombstone (not
  re-asked for 30 days; its films keep their own monthly date). A 2xx that is not a JSON object counts as a failure.
  Memory gate: the pass is skipped when the `system` snapshot has no fresh reading or under 1,200 MB available (as
  the posters pass). Kill switch `COLLECTIONS=off`: no loop, the pages still read what is stored.
- Manual kick: owner "you" on the private front, a "Check now" button on the grid page (POST
  `/media/collections/refresh`): sets `kick_at` and runs one pass after the response (BackgroundTask).
- Owned / missing: `media_collections.summaries(owned_keys)`: one card per stored collection with at least one part
  in `owned_keys`; parts in release order; `n`, `on`, year range ignoring parts with no date, `complete`. The pages
  read the tables only (no Seerr call on render); the franchise page of a collection not stored yet falls back to the
  title page's cached Seerr read (`media_film._cget`, already warm when the banner link was followed), for the
  household only: a friend asking for an unstored id gets 404 with no upstream read.
- A friend's page (media front) uses the friend's scrubbed library (`media_home.view_jelly`): collections from titles
  they can see only; no household watch state appears.

## Screens
### P2 franchise page `/media/collections/<id>`
- Header: collection backdrop banner, poster, name, "4 films · 2001-2011 · 3 of 4 on Joey".
- Parts in release order as poster cards; owned in colour (link to the title page), missing dimmed with a
  **Request** button that opens the normal confirm step in the card (`/media/title/movie/<id>/request?step=confirm`,
  the existing path: the household's own request goes straight through, a friend's is pending for B.'s approve /
  decline, JY-230). A part already requested reads "Requested" / "Processing" (jellyseerr snapshot), no button.
- The film page's series banner (`_film_collection.html`, web) gets an "Open collection" link.

### P3 grid page `/media/collections` (Movies > Collections tab)
- One card per franchise: a poster stack (collection poster in front, up to two part posters behind), name,
  "4 films · 2001-2011", a "3 of 4 on Joey" bar (filled by the share on Joey, a tick when complete).
- A-Z jump bar (letters with cards; A-Z sort only), filters All / Complete / Missing some, single-film collections
  hidden (a "Single films" chip shows them), sort A-Z (default) / Size / Newest / Most complete. Chips are links.
- Owner only: "Check now" + "Last checked <date>". Friends see the grid read-only.
- Empty state: "No collections yet" (+ for the owner: "The monthly check fills this; Check now starts it").

## Platforms
- Desktop / iPad / phone: the grid is the shared `poster-grid`; the A-Z bar and chips scroll sideways on a phone.
- TV (Joey TV shell): the Collections tab sits in the Movies tab row (it folds under "More", JY-259); the grid and
  franchise page are plain links in the kit grid, so D-pad focus moves card to card; no A-Z bar on the TV; filters
  and sorts as one chip row. Q4 A: the TV franchise page shows the owned films only, read-only (no Request). tv.css
  pins unchanged.

## Performance budget
Grid / franchise warm render: two small table reads (no network). The pass: at most 40 small JSON reads an hour,
inside joey-hub's 200 MiB.

## Acceptance criteria
- [ ] P1: fixture of 6 owned films over 3 collections (one complete, one missing a film, one single-film) gives the
      right counts and year ranges; a film with no collection is stored NULL and not re-asked inside 30 days; a
      collection TMDB drops (404) is removed; PER_PASS cap; kick makes everything due; `COLLECTIONS=off` runs nothing;
      memory gate; the migration upgrades a populated media.db (user_version 7 -> 8).
- [ ] P2: franchise page lists parts in release order, missing dimmed with Request (confirm-step link), requested
      parts read "Requested"; friend view on the media front works; banner link present.
- [ ] P3: grid A-Z, sorts, filters, single films hidden by default, empty state, kick button owner only (403 / 404
      otherwise), no network call on render, Movies tab lit, TV mode renders without the A-Z bar.
- [ ] B. sees his real franchises on web, iPad and phone with correct counts (after the first pass on the NAS).

## Out of scope
TV shows' "collections"; user-made lists / Jellyfin BoxSets; "Request all missing" (v1 is one film at a time);
collections B. owns no film of; an Overview shelf (option B, later).

## B.'s picks (2026-10-29)
B., 2026-10-29: "I like A for both options." Picks: 1A (single films hidden, with a filter), 2A (one film at a time),
3A (a Movies tab), 4A (TV shows owned films only, read-only).
