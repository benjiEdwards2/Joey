# JY-193 TV title shelves on-server only, the TMDB title page as a request page, the person page on the TV

Status: building
Size: M
Live risk: none
Area: hub/templates (`_film_shelves.html`, `media_film.html` guest TV branch, `media_person.html`; one `data-first` attribute in `_request_block.html`, outside the listed files - the Request anchor lives there), hub/static/tv.css (a commented "JY-193" block), tests/hub
Needs: JY-192 (U6, `media_film.html` + `tv.js`), JY-188 (density B), JY-248 (nav) - all on origin/main
Options page: `JoeyTV\mockups\tv-v2\01-title.html` (screens 1 and 4; shelves option A), plan row U7 in `JoeyTV\TV_UI_PLAN.md`

## Problem
TV_UI_EVALUATION_2026-10-23:
- **P2** (S1): the friends' title page keeps the **Similar** and **Recommended** rows of 20 TMDB titles, all captioned "Not on server". A friend opens one and lands on a TMDB title page with nothing to play.
- **D1** (S1): that TMDB title page (a title not on the server) shows no Play, "+ Season 1 · 60 episodes · Not in library" rows, then Similar + Recommended again: the friend wanders TMDB with nothing to watch. 12 nodes outside the safe area, 28 low-contrast.
- **N1** (S2): the person page has no TV rule. A 330 px round headshot fills the top, the name and role hide under the top bar, an "On server" shelf of 1, then "Everything else · Films" grids of TMDB titles (back to D1).

## Options and the pick
B.'s Gate 1 pick, 2026-10-25: **"2A"** (title-page shelves for friends show on-server titles only). Shelves option A of `01-title.html`: one shelf, "More on Joey" (`01-title-movie-shelvesA.png`). The TMDB page follows screen 4 (`01-title-tmdb.png`, `01-title-tmdb-requested.png`).

## Acceptance criteria
TV mode = `tv_mode(request)`; friend = `guest(request)` (the media front). Every change below is behind **both**. Desktop and phone (TV mode off), and the private front, render as before. The on-server filter is template-side, inside the TV + friend branch; it is not shared, so nothing changes off the TV.

1. **Shelves (P2, pick 2A).** On a friend's TV title page, `_film_shelves.html` draws ONE shelf, "More on Joey": the Similar then Recommended rows that are on the server (`r.on_server`), each title once (by href). Caption: title, then the year. No "Not on server" word, no off-server card. No shelf when none are on the server. Posters ask `h=600` (the JY-189 warm size), so they come from the disk cache.
2. **TMDB title page (D1).** A friend's TV page for a title that is not on the server (`film.t`, not `film.on_server`, not an episode) is the request page: the header carries `tv-reqpage`; poster 220 px beside the title, the facts line "year · Film / TV · genres · Not in the library yet", the synopsis (3 lines), "Not on Joey yet, so there is nothing to play.", then **Request** and **Back**. No Trailer, Watchlist or Rate button, and nothing below the hero (seasons, shelves, details, cast are hidden).
3. **Request focused first.** The hero's Request button carries `data-first` only on the TV request page (TV mode, media front, white primary, an off-server title, not an episode; review 2026-10-25 narrowed it, a test pins it), so tv.js focuses it on load. After a request the block says "Requested — waiting for approval" and Back is the one control, so it takes focus. Back is a `<button>` (`history.back()`): tv.js Back memory keeps links only, so it never steals the focus from the confirm step.
4. **Person page (N1).** In TV mode for a friend: a compact head (120 px round headshot beside the name, 44 px name, facts, a 2-line bio, no "More"), then the "On server" shelf (posters `h=600`). The "Everything else · Films / TV" grids are not drawn (pick 2A: friends see on-server titles only). With nothing on the server: "Nothing with <name> is on Joey yet." The head and the shelf fit one 960x540 screen, so the first poster's focus does not scroll the name under the top bar.
5. **No live calls on render.** The changes are template and CSS only: the TV friend page makes exactly the upstream reads the non-TV friend page makes (a test counts the Seerr calls).
6. **CSS.** All new rules sit in one commented `/* ==== JY-193 ... ==== */` block in `tv.css`, every selector under `html.tv`; no hover rule; nothing under 18 px; `control-surface.css` untouched.
7. **Tests:** `tests/hub/test_tv_shelves_tmdb.py` (red first): shelves filtered + "More on Joey" + h=600 for the TV friend; non-TV friend and private front unchanged; TMDB page request layout, `data-first` on Request, Back button, requested state; person page TV layout and non-TV unchanged; Seerr call counts equal TV vs non-TV; the CSS block. Hub suite green.

## Data
None. No snapshot, schema or migration change. Reads `film.shelves[].rows[].on_server` (hub.media_film `_on_server`) and `person.shelf` (hub.media_person) as they are.

## Performance budget
Item page p95 <= 150 ms unchanged: a Jinja filter over at most 40 rows. Images: shelf and person posters ask `h=600`, the size `media_warmup` already warms for library titles - on-server titles only, so a first TV view is a disk-cache hit. Not timed here (machine rule; the orchestrator's full check).

## Device check (the grouped TV run)
`tv_ui_capture.py device --only title_movie,title_tmdb` on the TCL:
- `title_movie`: images settle in under 3 s (`images_ms` < 3000), the shelf reads "More on Joey" with on-server posters only;
- `title_tmdb`: `outsideSafe 0`, **Request focused** on load (OK opens the confirm step; after Confirm, "Requested — waiting for approval" with Back focused);
- the person page: name visible under the top bar with the first poster focused.

## Out of scope
The "Request chips" shelf (option 2B); private-front and phone shelves; Discover; the series Seasons / Episodes shelves (JY-192); tv.js (unchanged: `[data-first]` already leads its first-focus rule).

## Accept checklist
1. On the TV as a friend, a film on Joey: one "More on Joey" shelf, every card on Joey, no "Not on server".
2. A title not on Joey (from Discover): poster, title, "Not in the library yet", synopsis, Request focused, Back. OK -> confirm -> "Requested — waiting for approval", Back focused; Back returns to Discover.
3. A person page from a film's cast: name and headshot visible, "On server" shelf, no TMDB grids.
4. Desktop (1440) and phone (390) title, TMDB and person pages look as before.

## Questions for B.
None.

## Shipped notes
