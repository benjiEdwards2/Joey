# JY-269 Web + phone title pages take the TV show/season layout

Status: spec
Size: M (three phases, S/M each)
Live risk: none
Area: `hub/templates/media_film.html`, `_film_*.html`, `_season_episodes.html`, `hub/static/control-surface.css` (new `.tl-*` block, not `tv.css`), `tests/hub/`
Needs: JY-259 phase 3 (merged; the TV layout is the source), JY-262 (backdrop 2)
Options page: https://claude.ai/artifact/D38p8cyWFbRZUWwH2hd6Mh (files: `JoeyTV\review\JY-269\`, built by `JoeyTV\scripts\jy269_shots.py`)

## Problem
B., 2026-10-29: "I like the seasons adn the shows. I would even be keen to take that approach to shows or seasons to the actual JOey App. Write it around."
And: "Happy for you to approve that once you show me an image of what you have done. No need for an artifact if its simple."

Goal: the web (desktop, iPad) and phone title pages (film, show, season, episode) get the layout B. likes on the TV, without the D-pad parts. "The actual Joey App" is read here as the web/phone pages at joeyhome.net (the phone installs it as a PWA), so this item changes those pages only; the TV and its tests stay as they are (question 4).

## What carries over from the TV layout (JY-259 §8)
1. Backdrop hero across the top, with a calm scrim (darker on the left for the words, fading to the page at the foot). Backdrop #2 first (JY-262), then the chain.
2. The poster beside the title, facts line, a short synopsis (2 lines, "more" expands) and ONE button row.
3. A show, season or episode page: the episodes are on the first screen, straight under the hero. The head line reads "Episodes", then the seasons as chips (the shown season lit), then "n of m watched".
4. Cast as circles, then "More on Joey" as posters, both from the page's existing deferred part. Skeleton rows while it loads.
5. The same state words ("Watched", "Next", "n left"), small-round corners, the existing colour tokens. No new colours.

## What must differ per device
| | Desktop 1440 | iPad 1024 | Phone 390 |
|---|---|---|---|
| Input | Mouse, keyboard. Hover states allowed (the TV has none). | Touch. 44 px targets, no hover reliance. | Touch, one hand. 44 px targets. |
| Hero | Backdrop 56 vh max, poster 140 px | Backdrop 48 vh, poster 120 px | Backdrop banner 220 px tall; poster 96 px overlaps its foot; title and facts under it |
| Text | 16 px body (the TV's 18 px floor does not apply) | same | same; synopsis 3 lines then "more" |
| Buttons | One row: Play / Next to watch / Resume, Trailer, Watchlist, Rate, then a "..." menu (Remove, Request, Follow). Never wraps. | same | Play full width on its own line; Trailer, Watchlist, Rate under it, one line; the rest in "..." |
| Episodes | Per the pick (below); chip row wraps | same | Chips are one horizontal scroll line (as the TV); list is one column |
| Cast / More | Circles 88 px / posters 120 px; row scrolls with arrow buttons and the wheel | swipe | swipe, 2.3 items visible so it reads as scrollable |
| Focus | Visible keyboard focus ring (existing token) | system default | system default |

The existing web actions all stay, with their current routes and tests: rate (the 1-10 picker moves into the Rate button's popover; the "Your rating" strip stays for a rated title), request (Request / Request seasons), remove (the existing confirm page), follow (Follow this show). Who sees what does not change: friends still see only their own data.

## Options (see the page)
Both start from the same hero, chips and cast/More shelves. They differ only in the episodes.
- **A. Faithful port.** Episodes as the TV's 16:9 tiles in a sideways row. One look on every device. Cost: a sideways row needs a swipe on a phone and is awkward with a mouse; synopsis and air date are not visible.
- **B. TV hero + the web episode list (recommended).** Episodes as the web's list, one row each (still, E-number and name, date, "n left" or progress, 2-line synopsis, rating). The list already works on every device and is where the synopsis lives.

Recommendation: B. The page's shots are mocks: the real TV page re-flowed with injected CSS, so web actions and the phone stack are not drawn yet.

## Phases (each its own PR, one builder, under ~150 turns)
1. **P1, S (Sonnet): the hero.** Shared hero block for film, show, season, episode: backdrop + scrim, poster, facts, synopsis, one button row with the "..." menu; phone stack. Web and phone only (behind `not tv_mode(request)`). Verify: tests 1-3; shots at 1440 / 1024 / 390.
2. **P2, M (Opus): episodes and seasons.** Show, season and episode pages: the "Episodes" head line with season chips and the watched count, the episode list per the pick on the first screen; the JY-114 season state rows are kept. Verify: tests 4-6; the first episode row starts inside the first screen at 390x844 and 1024x768.
3. **P3, S (Sonnet): cast and More on Joey.** Circles and poster shelves, skeletons, eager load of the first shelf. Verify: tests 7-8, image times.

Applying the hero to the library pages and Home is not in this item (question 3).

## Acceptance criteria
1. Film, show, season and episode pages draw the backdrop hero on desktop, iPad and phone; a title with no backdrop draws a poster-colour wash, not a gap.
2. The button row never wraps at 390, 1024 and 1440; every existing action is still reachable (rate, request, remove, follow) and each route is unchanged.
3. The TV pages draw the same bytes as before (`test_tv_*` untouched); web and phone differ only by this item.
4. A show's first screen at 390x844 shows hero, chip row and the first episode row. At 1440x900 and 1024x768 it shows at least three episode rows.
5. Season chips: the shown season lit, one tap changes season, the watched count is correct per viewer (friend isolation as JY-192).
6. Episode rows keep every state word and the JY-054 play hand-off.
7. Cast circles and More on Joey come from the existing deferred part; no new upstream read; page weight within the existing film-page budget.
8. No horizontal page scroll, no text under 14 px, tap targets 44 px on touch, at all three sizes.

## Tests (ship with the code, rule 4)
1. `test_web_title_page_is_a_backdrop_hero_per_kind` (film, show, season, episode).
2. `test_web_button_row_never_wraps_and_keeps_every_action` (rate, request, remove, follow present).
3. `test_tv_title_pages_are_unchanged_by_the_web_layout`.
4. `test_show_page_draws_episodes_then_season_chips`.
5. `test_each_friend_sees_only_their_own_episodes_and_chips_on_the_web`.
6. `test_episode_rows_keep_state_words_and_play_handoff`.
7. `test_cast_is_circles_and_more_on_joey_is_posters_on_the_web`.
8. `test_no_new_upstream_read_on_a_warm_title_page`.

Plus headless shots at 1440 / 1024 / 390 with a DOM audit (x-scroll, wrapped buttons, targets under 44 px, first episode row on the first screen), following `JoeyTV\scripts\jy269_shots.py`. Existing web tests that pin the old markup are re-pointed with a dated line here, never deleted.

## Performance budget
The film-page and item-page budget rows in `CLAUDE.md` apply. Measure with `scripts/bench_item_page.py`; the hero image is `fetchpriority=high`, cast and More images are lazy. Numbers go in each PR.

## Out of scope
The TV layout; the Kotlin shell; library grids and Home; JY-260 poster source; new colours; a native (non-web) Joey app.

## Accept checklist
- [ ] A show at 390: hero, one button row, chips, first episode on the first screen.
- [ ] A show at 1440 and 1024: hero, chips, three or more episodes.
- [ ] A film at all three sizes: hero, Cast circles, More on Joey.
- [ ] Rate, Request, Remove, Follow each still work from the new row.
- [ ] A friend sees only their own watched marks.
- [ ] The TV looks exactly as before.

## Questions for B.
1. Episodes: A (tiles) or B (list)? Recommended: **B**.
2. Request, Remove and Follow in a "..." menu, with Play, Trailer, Watchlist and Rate shown? Recommended: **yes** (keeps one row on a phone). Alternative: all actions shown, wrapping to a second row on phone.
3. Apply the same hero to the library pages and Home later? Recommended: **no, a separate item after you have seen this one**.
4. Does "the actual Joey App" mean only the web/phone pages (what this spec does), or also a native app? Recommended: **web/phone pages only**.
5. Approval: you said you would approve once you see an image. The options page is that image; say "B, all recommended" to mark it ready.

## Shipped notes
