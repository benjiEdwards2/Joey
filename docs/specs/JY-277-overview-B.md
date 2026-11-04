# JY-277 Overview restructure, option B (preview)

Status: preview branch `preview/JY-277-overview-B`, for B. to compare with option A. Covers JY-276 (pill carousel),
JY-278 (one tile per show) and JY-305 (a taller top on load) on the household web Home (`/a/<shelves area>`).
The media front (friends, TV) is unchanged.

## What it does

- The Home head is the plain band with the Media tabs. Below it, the carousel fills about the top half of the screen:
  pills (New / Continue watching / Not yet watched), then one wide centred slide with its neighbours bleeding off the
  left and right edges. Slide title is the stored TMDB logo when there is one (JY-267), else the words.
- Pills swap the carousel through htmx (`GET /a/<id>/carousel?s=`, outerHTML on `#home-car`, URL pushed as
  `/a/<id>?s=`); the plain href works without script. The pick is remembered in the `media_homepill` cookie.
  On load: `?s=`, else the cookie, else Continue watching when there is something to continue, else New.
- Touch: swipe (scroll snap). Mouse: side buttons. Keyboard: the track takes focus; Left / Right move one slide.
- Sets: New = Recently added (Jellyfin latest, then arr arrivals); Continue = the viewer's up next; Not yet watched =
  films not played and not resumed, plus shows with every episode unplayed, newest added first. Up to 12, one per show.
- Shelves below: Continue watching, Recently added, Downloading, Not yet watched, Top rated on Joey.
  Removed from Home: Because you rated, Most played, New from people you follow, the Playing now hero.
- JY-278: Recently added (shelf and New pill) keeps one tile per show; a series, its season and an arr arrival
  ("Billions · 3 episodes") are one tile, the Jellyfin row (Joey poster) kept.

## Test changes (dated, 2026-11-03)

Route tests that asserted the removed hero or shelves on the household Home now assert option B instead; the
builders behind the removed shelves keep their coverage:

- `test_because_shelf.py`: the two household route tests check the shelf is gone from Home and run the
  `media_because.shelf` builder directly (cache only, sockets blocked; per-view ownership).
- `test_media_plays.py::test_home_shelf_present_when_data_and_omitted_when_empty`: Most played is absent on Home;
  the `build_shelves` call checks the shelf's rows, words and link.
- `test_media_follow.py::test_home_shelf_only_with_a_follow`: absent on Home; `/media/following` keeps the rows.
- `test_media_her.py` (two tests), `test_media_shelves.py` (three route tests), `test_tmdb_logos_jy267.py`
  (web Home logo): the Playing now / Up next hero is the carousel; the logo test checks the slide's logo.
- `test_shelf_season_state.py`: the section helper anchors on the shelf heading, not the first matching text
  (the pill has the same words).

New: `tests/hub/test_home_carousel_jy277.py`.

## Open (questions 2-8 in the options page)

Shelf set, Downloading for friends, Because you rated's new home, pill on load, "New episode" tag (not built),
TV layout (untouched), auto-advance (not built: moves only on swipe, click or key).
