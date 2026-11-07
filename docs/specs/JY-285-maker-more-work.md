# JY-285 — Director and writer: more of their work (A on web, C shelf on the TV app)

Status: ready (B. 2026-11-06 on the options page: "Accept — A on desktop, tv etc if you click into it. C on TV app where we have the space underneath." q-1 "Default A with C shelf on TV", q-3/4/5 defaults)

## Goal
From a film, show, season or episode page, B. reaches more of a director's or writer's work in a few touches. Web (desktop, phone, and the TV *web* page): option A, the maker chips stay links to the person page, polished. TV *app* (`html.tv`): option C, a "More from <name>" poster shelf under the cast for each maker.

## What exists (do not rebuild)
- `hub/templates/_film_makers.html` renders Director / Writer / Creator chips (`.makerchips`) under the facts line on web title pages (JY-280, JY-316/317). TV keeps headshot maker cards.
- Person page `/media/person/<id>` (name search when no TMDB id): bio, On server, Films, Film series, Bonus, TV, awards, Follow, now also the awards carousel and "you may like" shelf (JY-292/294). Credits come from Seerr `person/<id>/combined_credits`, cached 10 min.
- Deferred loads on title pages use the existing HTMX `hx-trigger="load"` pattern (see the Where-to-watch logos and the JY-292 shelf for the 12 s deadline and "hidden when empty" handling).

## Build

### A. Web polish (desktop, phone, TV web)
1. Chips stay plain links. Same person as Director and Writer: one chip labelled "Director and Writer" (q-5), linking once.
2. Person page opened from a maker chip lands with "On Joey" (On server) first: pass `?from=<media id>` (or an equivalent small query flag); the page scrolls/anchors to the On server section when it has entries, otherwise to Films. No change for other entry points.
3. Back returns to the title page at the same scroll position (browser default; verify no `hx-push-url` breaks it).
4. No popover, no new fetch on web.

### C. TV app shelf
1. On `html.tv` title pages (film, show, season, episode), under the cast row and above Scores: one shelf per maker, heading "More from <name>" (one shelf "More from <name>" when the same person directs and writes). Up to 12 titles, films and shows together, newest first (q-3), each poster with an "On Joey" dot when the title is on the server (q-4). The title itself is excluded.
2. Loaded after the page draws (HTMX load trigger), never on render; one cached Seerr credits read per person; 12 s overall deadline; shelf hidden when empty or when Seerr is down. Friends' TV sessions: same behaviour (read-only, no request chips).
3. Focus: the shelf is reached with Down from the cast, Left/Right moves across posters, OK opens the title page; text at or above the 18 px TV floor; pins in `tests/hub/tv_css.py` if tv.css grows.
4. TV posters reuse the existing TV shelf tile (the JY-292 you-may-like TV tile or the Discover shelf tile), no new tile style.

## Tests
- Web: single "Director and Writer" chip when ids match; `from` flag lands on On server (anchor present) and falls back to Films; no maker shelf markup on web pages.
- TV: shelf markup present with load trigger on the four title pages; endpoint returns 12 newest titles excluding the current one, On Joey dot set from the library; empty / Seerr-down → empty 200 body; 12 s deadline; friend session gets the same read-only shelf.
- Full tree green: `python -m pytest tests -n 4 -p no:cacheprovider -q 2>&1 | tail -3`.

## Out of scope
Popover (option B), any change to the person page beyond the landing anchor, TV headshot card redesign.

## Done
PR on `jy-285-maker-shelf` from main; reviewer PASS with shots: web film page (1440, 390) chips, person page landing after a chip tap, TV film and show pages (1920) with the shelf, one shot with focus on the shelf.
