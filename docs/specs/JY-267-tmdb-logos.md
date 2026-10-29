# JY-267 TMDB title logos instead of plain text

Status: ready (2026-10-29)
Size: M (three phases, each S)
Live risk: none beyond a normal hub deploy (reads Jellyfin `RemoteImages` like the poster pass; writes only to the local poster store)
Area: `hub/media_posters.py` (a logo step beside `fetch_backdrops`), `hub/images.py` (`jfs:<id>/logo` ref), `hub/tv_home.py` + `hub/templates/media_film.html` + `hub/templates/_pagehead.html` (draw the logo), `hub/static/control-surface.css` (a few non-token lines), `tv/` only if the TV app draws its own hero text (phase 3 checks), `tests/hub/test_tmdb_logos_jy267.py` (new)
Needs: JY-262 (shipped; ranked backdrops and the poster store)
Options page: none (the screen is the existing hero with an image where the text was; a text fallback keeps it safe)
Date: 2026-10-29 (draft)

B., 2026-10-28: "Yes please, I would be keen to run that next." (the title-logos idea)

## Problem
Home's carousel and the title page hero show the title as plain text over the backdrop. Streaming apps show the
studio's own title artwork (a transparent PNG logo). TMDB holds these as `logos`; Jellyfin exposes them as
RemoteImages type `Logo`.

## What changes
- **Fetch (the poster pass, monthly per title like backdrops).** `GET /Items/{id}/RemoteImages?type=Logo&providerName=TheMovieDb&includeAllLanguages=true`
  through Jellyfin (same request form as backdrops, no new key). Films and series only; seasons and episodes use their show's logo.
- **Rank, language first (like posters).** The viewer-language pool, then English, then any other; within a pool more
  votes, then CommunityRating, then width. Art from image.tmdb.org only; a URL once. A logo is text, so unlike posters
  there is no "text-less first" rule.
- **Store.** The top one, fetched at TMDB `w500` (never `original`), kept as PNG with its alpha (SVG skipped: not
  rendered the same on TV). In the poster store beside the posters: `<id>/<ver>.logo.png` + a `logo` pointer; `ver`
  hashes the source URL and size, so a new pick is a new `&v=` URL (cache-bust, as backdrops). A title TMDB no longer
  has a logo for is cleared. Survives a poster re-render.
- **`/img`.** `jfs:<id>/logo` serves the stored file when `&v=` is its published version (HIT_CACHE); otherwise the
  caller draws the text. No network on render; no Jellyfin fallback (Jellyfin's own Logo image is not requested).
- **Where it draws.** Home carousel and hero (TV and web) and the title page hero (film, series; season and episode
  pages use the show's). A logo replaces the title text; the `<h1>` and alt text stay the title (screen readers, search).
- **Fallback.** No stored logo, a failed load (`onerror`), or `POSTERS_LOGOS=off`: today's plain text, no layout jump
  (the logo box is the text box's height).

## Size budget
- File: 500 px wide PNG, normally 15 to 60 KB; refuse over 250 KB (draw text instead, flag in the pass log).
- Store: about 40 KB x 1,500 titles = about 60 MB on the NAS, local disk only.
- Render: the choice reads local store pointers only (page budgets in `CLAUDE.md` unchanged: item page p95 <= 150 ms, Home warm <= 50 ms). Pass work stays inside the existing memory gate and backoff; joey-hub <= 200 MiB.

## Per surface
| Surface | Draws | Size |
|---|---|---|
| Web home carousel and title hero | logo, left-aligned over the scrim | max 60 % width, max 120 px tall |
| Phone | same, centred under the backdrop | max 70 % width, max 90 px tall |
| TV (Home hero, title page) | logo in place of the hero title | max 40 % width, max 160 px tall; never upscaled past 1.5x |

Logos are mostly white or coloured on transparent: the scrim already behind the text keeps them readable. A dark logo
on a dark scrim is the known weak case (Question 2).

## Phases
| # | Step | Verify |
|---|---|---|
| P1 | Rank + fetch + store + `jfs:<id>/logo` in `/img` | Ranking cases (language, votes, width, TMDB only, dedupe, no logo), w500, size cap, monthly, cleared, survives re-render, switch, hostile ref |
| P2 | Web + phone: carousel and title hero draw the logo, with fallback | Page tests with and without a stored logo, `onerror` text path, `<h1>` unchanged, friend front, budgets measured |
| P3 | TV: Home hero and title page (+ `tv/` change only if the app draws its own text) | Same page tests on the TV front; if `tv/` changes, a TV release and its own checklist |

## Tests
`tests/hub/test_tmdb_logos_jy267.py`: the three phase lines above, plus: no network on render; a friend sees only logos for
titles they can see; the store file is never served without a matching `v`; a 300 KB logo is refused; an SVG is skipped;
a smoke test for each changed route.

## Accept checklist
- [ ] Home carousel and a title page show a logo for five titles B. knows, on web, iPad, phone and TV.
- [ ] A title with no logo still shows clean text.
- [ ] A dark logo is readable (or Question 2's fix is applied).
- [ ] Nothing slower: numbers in the PR.

## Out of scope
Season or episode logos; animated logos; a user-chosen logo; Discover and request pages for titles not on Joey (the cached Seerr body has no logo list).

## B.'s picks (2026-10-29)

B., 2026-10-29: "I like A for both options." (read by the orchestrator as the recommended A answers; B. to be told this assumption)
Picks: 1A, 2A, 3A, 4A.

## Questions for B.
1. **Source of the logo list.** A) Jellyfin RemoteImages, no new key (recommended). B) TMDB directly with a key.
2. **Dark logos on the dark scrim.** A) Do nothing now; fall back to text for a title only if B. flags it (recommended). B) Detect a mostly-dark logo and draw text instead.
3. **Language.** A) Viewer language, then English (recommended). B) English only.
4. **Phone title page.** A) Logo replaces the title (recommended). B) Logo above, title text kept below.
