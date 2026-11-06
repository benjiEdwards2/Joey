# JY-316 TV shows 2.3: season page with progress in words, Mark season watched, season cast and scores

Status: building, round 2 (B. 2026-11-06, Sweep 34; round 1: B. 2026-11-04 on Plan 2 phase 2.3: "Only the chips. No need for that view.")
Size: M
Live risk: none (template + page data; one extra small SELECT; no schema change, no new network call)
Area: `hub/media_film.py` (`tv_shelves`, section 5 your rating, `_sections` cast), `hub/media_db.py` (season mean), `hub/templates/media_film.html` (Episodes row head, Scores card), `hub/templates/_rate.html` (`avg_pill` words), `tests/hub/`
Needs: JY-290 (shipped). Must not overlap JY-317 (show pages take the movie chips, cast tiles, scores column, File drawer): it shares `media_film.html`, so the two are never in flight together.
Options page: no (pieces reuse existing looks; Questions below carry defaults)

## Problem
Plan 2 phase 2.3 (JY-287): the season page should say where you are in words, let you mark the season watched, show the season's cast and the season's scores. The season chips stay the only season selector: no "this / all seasons" pill and no all-seasons view.

## What the code does today
- Route: `GET /media/item/{jf_id}` (`hub/media_film.py`, line ~1508) with a Jellyfin season id. One template for film, show, season and episode: `hub/templates/media_film.html`. `_jellyfin_side` sets `page_item` = the season and `item` = its series (`base`); `season_page = page_item.kind == "season"`. JY-289 gives it the season's own poster and drops directors.
- Chips: the "Episodes" row (`section.tl-eps`, JY-269 P2) on web and phone: `.tl-chips` = one chip per season from `film.tv.seasons` (`tv_shelves`), the page's season lit; Sonarr-only seasons as dimmed chips (`.tl-chipdim`, JY-290). Head line after the chips: `shown.sub` (= the season's `watched_text`, "3 of 6 watched", built in `media_item` season read) + `ws.state_word` (Sonarr, "5 to come · next airs 2 Nov"). Then the episode tiles with state word, `ef.rowrate`, Play and per-episode Mark watched. The TV draws its own row (`section.tv-eps`, `.tv-seasonchips`, chips carry the IMDb "8.2 avg", `p.tv-seasonsub` = the same `shown.sub`).
- Mark season watched ALREADY exists on the season page: JY-290 moved `wa.season_toggle(ws, ...)` (`_resume_acts.html`) beside the chips (`.tl-seasonacts`). It posts to `POST /media/resume/{season_id}/watched|unwatched` with `scope=season`, `show`, `season`, `back` (`hub/media_resume.py`); the flash key `season-watched` reads "Season marked watched". Owner-gated server-side: `f["watch_owner"] = owner if owner == "you" ...` (B.'s views only; friends and her view never get write toggles). Not drawn on the TV.
- Next episode: `f["next_ep"]` is show-wide (`episode_nav`, "S2 E5" code); nothing names the next unwatched episode of the shown season.
- Cast: `_film_cast.html` from `f["cast"]` = `_cast(raw, people)`: the SHOW's TMDB credits from the Jellyseerr title body (deferred part "cast"), else Jellyfin's series Actors. Same list on show and season pages; no season credits are fetched anywhere (no `/season/{n}` credits call in hub/ or connectors). Episodes in the cached season list carry `people_names` (all People names, no type or headshot). Web and phone draw circles (`.castsec`; `.casttiles` 2:3 is movie-only, JY-280). TV draws 2:3 `tvt.person` tiles (JY-323: 2:3, two-line names, pinned in `tests/hub/tv_css.py`).
- Scores: web show and season pages draw the `.stats.numbers` Scores card (`tvweb`): `_film_scores.html` (IMDb / RT / MC upstream, the show's) + `ts.own` (TMDB) from `_title_scores.html`, then Yours. On a season page `key_item = ep or item` = the SERIES, so the Rate button and "Yours" pill rate the whole show, not the season. JY-288 `media_db.show_averages` (mean of your season ratings, else episodes) runs on show pages only (`show_page`); its spec kept season pages unchanged. The IMDb per-season episode mean is already loaded in `film.ratings.seasons[n].avg` (`media_episode_ratings.build_ratings`), shown only on TV chips.

## Change (smallest reuse)
a. Progress in words. `tv_shelves` adds to each season card `next_code` = "S{n} E{k}" of the first aired, unplayed episode (from the episodes it already walks; None when all aired are watched). Web/phone head line becomes "4 of 10 watched · next S2 E5 · <state word>"; all watched: "10 of 10 watched" + state word. Same row, so the show page's Episodes row shows it too (Q3).
b. Mark season watched: no new action. Keep `wa.season_toggle` beside the chips; confirm it shows on season pages for owner "you" only, redirects back to the season page with the flash. Only change if a test shows a gap.
c. Season cast: in the `_sections` "cast" branch, on a season page order the show cast so actors named in this season's episodes (`people_names`) come first and drop the rest, falling back to the full show cast when fewer than 3 match (Q2). Pass the season's names in the `ctx` dict so the page and the part request (`/media/item/{id}/part/cast`) agree. No TMDB season-credits call. Web keeps circles until JY-317 (Q4); TV keeps JY-323 tiles.
d. Season scores. On a season page `key_item = page_item` (the season: `_rating_for` already returns the `jf:<season>` key, level season, title "Show · Season N"), so Rate and "Yours 8" are the season's (Q1). Not rated: new `media_db.season_average(show_title, n, owner)` = mean of the owner's episode ratings whose title starts "Show · S{nn}E" (one SELECT, the JY-288 prefix rule), drawn with `rate.avg_pill` (its hidden words take a label: "Your episodes average"). Add one pill for the IMDb season mean from `film.ratings` ("IMDb 8.2 avg", `ts.score`, unlinked). Show-level IMDb / RT / MC / TMDB pills stay as now. Placement: the existing Scores card (the movie-style column is JY-317).

## Platforms
- Desktop and phone: a, b, c, d as above.
- TV (html.tv): c (same `f["cast"]`) and the Rate button rating the season (d) come for free; no TV template or tv.css change; `tests/hub/tv_css.py` pins unchanged. Progress words, the season toggle and the score pills stay web-only (JY-307 owns the TV look).

## Acceptance criteria
1. Season page (web 1440, phone 390): head line reads "n of m watched · next S2 E5" (or no "next" when all watched) with the Sonarr word when present.
2. Owner "you": "Mark season watched" beside the chips marks the season, returns to the same season page with "Season marked watched"; label flips to "Mark season unwatched". Her view, friends and the guest front: no toggle.
3. Season cast lists actors from this season's episodes first; under 3 matches = the show cast; no extra request in the server log on render.
4. Rate on a season page saves a season rating (key `jf:<season id>`, level season); Scores card shows "Yours 8", else "Yours 8.3 avg" from that season's episode ratings, plus "IMDb 8.2 avg" when loaded.
5. Show page: unchanged except the progress line (Q3); JY-288 show average unchanged.
6. TV season page: renders, no new sections, TV audit passes; tv_css pins unchanged.
7. `tests/hub` and the full tree pass.

## Data
`film.tv.seasons` (+ `next_code`), `film.seasons[*].episodes[*].people_names`, `film.ratings`, media.db `rating` (owner, level episode, title prefix). No schema change.

## Performance budget
Media item page warm p95 <= 150 ms. No new network call on render (no TMDB / Jellyseerr season credits; cast filter uses the cached season list). One extra SELECT only on an unrated season page.

## Tests to add or change
- New `tests/hub/test_season_page_jy316.py`: progress words (next / all watched), cast filter + fallback, season rating key, episode mean, IMDb season pill, owner-only toggle on the season page, TV page has no new web blocks.
- `test_season_state.py` (head line now carries "next"), `test_media_watched.py` (season toggle on the season page), `test_season_page_jy289.py` (still passes), `test_show_average_jy288.py` (season mean rule + "season pages unchanged" test updated, dated), `test_media_film_scores.py` (season Scores card), `test_media_film.py` / `test_tv_p3_jy259.py` (cast list), `test_media_resume.py` (unchanged unless the flash moves). Each change dated in this spec.

## Out of scope
An all-seasons view or "this / all seasons" pill (B.: chips only); the part-of banner; season guest-star tiles with headshots (needs data we do not hold); TMDB season credits; web cast tiles and the movie scores column on show pages (JY-317); TV look (JY-307); season air-date range and overview fallback.

## Accept checklist
- [ ] Season page says "n of m watched · next S2 E5".
- [ ] Mark season watched works from the season page (you only).
- [ ] Season cast looks like this season's actors.
- [ ] Rating on a season page rates the season; season scores show.
- [ ] TV season page unchanged apart from cast order and season rating.

## Questions for B.
1. Rate button on a season page rates: A. the season (default; matches the "Yours" score), B. the whole show as today.
2. Season cast: A. show cast filtered to actors in this season's episodes, full show cast when under 3 match (default; no new fetch), B. show cast unchanged, C. TMDB season credits (one new cached fetch, later item).
3. Progress line "· next S2 E5": A. on season and show pages, web and phone (default; same row), B. season page only, C. also on the TV.
4. Web cast look on the season page: A. circles until JY-317 does show and season together (default), B. 2:3 tiles now on season pages only.

## Round 2 (B. 2026-11-06, Sweep 34)
B.: "We agreed that the seasons would be along the row of pills. And shows would be under that. Allowing the removal of the all seasons row which is not needed." Also "Please change all headshots of cast members to 2:3. Stop placing them in circles. For shows and movies." (Q4 answered "Okay" = 2:3 now) and "Remember the rating column sitting on the right hand side as a smaller side bar. Can you please implement that. Instead of having it as a row of things." Built together with JY-317 and JY-283 on PR #328 (spec: `docs/specs/JY-317-show-page-movie-parts.md`).

Change (web and phone; the TV is not touched):
- R2a. The Episodes row's season chips (`.tl-chips`) are the one season selector on show and season pages, the episodes directly under them; "n of m watched · next S2 E5" and Mark season watched stay beside the chips. The season page's second seasons row (the hero's S1 / S2 switch, `ef.seasonswitch`, `.seasonseg`) is removed. The part-of banner's "All seasons" button stays: it is the season page's only link to the show page (no chip leads there). The episode page's carousel head (JY-315, "Season N" + S1 / S2) is not a show / season page and stays.
- R2b. Cast on film, show and season pages: 2:3 portrait tiles (`.casttiles`), 4 px corners, names on up to two lines, the role on one line; about 3.5 across a 390 phone (the row scrolls sideways), 88 px from 640 (about 8 across the 784 px main column at 1440, beside the scores column; 104 / 120 px on the JY-308 wide monitors).
- R2c. Scores as a right-hand column: JY-317.

### Round 2 acceptance criteria
1. Season page (1440, 390): one seasons row (the chips) with the episodes under it; no `.seasonseg` on the page.
2. Film, show and season cast are 2:3 tiles; no `border-radius: 50%` on any web `.castsec` rule.
3. TV pages unchanged; `tests/hub/tv_css.py` pins unchanged.

Tests changed (2026-11-06, round 2 R2a / R2b): `test_episode_flow_templates.py` season-head switch tests now assert the switch is gone from the season head; the JY-269 circle-cast CSS pin becomes the 2:3 tile pin.

## Shipped notes
