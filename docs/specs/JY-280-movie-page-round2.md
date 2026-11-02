# JY-280 Movie page, round 2 (option A: right column)

Status: ready (B. picked A, 2026-11-03: "Movies round 2 I like the option A.")
Size: L
Live risk: none
Area: `hub/templates/media_film.html`, `_pagehead.html`, `_film_cast.html`, `_film_crew.html`, `_film_scores.html`, `_film_macros.html` (`sp`, `sitepills`, `makercards`), `hub/media_film.py` (`crew_for`, `file_panel`, `_makers`, owner gating near `media_db.owner_of`), `hub/media_person.py` (writer credits), `hub/static/control-surface.css` (`.hero-detail*`, `.castrow` / `.castcard` / `.castpic`, `.scorepill`), `tests/hub/` (`test_media_film.py`, `test_media_film_scores.py`, `test_media_person.py`)
Needs: JY-286 spec (where-to-watch logos; its logo row is placed here, not redone)
Options page: done (A picked; notes in `JoeyTV\review\JY-280-movie-r2\options.md`)

## Problem
B., 2026-11-02 (rows JY-280 to 285):
- JY-280: "make the poster larger, either taking up more of the left side and allow the main background picture to be larger in the back."
- JY-281: "remove the imdb, tmdb, and letterboxd referenced and place the links to click on them as the ones above. Linking the score from IMdb to linnk you straight to where the link below wanted to go."; "either in a right column or somewhere that is not front and center of the screen."
- JY-283: "Place the cast with nicer thumbnails of them above the scores section below the main section. Please use a similar box or 2:3 ratio as the poster scetions. Reducing the corner radius and making it a little boxier."
- JY-284: "maybe only those who want to find it could or only I can access similar features."
- JY-285: "Move the Director and writed to be at the top where you have the director. I would like to be able to go into the writer or director and see more of their work at a few touches of the button."
- JY-282 (one overview) and JY-286 (logos) are separate rows; option A needs both (see Needs).

## What the code does today
- Hero (`media_film.html`, `.hero-detail`): poster `.hero-detail-poster` max 260 px (62% on phone), backdrop `.hero-detail-bd` behind, "Directed by" maker cards (`_film_makers.html`, a deferred part) under the buttons. The overview shows twice: `.tl-syn` in the hero and an Overview section in `.filmbody`.
- Body is one column: `.stats.numbers` card (score pills via `sp()` with site-name labels, plus a `sitepills` link row), Awards, File section (`film.file` from `file_panel`, drawn for any viewer with a file), Crew (`_film_crew.html`, Director + Writer + others), Details, Cast (`.castrow`, 130 px cards, 8 px radius), Where to watch (`_film_providers.html`, names), shelves.
- `crew_for` already returns Director and Writer with TMDB ids (`_pid`); `/media/person/{id}` exists (`media_person.py`) but lists credits generally, not writer-specific.
- Owner: `media_db.owner_of(view)` gives "you" / "her" / a friend key; `guest(request)` is true on the friends' front. File data is in the page dict for every viewer today.
- The guest front draws no off-site links (`sites` is false for guests); TV mode (`tv_mode`) is a separate layout in `tv.css`.

## Acceptance criteria
Movie page only (`film.kind == "movie"`); TV, season and episode pages unchanged.
1. Hero: poster about 300 px desktop, 230 iPad, 170 phone (2:3), taking more of the left; backdrop taller and a different picture from the poster (fallback: Question 2).
2. One overview, under the title in the hero; the body Overview section is gone (done once with JY-282).
3. Director and Writer chips under the facts line; each is one link to `/media/person/<id>`, or `person_find_href` when there is no id. The old "Directed by" cards are removed for movies.
4. The writer chip opens a person page that lists their writing credits (writer jobs from combined credits); the director's page keeps directing. Existing person tests stay green.
5. Cast: 2:3 tiles, 4 px poster radius (existing token, no new `:root` value), in the left column under the hero, before Scores. Each tile links to the person page.
6. Where to watch: logos only, left column under the cast, built to the JY-286 spec (`docs/specs/JY-286-where-to-watch-logos.md`).
7. Right column (desktop, >= 1024 px): Scores, then Details, then the File drawer. Below 1024 px it stacks under the cast.
8. Scores show logo + number only, no site words; each is a link to that site's page for the film (IMDb, RT, Metacritic, Letterboxd, TMDB as the data allows; a site with no id shows the number unlinked). "Yours" keeps its Rate behaviour. The separate `sitepills` row is dropped.
9. File drawer: a closed `<details>` "File details", drawn only when the viewer is the owner ("you"). Friends, other household members and the guest front never get the drawer or its data in the HTML: tests assert the response body has no filename, size, bitrate, audio or release strings and no `filepanel`. Gate is server-side (template and page dict), not CSS.
10. Friends' TV and guest front: score numbers without links (no off-site links); no File drawer. `test_tv_*` stay green.
11. Layouts checked at 2560x1440 desktop, an ultrawide 3440x1440 (assumed, Question 1), iPad 1024, phone 390, and TV 1920x1080 as the render of a 4K panel (B.'s standing rule, 2026-11-03). No horizontal scroll at any size; the content stays centred with a sane max width on the wide screens; hero art does not stretch or blur.
12. No new request or upstream call on page load; budget below holds.
13. Tests: owner sees the drawer, friend and guest do not; chips link to person pages; score links go to the right site; no body overview; cast tile markup; existing film, scores and person tests green.

## Data
No new tables. Writer ids already come from `crew_for`; the person page needs writer jobs from the combined credits it already fetches (builder verifies). Score link URLs come from ids already on the page (IMDb, TMDB) and the existing `sitepills` logic. Provider logos per JY-286.

## Performance budget
Hub page p95 <= 50 ms; the movie page makes no new requests or upstream calls; backdrop stays `h=1280`, poster `h=600`; cast images lazy after the first row. Measured on the preview.

## Phasing
- P1 (one PR, <= 150 turns): hero (poster, backdrop, one overview, Director / Writer chips, writer credits on the person page) + cast tiles. Covers AC 1-5 and the hero part of 11.
- P2 (one PR, <= 150 turns): two-column body, logo-only linked scores, owner-only File drawer, JY-286 logo row placement, TV / guest handling. Covers AC 6-10, 12, 13 and the full width sweep for 11. Starts once JY-286 has landed, or takes its logo row as given.

## Out of scope
The TV-show page. Recommended: movie page only now; scores (JY-281), file info (JY-284) and Creator chips (JY-285) for TV titles follow once this ships, so the builder builds scores and the File drawer as shared partials. Also out: new score sites, JY-286 internals.

## Accept checklist
- [ ] Movie page at 2560, ultrawide, 1024, 390 and TV 1920x1080: big poster, one overview, chips, cast tiles, right column
- [ ] A friend's session shows no File drawer and no file text in the page source
- [ ] A score opens that site's page for the film
- [ ] The writer chip lists their other writing work

## Questions for B.
1. Ultrawide: is 3440x1440 right?
2. Backdrop when a title's only image matches the poster: blurred poster wash (builder default) or plain dark hero?
3. Cast length: top 8 and scroll (default) or 12?
4. Score sites: keep all five (default) or trim?

Defaults apply if unanswered. File drawer is owner-only, per "only I can access".

## Test changes (2026-11-03)
P1 (PR 296) changed existing tests where the spec changes behaviour (rule 4):
- `tests/hub/test_media_film.py`: film "Directed by" card tests became chip tests (person link, find fallback, Jellyfin fallback, chips under the facts line); headshot + initials checks moved onto the 2:3 cast tiles; JY-269 cast tests now find the film's `casttiles` section.
- `tests/hub/test_film_page_e4.py`: hero order now has the chips under the facts line instead of the makers after More.
- `tests/hub/test_film_quality.py`: no body Overview on a film; the order is Cast, File, Crew.
- `tests/hub/test_media_episodes.py`: film order is Cast, File, Where to watch (no Overview section).
- `tests/hub/test_media_partof.py`: renamed to `test_collection_banner_leads_the_film_body_after_cast_and_scores`; exact order Cast, Scores, banner, File, More on Joey.
- `tests/hub/test_media_follow_shows.py`: a film's director is a chip (still no Follow buttons).
- `tests/hub/test_media_tv_crew.py`: the film page shows chips, not a Directed by row.
