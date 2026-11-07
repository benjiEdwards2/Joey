# JY-303 Discover "See all": a full grid with filters and Load more

Status: phase 1 shipped (#333 d746293, live 1c8b37e 2026-11-07; Sweep 38 Accept); phase 2 not started
Size: M
Live risk: none (Seerr reads only, through the existing cached read path)
Area: `hub/media_discover.py`, `hub/guest.py` (one allow-list row), the Discover templates (`media_discover.html`,
`media_discover_all.html`, `_discover_*.html`, `media_discover_guest.html`, `_guest_discover_*.html`,
`_guest_req_dialog.html`, `media_service.html`), `hub/static/control-surface.css` + `hub/static/tv.css` (grid and See all
only), `hub/static/tv.js` (focus after Load more only), `tests/hub`
Needs: none
Options page: https://claude.ai/artifact/5QyS81ugDMYsxksmwBcftx (`JoeyTV/review/JY-303/options.md`)

## Problem
B. 2026-11-02: "I would like to be able to go into similar topics like I can on Seerr. Not just see only a few and no
more. Are you able to provide an all option or let me browse with more detail." Today every Discover shelf reads
Seerr's page 1 only and stops at 20 titles; there is no "See all" and no page with more.

## Options and the pick
B. 2026-11-06 (picker): PUSH, with the defaults: option B phased (A first, topics second), Load more on every
platform, all six filters, genres + keywords in phase 2, friends on the TV get the same grid.

## Change (phase 1 = option A)
- Every shelf on Discover (Trending, Popular films, Popular TV, Upcoming films, Upcoming TV) and on a service page gets a
  "See all" link in its heading. The friends' Discover grid and their TV Upcoming shelves get it too.
- One shared grid page, `GET /media/discover/all`, opened with the shelf's preset (`?shelf=<id>`, or the filters for a
  service shelf). A filter bar: Films / TV (Films & TV, Films, TV), Genre (once Films or TV is picked), Year, Sort
  (Trending, Popular, Top rated, Newest, Coming soon), Service (the 13 Discover services), Hide what is on Joey.
  A change reloads the grid (htmx; an Apply button without JS).
- Load more fetches the next 20 (Seerr `?page=N`) and adds them under the grid; the URL follows (`page=N`), so a
  refresh or Back shows pages 1..N again (at most 10 re-read on a full load). No button on the last page.
- Desktop and phone: the web poster grid with the watchlist "+" as on Discover. Friends (web and TV): the request grid
  with the friend's state chips and the request panel, as on the friends' Discover. On the TV the "See all" links are
  focusable (`html.tv .sechead a.seeall`; other `.sechead a` stay hidden), and after Load more the first new poster
  takes the focus.

## Seerr reads (checked against the `tests/hub` fakes and the code, not a live server)
| Read | Already used live? | Note |
|---|---|---|
| `/api/v1/discover/trending`, `/movies`, `/tv`, `/movies/upcoming`, `/tv/upcoming` (page 1) | yes (Discover shelves) | page 1 of an unfiltered preset reads the shelf's own path |
| the same with `?page=N` | no | the fakes answer `{"page", "totalPages", "results"}` (Seerr's shape); not probed live |
| `/discover/movies` and `/discover/tv` with `sortBy`, `primaryReleaseDateGte/Lte`, `firstAirDateGte/Lte`, `voteCountGte`, `watchRegion` + `watchProviders` | yes (service pages) | |
| `/discover/movies` and `/discover/tv` with `genre=<id>` | no | not probed live |
| `/api/v1/genres/movie`, `/api/v1/genres/tv` -> `[{id, name}]` | no | 24 h restart-proof meta read, 3 s, the last list kept on failure; no list hides the Genre filter |

The "no" rows need one look on B.'s Seerr at accept (open a See all, Load more, pick a genre).

## Acceptance criteria
1. Each of the five Discover shelves has a "See all" link to `/media/discover/all?shelf=<id>`; each service-page shelf
   has one carrying `service=<id>`; the friends' Discover grid heading and TV Upcoming shelves have one.
2. The grid page shows page 1 of the shelf (the same titles as the shelf), the filter bar set to the preset.
3. Load more (htmx) returns the next page's posters only plus a new Load more for the page after; none when
   `page >= totalPages` (or 500).
4. `?page=3` on a full load shows pages 1-3 (de-duplicated), capped at 10 pages.
5. Each filter changes the Seerr read as in the table above; Films & TV with a filter reads films and TV and alternates
   them; Hide what is on Joey drops Available / Partly available titles.
6. Bad values (unknown kind, sort, genre, service, a year out of range, page < 1) fall back to defaults, never a 500.
7. Seerr down: "Discover unavailable", no Load more, no 500 (reads wait 3 s, a failure is remembered 60 s).
8. Friends (media front): the page is on the guest allow-list; cells carry their request chips and open the request
   panel; no watchlist button.
9. TV: the See all links are shown and focusable; Load more is a focusable link; after Load more the first new poster
   is focused (tv.js). tv.css pins added in `tests/hub`.
10. No secret, Seerr URL or key in any page or partial.

## Data
No tables. New cached reads only (in memory 10 min per page path; the genre lists on disk as meta, 24 h).

## Performance budget
Discover page <= 3 s, never blocks: one page is 1-2 Seerr reads (3 s timeout each, in parallel) plus the cached genre
and provider lists. A full load with `page=N` reads N pages in parallel (cap 10). Measured at accept on the preview.

## Out of scope (phase 2, later)
- "Browse by genre" tiles on Discover (Films / TV tabs) and a genre page.
- "Related topics" chips from TMDB keywords.
- Film-page genres and keywords as links; "See all" on the film page's Similar / Recommended shelves (the film page
  template has its own builder now).
- Studios & networks (only if B. asks after using phase 2).
- See all on search results.

## Accept checklist
- Desktop: Discover -> See all on each shelf; change each filter; Load more twice; open a title and come Back.
- Phone: the same; the grid 3 across, the filter bar wraps.
- TV (friend signed in): Discover -> See all (the grid heading and an Upcoming shelf); Load more with the remote; the
  first new poster is focused; request a title from the grid.

## Questions for B.
None open (defaults taken).

## Shipped notes
