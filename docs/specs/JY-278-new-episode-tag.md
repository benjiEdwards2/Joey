# JY-278 Recently added: the "new episode" tag on show tiles

Status: review (PR open, reviewer PASS 2026-11-05) (B. 2026-11-04 plan page: "Happy with new episode." -> tag by default, no switch; B. 2026-11-05: "continue running on the hitlist")
Size: S (one tile per show already shipped in JY-277 option B #313; only the tag remains)
Live risk: none
Area: `hub/media_home.py` (`added_rows`, show grouping), the Home / Overview shelf templates that render Recently added tiles (`_poster.html` or the JY-277 shelf partial), `hub/static/control-surface.css`, TV branch of the same tile (`_tv_tile.html` caption), `tests/hub/test_media_home*`
Needs: none (JY-277 B live 91c73ab)
Options page: none: the choice was made on the JY-287 plan page ("Happy with new episode.")

## Problem
B. 2026-11-02: "Recently added shows two Billions icons." and "Can you show a choice for either selecting a show with 'new episode' attached or just the show." JY-277 B gave one tile per show. B. 2026-11-04: "Happy with new episode." So: when the Recently added row's show tile stands for newly added EPISODES of a show that was already on the server (not a whole new show), the tile carries a small "New episode" tag ("3 new episodes" when the grouped rows count more than one), on desktop, phone and TV. A show that is new to the server as a whole carries no tag (the row sub-line already says Added X ago).

## Build
1. `added_rows` (or a sibling) keeps, per show tile, the count of grouped episode rows and whether the tile stands for a whole new show or new episodes (Jellyfin `latest` rows carry the item kind and `show_title`; an arr arrival "Billions · 3 episodes" carries its count in the title; a row whose kind is series/show = whole show, anything episode/season-shaped = new episodes). Expose `new_episodes: int` on the tile row (0 = no tag).
2. Tile template: when `new_episodes >= 1`, a small pill over the poster's bottom-left (same family as the existing watched check / "This one" chip), text "New episode" or "N new episodes"; TV tile: the same words in the caption line (no new overlay element on TV; the P3 16:9 tile keeps its logo/caption).
3. Correct poster and font: the grouped tile keeps the Jellyfin show poster and the standard caption font (B.: "only the full season one has the correct font and posters"); a test asserts the kept row is the Jellyfin series row when present.

## Acceptance criteria
1. Fixture with Billions (existing show) + 3 new episodes and a brand-new show: Recently added shows ONE Billions tile tagged "3 new episodes" and the new show untagged.
2. One new episode -> "New episode" (singular).
3. Desktop 1440, phone 390, TV 1920 shots of the row: tag visible and readable; TV audit passes.
4. The kept tile is the Jellyfin series row (poster + caption font as the other shelves).
5. `tests/hub` pass; full tree passes.

## Out of scope
A switch between "show" and "show + new episode" (B. picked the tag by default), Up next / Continue watching rows, the diary.

## Shipped notes
