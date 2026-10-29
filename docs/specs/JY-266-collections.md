# JY-266 Collections page (franchise grid)

Status: spec (questions answered 2026-10-29; `ready` once the grid options page is picked)
Size: M (three phases, S/M)
Live risk: none (read-only; the one write is a request through the existing Seerr request path)
Area: `hub/media_collections.py` (new), `hub/templates/media_collections.html` (new), `hub/templates/_media_tabs.html` (one tab), `hub/media_film.py` (read of `belongs_to_collection`, already partly there as `_collection_id`), `hub/main.py` (one router line), `hub/media_store.py` (one STEPS entry), `hub/static/control-surface.css` (a few non-token lines), `tests/hub/test_media_collections_jy266.py` (new)
Needs: none. The grid is a screen: it gets an options page before phase 2 builds it (CLAUDE.md rule 2).
Options page: to come (grid density and card design on desktop / iPad / phone / TV)
Date: 2026-10-29 (draft)

B., 2026-10-28: "File collection page as an idea." (reference screenshots of a friend's site, shared in chat 2026-10-28)

## Problem
Franchises (Alien, John Wick) are scattered across the Movies list. A Collections page gathers them: one card per
franchise, so B. can see what he has and what is missing.

## What it shows
One card per TMDB collection that has at least one film **on Joey** (Jellyfin):
- Collection poster (TMDB), name, film count "3 of 5 on Joey", year range "1979-2017".
- On Joey vs missing: a small bar filled by the share on Joey; a tick when complete.
- A-Z by default; sort by name, size, newest film, % complete; filter All / Complete / Missing some.
- A collection page lists its films in release order: owned films in colour, missing ones dimmed with a
  **Request** button (the existing Seerr request flow and approval rules: the household's own request goes straight
  through, a friend's goes via JY-230's approve/decline).

## Data
- Membership comes from TMDB `belongs_to_collection` (id, name, poster, backdrop). Source: the Seerr title body Joey
  already reads on the title page (`media_film._collection_id` uses `body["collection"]`) and the collection body
  `/api/v1/collection/<id>` (its `parts` = every film, with year and poster). No new key, no direct TMDB call.
- Owned = a Jellyfin movie whose TMDB id is in `parts` (snapshot rows carry `tmdb`). Requested / pending state comes
  from the existing request cache, so a pending film shows "Requested", not "Request".
- New small table `collection` in `media.db` (new `STEPS` entry): `id, name, poster, backdrop, parts_json, fetched_at`,
  plus an index `movie_tmdb -> collection_id`, filled by a monthly background pass over owned films (batched, inside the
  pass limit, memory gate and backoff). The page reads these tables only: no live TMDB or Seerr call on render. Posters
  are cached through `/img` as today.
- A friend's page shows collections from titles they can see only; no household watch state appears.

## Performance budget
Media list / item page warm p95 <= 150 ms (one read of two small tables); the background pass stays inside joey-hub
<= 200 MiB; numbers in the PR.

## Phases
| # | Step | Verify |
|---|---|---|
| P1 | `collection` table + monthly pass + the owned/missing computation (no screen) | Fixture: 6 owned films across 3 collections (one complete, one missing a film, one single-film); counts, year ranges, a film with no collection, a collection TMDB drops, monthly rate, kill switch `COLLECTIONS=off`, migration upgrades a populated media.db |
| P2 | `/media/collections` grid + collection page, after B. picks the options page | A-Z, sorts, filters, empty state, friend front; no ids in the HTML; smoke test; budget numbers |
| P3 | Request missing from the collection page | The button creates one Seerr request through the existing path; pending shows "Requested"; a friend's goes to approval; a double click does not double-request; no request for a film already owned or pending |

## Tests
The three phase lines above in `tests/hub/test_media_collections_jy266.py`, plus: a single-film collection is hidden by
default (Question 1); a year range ignores unreleased films with no date; the page makes no network call on render.

## Accept checklist
- [ ] The grid shows B.'s real franchises on web, iPad and phone with correct counts.
- [ ] A collection page dims the missing films and requests one successfully (on the preview, Seerr test mode).
- [ ] Nothing slower: numbers in the PR.

## Out of scope
TV shows' "collections"; user-made lists; auto-requesting a whole collection; collections B. owns no film of.

## B.'s picks (2026-10-29)

B., 2026-10-29: "I like A for both options." (read by the orchestrator as the recommended A answers; B. to be told this assumption)
Picks: 1A, 2A, 3A, 4A. The grid options page is still to come.

## Questions for B.
1. **Single-film collections.** A) Hide them, with a filter to show them (recommended). B) Show all.
2. **Request all missing.** A) One film at a time only for v1 (recommended). B) A "Request all missing" button with a confirm.
3. **Where in the nav.** A) A tab in the Movies area beside Library and Discover (recommended). B) Its own top-level Media tab.
4. **TV.** A) TV shows owned films only, read-only (recommended). B) Same as web.
