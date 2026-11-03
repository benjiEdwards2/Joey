# JY-281 Show page: scores and File drawer parity with the movie page

Status: shipped (#308, live pending, 2026-11-04)
Size: M
Live risk: none
Area: `hub/templates/media_film.html` (show / season branches only), `_title_scores.html`, `_title_file.html`, `_film_providers.html`, `hub/media_film.py` (`file_owner` gate extended to `tv`; per-episode file fold), `hub/static/control-surface.css` (reuse `.scorepill`, `.filedrawer`; no new tokens), `tests/hub/`
Needs: PR 301 merged (JY-280 round 2 phase 2: the shared `_title_scores.html` and `_title_file.html`, `file_owner`)
Options page: no (follows the accepted movie pattern, B.'s pick A on JY-280, 2026-11-03)

## Problem
B., 2026-11-02 (JY-281): scores for movies and TV drop the IMDb / TMDB / Letterboxd words, and a score links to the site. PR 301 did this for movies. The show page still draws the old pills and an always-visible File section.

## What the code does today
- Show and season pages share the non-film path of `media_film.html`. The Scores card (around line 263) is the old `.scorepill` block (`_film_scores.html` plus `sitepills()`: IMDb / TMDB / Letterboxd as named links, `sp-you` "Yours" pill) with no shared partial.
- The File section (around lines 396-412) is the inline `.filepanel` markup, always drawn when `film.file` exists. `media_film.py` empties `file` only for movies (`kind == "movie" and not file_owner(owner)` in PR 301); a show keeps its `file_panel` (total size, episode count, languages) for every viewer on the private front. `guest_controls` blanks only the badges.
- Providers: `_film_providers.html` draws "Where to watch"; JY-286 turns it into logos (web / phone only). The show page includes it after the body.
- Layout to keep (JY-269): backdrop hero, then the Episodes row first (season chips, `n of m watched`, 16:9 tiles), cast circles, More on Joey. TV mode (`tv_mode`) has its own shelves and is not touched.
- Yours score: the show page's own rating pill and the season average (JY-288, "Yours N avg") via `film.score` / `rate.rated_pill`.
- An episode page keeps its own file and ratings flow (`eflow`); it shares this branch.

## What moves
1. Show and season Scores card: replace the inline pills with `ts.upstream(sites)` and `ts.own(sites)` from `_title_scores.html` (logo + number, each one link to the site's page; no site words). `ts.own` already builds `/tv/<id>`; Letterboxd is skipped for `kind == "tv"` (it is movie-only). A site with no id shows unlinked.
2. Yours pill: unchanged, via `rate.rated_pill` showing the JY-288 "Yours N avg" figure; "Rate" until rated.
3. File: replace the inline File section with `tf.drawer(fp)`, closed under "File details", owner only. Extend the server gate: `kind in ("movie", "tv") and not file_owner(owner)` empties `f["file"]` and `facts.languages`.
4. Per-episode file info: an episode's file facts (size, audio, subtitles, file name) fold into the same drawer as a "By episode" list for the owner; they are not drawn on the episode tiles for anyone else. Season page: its drawer holds that season's episodes only.
5. Where to watch: place the JY-286 logo row on the show page; no provider words, JustWatch link on web, none on guest / TV.
6. Remove from the show branch only: the old named pills, `sitepills()` use, and the always-open File section. Movie and TV-mode branches stay as they are.

## Acceptance criteria
1. Show page: Scores shows logo + number links (IMDb, TMDB; RT and Metacritic unlinked) and no visible word IMDb / TMDB / Letterboxd; each logo has the site name as alt text.
2. A score link opens that site's page for the show (`/title/<imdb_id>/`, `/tv/<tmdb_id>`); a pill without an id has no href.
3. Letterboxd never appears on show or season pages.
4. The JY-269 order is unchanged: hero, Episodes row, then the rest; the Episodes row renders identically (existing tests green).
5. "Yours N avg" shows the JY-288 season-average figure unchanged; "Rate" still jumps to `#rate`.
6. The owner (private front, owner `you`) sees a closed "File details" drawer on the show, season and episode pages; opening it shows size, languages and the per-episode list.
7. Friends, guests and the TV never receive file strings: with a non-owner or guest request, the show / season / episode HTML contains no file name, size, bitrate, audio or subtitle track, and no `filedrawer` markup. Asserted by test on the rendered body for guest front, friend, "her" and `tv_mode`.
8. Guest front and TV carry no off-site score or provider links (`sites` false), as on the movie page.
9. Where to watch is logos only, alt = provider name, no link on TV and guest.
10. No new upstream call; the deferred `scores` and `providers` parts load as before; Hub page p95 <= 50 ms.
11. Colours, radii, spacing from existing tokens (`CLAUDE.md` rule 9); no new `:root` values.
12. Tests: rendered show with and without `sites`, owner vs non-owner vs guest vs TV file gating, no Letterboxd on tv, drawer closed by default, existing movie tests green.

## Data
None new. `film.file` already carries the show totals; the per-episode list is read from the Jellyfin episode data the page already fetches (no extra call). Nothing is stored.

## Out of scope
The TV-mode (Joey TV) show page and its shelves; the Episodes row; season ratings logic (JY-288); cast and More on Joey; new score sources.

## Accept checklist
- [ ] Show page: logos and numbers, no site words, each opens the right site.
- [ ] Only I see "File details"; a friend's and the guest view show none (checked on the preview).
- [ ] Episodes still lead; "Yours N avg" still there.

## Questions for B.
None; the movie pattern is the accepted direction.

## Shipped notes

## Shipped notes (2026-11-04)

Merged #308 on B.'s review-page answer (Accept, 2026-11-04 morning), live pending.
