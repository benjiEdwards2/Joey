# JY-192 U6 Series and episodes on the TV

Status: review
Size: L
Live risk: none
Area: `hub/templates/media_film.html`, `hub/media_film.py`, `hub/static/tv.css` (one commented "U6" block), `hub/static/tv.js` (Rate strip + Back = series), `tests/hub/fake_jellyfin.py` (an Episodes read), `tests/hub/test_tv_series_episodes.py`, `tests/hub/test_tv_mode.py` (fake DOM gains `setAttribute`)
Needs: JY-187 (merged: Back memory, P5), JY-116 (merged: "Season 2 of 4" eyebrow). JY-188 (U2 density) lands first; this branch rebases onto it.
Options page: none: the design is the signed tv-v2 shell `Desktop\Claude\JoeyTV\mockups\tv-v2\01-title.html` (screens 2 series, 3 episode; PNGs `01-title-series-B`, `01-title-series-episodes`, `01-title-episode`, `01-title-episode-shelf`, `01-title-movie-B`, `01-title-movie-B-open`).

Source: `Desktop\Claude\JoeyTV\TV_UI_PLAN.md` row U6; findings S1, X1, X2, X3 in `Desktop\Claude\JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md`.

## Problem
S1: on a series title page the TV shows Seasons as a `<details>` list at 15 px, no art, and OK expands a 12 px episode list.
X1: the episode page's breadcrumb sits over the backdrop at 18 px and is the only way up; the shell's Back goes to the previous page, which may be the grid, not the series.
X2: the episode header is the desktop stack (eyebrow, "S01E01 · Name", then the series title at 44 px); on the TV the episode name should lead.
X3: below the hero, the season card and the episode rows have the same 12-15 px text as S1.

## Acceptance criteria
TV mode only (`html.tv`, `tv_mode(request)`). Desktop, phone and iPad render exactly as before.

1. **Seasons shelf.** On a series, season and episode page the TV shows a "Seasons" shelf instead of the `<details>` list: one 2:3 card per season with episodes on the server (the season's own Jellyfin image, `/img/jf:<season id>`, letters fallback), "Season 1" and "2 of 6 watched" under it, a progress bar (watched of aired) with its words in `aria-label`. The card links to the season page (`/media/item/<season id>`). On a season or episode page the page's season card says "This season".
2. **Episodes shelf.** Under it, "Episodes · Season N" (plus "Next episode E7 airs 26 Oct 2026" when the snapshot has it): one 16:9 card per episode of the current season (season page: that season; episode page: the episode's; series page: the next episode's season, else the last). The still is the episode's Jellyfin Primary image through `/img/jf:<episode id>?h=400` (letters fallback). Caption "E3 · Name", then the runtime (and "23m left" in progress). A word chip on the still: "Watched", "Next" (the next to watch), "In progress", "Not aired", or "This one" (the episode page's own); a progress bar over the still foot for an episode in progress. Every colour has its word.
3. **OK on an episode plays it.** An aired episode's card is the Jellyfin hand-off link (the same public `/web/#/details?id=` link as Play) with `data-jf-id` = the episode id (shell route 1b), so OK hands that episode to Jellyfin. With no deep link (Jellyfin not reachable) or a not-aired episode the card opens the episode page.
4. **Episode hero (X2).** On an episode page the hero leads with the episode: the 16:9 still where the poster was, the eyebrow "Show · Season 1", the episode name as the title, "E3 of 6 · 43m · aired 28 Sep 2026", the episode synopsis (3 lines), then Play (the episode), Mark watched (only where the page already offers it: B.'s own session), Season (the season page), Rate.
5. **Back = series (X1).** No breadcrumb on the TV. On a season or episode page the shell's Back goes to the series page: `window.joeyTV.back()` replaces the page with the series (`location.replace`) and returns true, unless the previous page was that series, in which case it returns false and the shell goes back as before (JY-187 Back memory then puts the focus back). An open dialog, an open Rate strip and a Discover query are still closed first.
6. **Rating = Rate button (Gate 1 pick 1B).** On every TV title page (film, series, season, episode) the 1-10 chips are no longer always shown: a "Rate" button (star + "Rate", or "Rated 8") ends the button row and opens the existing rating UI (the same `/media/rate` picker, or the rated number + Undo) in a strip under the buttons, focus on its first control. Picking a number closes the strip, the button reads "Rated N" and keeps the focus. Back closes an open strip (focus to the Rate button). Off the TV the picker and the "Yours" pill are unchanged.
7. **Friends see only their own watch state.** Every watched / progress / next word on the shelves comes from the page's season list, which on the media front is read as the signed-in viewer (`/Shows/{id}/Episodes?userId=<viewer>`, cached per viewer, `media_item._ck`). Nothing on the shelves reads the household snapshot's `played`, plays or diary rows.
8. **No live call on render (rule 7).** The page emits `/img/jf:<id>` URLs only; the stills are fetched by the browser through the existing `/img` proxy and its disk cache. Rendering makes no `/Items/{id}/Images` call.
9. **Kept.** JY-116's "Season 2 of 4" eyebrow on a TV season page; JY-187's Back memory, Up to the current pill and P5 (Down from the buttons into an open strip = its first control); the nav row (JY-248) untouched.
10. **CSS.** All of it in one commented `U6 (JY-192)` block at the end of `tv.css`, no hover rule, no text under 18 px in the new rules, tokens from `:root` / the existing `--tv-*` variables.

Test changes (2026-10-25, builder): `tests/hub/test_tv_mode.py` - the JY-187 order check now finds `<div class="tv-rate"` (the strip gained `id` + `hidden`; the order assertion is unchanged), and the Back-memory node test reads its sessionStorage entry by name (`store['joeyTV.back']`) instead of "the first key", because tv.js now keeps a second key (`joeyTV.trail`). The fake DOM gains `setAttribute`. No assertion was weakened. `tests/hub/fake_jellyfin.py` gains `/Shows/{id}/Episodes` with per-user UserData.

Red-first check (2026-10-25): `tests/hub/test_tv_series_episodes.py` on the untouched code: 10 failed, 2 passed (the two guards: off-TV unchanged, no image call). After the build: 12 passed.

## Data
No table or migration. `hub/media_film.py` gains `tv_shelves(f, page_season, page_episode_id)` -> `f["tv"] = {"seasons": [...], "eps": {...} | None}`, a pure function of `f["seasons"]` (viewer-scoped), `f["next_ep"]` and `f["next_air"]`; `f["episode"]` gains `still` (`jf:<episode id>`). No new Jellyfin read: the episode list is the page's existing `/Shows/{id}/Episodes` read.

## Performance budget
Media item page, warm: p95 <= 150 ms. The shelves are a loop over data already built; measured in the grouped full check.

## Options and the pick
B.'s Gate 1 pick, 2026-10-25 in chat: "1B" (the rating on the title page is a **Rate button**, B, not a chip row). The rest of the design is the shell's screens 2 and 3 (no options there).

Placement note: the shell opens the strip above the buttons; here it opens under them, so the buttons do not move when it opens and JY-187's P5 rule (Down from the buttons = the strip's first control) still holds. Focus on open is the first control (chip 1), not the shell's chip 7.

## Out of scope
The series Play label ("Next to watch: S1 E3 ▶" stays; the shell says "Play S1 E3"), the hero scrim and density (JY-188 / U2), "More on Joey" shelves and the TMDB page (U7), the off-server seasons list (U7), the desktop breadcrumb and episode page, any shell (`tv/`) change.

## Accept checklist
Device check for the grouped TV session (orchestrator, `JoeyTV\scripts\tv_ui_capture.py`):
- `tv_ui_capture.py device --only title_series,title_season,title_episode` -> 0 `tiny`.
- Journey J6 on an episode still: on a series page, Down to the Episodes shelf, OK on an episode card -> the Jellyfin app plays that episode.
- On an episode page reached from Overview, Back -> the series page; Back again -> Overview.
- Rate -> the strip opens on 1; OK on 8 -> strip closes, button reads "Rated 8"; Back with the strip open closes it.

## Questions for B.
None open.

## Shipped notes
