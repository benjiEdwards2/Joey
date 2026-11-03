# JY-282 Remove the duplicate overview (films and TV)

Status: shipped (#300, live bf94e98, 2026-11-03)
Size: S
Live risk: none
Area: `hub/templates/media_film.html` (hero synopsis block and the `Overview` section), `hub/static/control-surface.css` (`.tl-syn`, `.tv-syn`), `tests/hub/`
Needs: none
Options page: yes, 2 options at desktop / iPad / phone / TV (the two positions in Question 1; B. asked "show me")

## Problem
B., 2026-11-02: "Remove two overview sections. Either have it there or leave it below the title above where it is closer."
TV: "Remove the overview at teh bottom as it should be in the section at the top."

## What the code does today
- Top: `media_film.html` draws the synopsis in the hero. On web and phone it is `.tl-syn` (2 lines, "more" expands); on TV it is `.tv-syn`.
- Bottom: the `Overview` section (`<h2 class="seclabel">Overview</h2>` then `<p class="overview">`, under `{% if film.overview %}`) draws the same text for web, phone and TV; it is not gated by `tv_mode`.
- On TV an episode page also draws `<p class="overview">` with the episode synopsis in the hero area (`tvm and film.episode.overview`).
- `tests/hub/test_media_episodes.py` pins the order Overview < Seasons < Cast < Where to watch.

## Acceptance criteria
1. Film, show, season and episode pages show the synopsis once, on desktop, phone and TV.
2. TV: the bottom `Overview` section is gone; the synopsis stays in the top section (B.'s TV words).
3. Web and phone follow the pick: A keeps the hero synopsis and removes the bottom section; B keeps the bottom section and removes the hero line.
4. The kept synopsis shows the full text on every device (A: the "more" toggle still works; the TV line is not cut mid-word).
5. A title with no synopsis draws no empty heading or gap.
6. No other section moves; the film series banner (`_film_collection.html`, which sits "directly under Overview") still follows the kept synopsis position without a gap.
7. Tests: one copy of the overview text per page on film, show, season, episode; the order assertion in `test_media_episodes.py` is updated to drop "Overview" (dated line here).

## Options (page to build)
- A. Synopsis stays in the hero, under the title and facts; bottom section removed (recommended: closest to the title, matches B.'s TV ask).
- B. Synopsis stays in the lower section; hero line removed. The hero is shorter, the first screen is more image.

## Data
`film.overview`, `film.episode.overview`. No change.

## Performance budget
Media item page warm p95 <= 150 ms (fewer nodes, no extra reads). Measured on the preview.

## Out of scope
Rewording the synopsis. Episode tile captions (`tl-epover`). Taglines.

## Accept checklist
- [ ] A film, a show, a season and an episode each show the synopsis once.
- [ ] TV page has no Overview at the bottom.
- [ ] Phone first screen still has Play above the fold.

## Questions for B.
1. Which position on web and phone?
   A. Under the title in the hero (recommended; same as the TV).
   B. In the lower section, hero line removed.
2. On an episode page, keep the episode synopsis only (recommended), or the show's too? A. episode only, B. both.

## Decisions
- 2026-11-03 (orchestrator, for B.): Q1 = A (synopsis under the title in the hero), Q2 = A (episode synopsis only).

## Test changes
- 2026-11-03: `test_media_episodes.py` `test_tv_page_order_overview_seasons_then_where_to_watch` and `test_off_server_tv_title_keeps_seasons_under_overview` drop "Overview" from the order (the section is gone, per the pick); both now also assert the synopsis appears exactly once.
- 2026-11-03: `test_episode_flow_templates.py::test_episode_sections_come_in_the_contract_order` and `test_media_item.py::test_episode_page_and_map` asserted the SHOW's overview on an episode page; per Q2 = A they now assert it is absent and the episode's synopsis leads.

## Shipped notes

## Shipped notes (2026-11-03)

Merged #300 on B.'s accept (B. 2026-11-03: "accept all, except 293 does not need 'everything else"), one deploy, live bf94e98.
