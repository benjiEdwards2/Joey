# JY-195 Home shelves and TV empty states (U9)

Status: building
Size: M
Live risk: none
Area: `hub/media_guest_home.py` (the friends' Home data; the brief's `media_guest_overview.py`), `hub/templates/area_shelves.html`, a new `hub/templates/_empty_state.html` macro, the empty branches of `media_watchlist.html`, `media_to_rate.html`, `media_history.html` and `media_diary.html`, `hub/static/tv.css` (a commented "JY-195" block), tests in `tests/hub/`
Needs: JY-188 (density B) and JY-248 (no Overview pill; "Joey Media" goes Home), both merged
Options page: `JoeyTV\mockups\tv-v2\03-overview.html` (pick A) and `02-library.html` (empty states)

## Problem
TV UI evaluation 2026-10-23 (`JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md`):
- O1: a new friend's Home had three shelves with 2 + 1 + 0 items. About 70 % of the screen was black, and "Recently watched" was a grey one-liner.
- E1: an empty Watchlist or To rate tab was a 1 px grey box with one 16 px line, and the rest of the screen black.
- E2: the Watchlist meta line "0 on your watchlist · 0 not on the server" is private-Joey wording.
- Y4: To rate on the Diary was the "Rate TV by" chips plus two grey empty boxes: the whole screen was empty states.

The page was called Overview. JY-248 removed the Overview pill: B., 2026-10-25: "remove the overview section, use the Joey Media as a way of going back to the home". This spec calls the page **Home**.

## Options and the pick
B., Gate 1, 2026-10-25: **"4A"** (Overview = shelves). Option A of `03-overview.html`: five shelves, no hero; a brand-new friend gets a one-line welcome above them.

## Acceptance criteria
### Home (media front, every device)
1. Home shows these shelves, in this order. A shelf with nothing in it is left out (no heading, no grey box):
   1. **Continue watching**: the friend's own Jellyfin resume list (unchanged read: their token, cached 60 s, 3 s timeout).
   2. **Recently added**: the scrubbed snapshot's `latest` (unchanged).
   3. **New on Joey this month**: films and shows from the scrubbed library lists (`movies`, `shows`) added in the last 30 days, newest first. Caption "Added 20 Oct".
   4. **Top rated on Joey**: films and shows by community rating, highest first (rows without a rating left out). Caption "Film · 7.8" / "Show · 8.2".
   5. **Films under 100 minutes**: films with a runtime of 1 to 99 minutes, highest community rating first. Caption is the runtime ("1h 24m").
   6. **Recently watched**: the friend's own play history (unchanged read), kept after the five pick-A shelves when it has items.
   Each shelf holds at most `SHELF_MAX` (15) posters. A show with no episode yet (`empty_series`) is not a library title and never appears.
2. Shelves 3 to 5 read only the jellyfin snapshot already loaded for the page (`media_home.view_jelly`, the guest scrub). No Jellyfin, arr, Seerr or TMDB call is added on render (rule 7). The only live reads stay the two cached per-user shelf reads that were already there.
3. Privacy: shelves show the friend's own data (1, 6, their own scores) or library-wide data (2 to 5). Never household watch state: no `played`, `last_played_at`, `unplayed`, Up next, history or now-playing rows of B. or Georgina. The scrub (`hub.guest.ROW_DROP`) already removes the played fields from the library rows; a test pins that a household-played film still shows on the library shelves with no watched mark.
4. Welcome line for a new friend: when both of the friend's own reads succeeded and both are empty, Home starts with "Welcome, <name> — here's what's on Joey" (name = the signed-in Jellyfin user). Not shown once they have anything to continue or watched, and not shown when a read failed.
5. When every shelf is empty (an empty library), Home shows one words-first state instead of nothing (criterion 8 recipe): "Nothing on Joey yet" / "New films and shows show up here as they arrive", button "Discover".
6. Page name: the tab title is "Home · Joey Media"; the desktop / phone head reads "Home" (was "Overview"). TV keeps no head band.
7. Desktop, iPad and phone friends get the same shelves and welcome line: `area_shelves.html` is the one template for every device. The household (private) front's Media home is unchanged.

### TV empty states (TV mode only; desktop and phone keep their one-line `.empty`)
8. Recipe (`_empty_state.html` `bigempty(icon, heading, line, href, label)`): centred in the space under the bar; a 64 px line icon, a 30 px heading, one 21 px line saying what to do, and one 56 px "Browse films" button to `/media/movies`. No border and no grey box. The heading is not a `.seclabel`, so it never reads as a shelf.
9. Watchlist (E1/E2), empty: "Nothing on your watchlist yet" / "Press + Watchlist on any film to keep it here" (TV shows: "on any show"; button "Browse shows" to `/media/tv`). The "0 on your watchlist · 0 not on the server" line is not drawn.
10. To rate tab (E1), empty: "Nothing to rate right now" / "Films you finish show up here so you can give them a score" (TV shows: "Shows you finish ..."). A Skipped list, if any, still follows.
11. Diary > To rate (`/media/history`, Y4 and "Recent"): a section with nothing in it is left out on the TV (the "Rate TV by" chips go with the To rate section). When both To rate and Recently watched are empty, the page is one state: "Nothing watched yet" / "Finish a film or episode and it shows up here".
12. Diary (`/media/diary`), no months: "Your diary is empty" / "Films and episodes you finish are logged here".
13. First focus: JY-187 G3 is kept. On an empty Watchlist / To rate tab the first focus is the current sub-tab; Down reaches the button. No `data-first` on the button.

### CSS
14. All new TV rules sit in one commented `/* JY-195 ... */` block at the end of `tv.css` (U10 / JY-196 lands after). No token change. The 18 px text floor holds (`test_tv_css_text_floor_is_18px`).

## Data
Read only: the jellyfin snapshot's `movies` / `shows` rows (`added_at`, `community_rating`, `runtime_min`, `title`, `year`, `poster`, `jf_id`, `item_key`) after the guest scrub. The viewer's own ratings (one `get_ratings` query, as before). No new table, no migration, no new cache.

## Performance budget
Hub page render, warm, p95 <= 50 ms: shelves 3 to 5 are three sorts over the in-memory library lists (hundreds of rows); no new I/O. The scores query stays ONE query for all shelves.

## Device check (for the grouped TV session)
`device --only overview,movies_watchlist,movies_torate` on the TCL as a friend:
- overview: >= 4 shelves on Home; no grey empty box.
- movies_watchlist, movies_torate (new friend, nothing there): the words-first state; no grey box; no "0 on your watchlist" line.

## Out of scope
- Option B (resume hero), genre shelves, "Popular on Joey" (needs play counts across users: household data).
- The household Media home.
- Y1 / Y2 Diary month card and Log a watch (other U rows).
- Tonight's and Awards' empty lines.

## Test changes (dated)
- 2026-10-25: `tests/hub/test_guest_overview.py` `test_an_empty_resume_list_keeps_the_heading_with_quiet_words` becomes `test_an_empty_resume_list_hides_its_shelf_and_welcomes_a_new_friend`: an empty Continue watching is now left out (pick 4A: "Nothing to continue: Continue watching is hidden"). Reason: B.'s pick above.

## Accept checklist
- TV, new friend: Home opens on "Welcome, <you> — here's what's on Joey" and at least four shelves; nothing grey.
- TV, friend with something half-watched: Continue watching first, no welcome line.
- TV: Movies > Watchlist and Movies > To rate, empty: big words and a Browse films button, no grey box, no "0 on your watchlist".
- TV: Diary and Diary > To rate, empty: the same kind of state.
- Phone and desktop: Home shows the same shelves under a "Home" head.

## Questions for B.
None open.

## Shipped notes
