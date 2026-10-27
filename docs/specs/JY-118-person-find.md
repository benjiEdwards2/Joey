# JY-118 Guest / crew names link to the person page

Status: shipped 2026-10-27
Size: S
Live risk: none (one read-only Seerr search per tap; no write)
Area: `hub/media_person.py`, `hub/media_film.py`, `hub/guest.py`, three templates, tests
Needs: none
Options page: `JoeyTV/review/decisions-2026-10-27/options.md` (JY-118: A recommended)

## Problem
On episode pages, guest names link nowhere, and crew names (episode crew, and the show's Crew and "Directed by" cards when the page has no TMDB id) link to `/media/discover?q=<name>`. That search lists titles only: `media_discover._row()` returns None for people, so the person is never reached. Jellyfin People carry no TMDB id, so the page cannot link straight to `/media/person/<tmdb>`.

## Acceptance criteria
1. `GET /media/person/find?name=<name>` runs one Seerr search, takes the first result of type person whose name matches (case and spacing ignored; titles and near-names skipped) and answers 303 to `/media/person/<tmdb>`.
2. No person match, Seerr unset or down: 303 to `/media/discover?q=<name>`. Empty name: 404 (nothing to look up). Never a 500.
3. The name is capped at 100 characters. The route is declared before `/media/person/{person_id}` so "find" is not read as an id.
4. Episode guests and episode crew link to the find route. The show / film Crew and maker cards use it where they had the Discover-search fallback. A person with a TMDB id still links straight to their page.
5. Nothing is looked up on render: a page with guests and crew makes no search call.
6. Friends: the route is in `GUEST` (GET only). It reads Seerr search only, so it shows media data and nothing of the household.
7. Existing tests that pinned the old `/media/discover?q=` link now pin the find link (dated here: 2026-10-27, because the link changed by design).

## Data
No tables. One Seerr read (`/api/v1/search?query=`) per tap. No cache: taps are rare, and a search carries request state, so it is not meta.

## Performance budget
No page render gains a call. The tap runs one Seerr read (8 s timeout, as Discover search) and redirects.

## Options and the pick
Option A (recommended). Option B (a Discover-search link for guests) and C (leave it) were not built. B.'s pick: pending.

## Out of scope
Fixing `_row()` to return people (the Discover grid is title-only by design). TMDB person ids from Jellyfin. Caching the name lookup.

## Accept checklist
Open an episode page: tap a guest and a "Directed by" name; each lands on the person's page. Try a name Seerr does not know: it lands on the Discover search for it.

## Questions for B.
None (B. picks A / B / C on the options page).

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #220, squash-merged as `102cafd` (102cafd57184744a642c7aab2d3dc855d1a47dc2).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-27: Accept every recommendation on the Joey decisions page: merge the 4 built-ahead PRs, drop the 7, apply the rest as recommended."
- Follow-ups: none
