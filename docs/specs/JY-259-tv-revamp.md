# JY-259 Joey TV: full revamp of the TV experience and the tile strategy

Status: ready (B. picked 2026-10-28); phase 1 building on `feat/JY-259-tv-revamp-p1`
Size: L overall (phased; each phase is its own PR). Phase 1: M
Live risk: phases 1 to 3 change what every friend's TV draws on the next hub deploy (hub templates, `tv.css`, `tv.js`; no TV release), so the phase PRs carry the `live-risk` label. Phase 4 touches `tv/` (a release).
Area: `hub/tv_home.py` (new, phase 1), `hub/templates/` (TV branches of `area_shelves.html`, `media_film.html`, `_poster.html`, `_shelf.html`, `_library_page.html`, `media_discover_guest.html`, new `_tv_tile.html`), `hub/static/tv.css`, `hub/static/tv.js`, `hub/media_guest_home.py` (row order, landscape data), `tests/hub/test_tv_mode.py`; phase 4 only: `tv/` (player overlay restyle after JY-057).
Needs: JY-057 ships first for phase 4 (the player overlay). Phases 1 to 3 need nothing open. Two items never share an area: this item stays out of `tv/` until JY-057 has merged.
Options page: `C:\Users\b.edwards\Desktop\Claude\JoeyTV\review\JY-259\JY-259-options.html` (three directions mocked at 1920 x 1080: Home, title page, player overlay; the questions with the reply line).

B., 2026-10-27: "After, can you continue or run the full tv remake and restrategise for the tiles. The TV version of Joey was poor so need a full revamp please."

## B.'s pick (2026-10-28)

B., 2026-10-28: "JY-259: A · 1A · 2A · 3A · 4A · 5A · 6A · 7A · 8A"

Direction A, and the recommendation on every question in §4: the hero follows focus, the top row fades, 16:9
in-progress tiles, rows 7 / grids 8 (changed by point 3 below), foot bands on Discover, a Search stop, `<main>`-only
swaps, the sub-tab fold. B. added, 2026-10-28:

1. "It scales to every TV needed once they load things up." The layout holds on 720p, 1080p and 4K panels, at any
   WebView devicePixelRatio: sizes come from the viewport (rem tied to vw / vh), never fixed device px. Proof: captures
   at 1280x720, 1920x1080 and 3840x2160, plus the TCL's 960x540 CSS px at dpr 2.
2. "The main screen and episode or movie shots should have a background shot or image that allows for people to
   distinguish the images." Home and the title / episode pages get a backdrop (Jellyfin backdrop, else the TMDB
   backdrop from the cache, else a blurred, dimmed poster) under a gradient scrim. No live call on render: cached image
   refs through the existing `/img` proxy.
3. "I would like it slightly scaled out more where things are a little smaller on the TV and allow a little more spacing
   around a few things. There are a few different areas where it is too condensed." Tiles slightly smaller than the
   mock (rows about 8 across, not 7; grids about 9), more gaps and row spacing, more room around headings and buttons.
   The 18 px text minimum and the readable focus ring stay.
4. "I have a lot of changes that will need to be better looking on the eyes. This will then provide a nicer option to go
   into things like awards, etc." Calmer contrast, fewer borders, less uppercase; the tile kit is built so later pages
   (Awards, collections) reuse it.
5. B. will swap in better TMDB posters later: that is JY-260, not this item. The poster source stays in one place.

Sources read: `JoeyTV\TV_UI_PLAN.md`, `review\TV_UI_EVALUATION_2026-10-23.md`, specs JY-186 to JY-197, JY-248, JY-250, JY-255, JY-057, JY-105, JY-052 options page, `hub/static/tv.css` (405 lines), `hub/static/tv.js` (499 lines), the TV templates, `tv/` (BackPolicy, MainActivity, the JY-057 branch: PlayerActivity, PlayerBar, PlayerUi), screenshots in `review\tv-ui-2026-10-25\recheck\shots\device\` and `review\jy057-tv-session\shots\`.

Units: the TCL renders the WebView at 960 x 540 CSS px, dpr 2. Sizes below are **device px (CSS px in brackets)** so they read the same whether a phase is built in `tv.css` or in Kotlin.

## 1. Diagnosis: why the TV version feels poor

The JY-042 round (JY-187 to JY-197, JY-248, JY-250) fixed what was broken: Back memory, search, episodes with art, the scrim, the type floor, the empty states. What is left is not bugs. It is that the TV mode is still the website's components scaled x1.5 and laid out for a laptop, where every TV app a friend already uses is built from a different kit: a hero, landscape tiles for things in progress, a chrome that gets out of the way, and a focus that moves the whole screen.

Frank list, by screen:

### 1.1 Home (`dev_overview_0first.png`, 2026-10-25)
1. **The screen is mostly black.** Two rows of two posters sit in the left 540 px of a 1920 px screen; the right 70 % of the screen and the whole top half above the fold carry nothing but the bar. A friend's Home with 2 + 2 items is the common case (`library_shelves` adds rows only when the library has data in the last 30 days). Plex, Jellyfin, Google TV and Apple TV all fill the first screen even with a small library: hero first, rows under it.
2. **No hero, no backdrop, no motion.** Home opens on a 208 x 312 px poster with a white ring. Nothing on the screen says "this is what you were watching" except a 5 px bar at the foot of the poster and "S1 E1 · 49m left" under it. The 03-overview Option B hero (`mockups\tv-v2\03-overview-B.png`) was offered on 2026-10-25 and B. picked A (shelves). With the rows this small, A reads as a list, not a lounge.
3. **Tiles are grid tiles, not row tiles.** "Continue watching" uses the same 2:3 poster as the library grid. Every reference app uses a 16:9 still with the progress bar inside the tile for anything in progress (Google TV, Apple TV Up Next, Plex, Netflix), because the poster says *what*, the still says *where you are*.
4. **Captions ellipsise at 208 px**: "One Battle ..." on Home; "Citizen Vi...", "Greenland...", "Project Ha...", "The Mand...", "The Punis..." on the grid. The title is the one thing a tile must say. At 8 across the caption is 104 CSS px wide at 18 px type: about 11 characters.
5. **Row labels are dashboard labels**: "CONTINUE WATCHING · 2", "RECENTLY ADDED · 2". Uppercase tracked grey with a count is the hub's web pattern (Server page, Library health). TV apps use sentence-case 28 to 32 px labels with no count.
6. **Focus is a ring, not a lift.** 4 px white outline + 1.06 scale + 120 ms. No shadow, no glow, no change elsewhere on the screen (the backdrop, the title block). It is the web's focus-visible made thicker. Plex and Google TV scale 1.1 with a soft shadow; Jellyfin uses a bright border and lifts the card; Apple TV parallax-tilts. The ring is readable, which was the WP-M bar; it is also the single most "web page" thing on the screen.
7. **The top bar is a website header.** Brand pill + four text pills + a user chip, sticky, 128 px (64 CSS) of the 1080. It never fades while you browse. Plex and Google TV fade the top row once focus is in the rows; Jellyfin keeps a slim one; Apple TV keeps tabs but no brand or user. The chip "joeytest [->]" with a sign-out icon is a desktop pattern; on a TV the user lives in a settings corner.

### 1.2 Title page, film (`dev_title_movie_0first.png`)
8. **A card on a dark page, not a hero.** 340 px poster, 88 px title, three lines of synopsis, four 112 px buttons; then **the bottom 45 % of the screen is empty**. The backdrop is under a scrim so heavy (`.94` to `.55` left to right) it reads as black. Jellyfin's detail page fills the top 60 % with the backdrop and puts the first shelf (cast, similar) on the first screen; Plex's hero is the backdrop with the poster floated; Apple TV is backdrop-only, no poster.
9. **Buttons wrap.** On a show the row is Next to watch / Trailer / Watchlist and **Rate wraps to a second row** (`dev_title_series_0first.png`); on an episode Play / Season then Rate on its own row. A wrapped button row is a 2-row D-pad walk where every other app has one row.
10. **The first shelf sits below the fold.** On a show the "SEASONS" label is at y = 858 and its one 208 px season card is cut off at the screen edge; the Episodes shelf, the thing a show page is for, needs a scroll (`dev_title_series_1down2.png`). On an episode page the same Seasons shelf is cut at the bottom again. The order should be Episodes first (the current season), Seasons as a chip row, not a poster shelf.
11. **No cast, no "more like this" with art on the first screen**, no logo art, no "On Joey since" line. The web page carries these; TV mode hides `.filmbody` wholesale (`tv.css` line 225) and the one "More on Joey" shelf shows only when the library has a match.

### 1.3 Library grid (`dev_movies_0first.png`)
12. The grid itself is the one screen that reads as a TV app (the evaluation's A-). Two things still fight it: the **gold score glow** (`rate.glow`) on Motor City and the third row looks like a second focus ring (a yellow border next to a white one), and the **sub-tab row (My films · Watchlist · Tonight · To rate · Awards) is a second header** under the first: 2 rows of chrome = 230 px before the first poster.

### 1.4 Discover (`dev_discover_0first.png`)
13. **State chips cover the art.** "Request" in indigo on every poster; "In library" wraps to two lines and hides 40 % of the poster. The state belongs at the foot of the tile (a band or a word under the title), with the art clear. 36 titles, 32 of them "Request": the chip is saying nothing most of the time.

### 1.5 Navigation depth and D-pad cost
14. Home to a specific episode: Home → show poster (OK) → Down (Rate row) → Down (Seasons) → Down (Episodes) → Right x n → OK = 5 + n presses with two page scrolls. Jellyfin: poster → OK → Down → Right x n → OK (the episode row is on the first screen). Sign-out is 6 presses (JY-248 J8, accepted). Up from any row lands on the section pill: fine. Awards, Diary, To rate, Tonight are five sub-tabs a friend walks past on every Movies visit.
15. **Every navigation is a full page.** `base.html` sets `historyCacheSize: 0` and `refreshOnHistoryMiss`, so each OK and each Back refetches and repaints the whole page: a 0.8 to 1.3 s flash of black with the bar re-drawn (evaluation §0.4). No crossfade, no persistent bar, no skeleton. This is the single largest "web page in a WebView" tell, more than any tile.

### 1.6 Loading and empty states
16. Images arrive lazily per tile with no placeholder shape; a row paints its labels first, then posters pop in one by one over 1 to 3 s on the LAN. Reference apps paint a grey tile shape of the final size, then fade the art in. The JY-195 empty states are good; the "empty-ish" Home (2 + 2 items) is the state that needs design, not the fully empty one.

### 1.7 Text size
17. The floor is 36 px (18 CSS) and holds everywhere since JY-188. That is fine for captions. What is missing is the top of the scale: the biggest text on Home is the 44 px (22 CSS) brand; a TV Home needs one 64 to 72 px title (the hero) so the eye has somewhere to land from the couch.

### 1.8 Against the reference home screens

| | Joey TV today | Jellyfin (Android TV) | Plex | Apple TV | Google TV |
|---|---|---|---|---|---|
| First screen | bar + 2 small rows, left third | slim bar + 3 rows (10+ across), backdrop of focused item | hero (backdrop follows focus) + 2.5 rows | top shelf hero (full width) + tabs | hero carousel + landscape rows |
| In-progress tile | 2:3 poster, bar at foot | 16:9 still with progress | 16:9 or poster, progress band | 16:9 "Up Next" | 16:9 with title + progress |
| Chrome while browsing | sticky 128 px bar, always | slim, scrolls away | fades after focus leaves | tabs stay, no brand | fades |
| Focus | ring + 1.06 | bright border + lift | 1.1 + shadow, hero updates | parallax tilt | 1.1 + border |
| Page change | full reload, black flash | in-app, instant rows | crossfade | crossfade | crossfade |
| Title page | card, 45 % empty below | backdrop 60 %, cast + similar on first screen | backdrop + floated poster | backdrop only | backdrop + landscape rows |

Headline: **tile size is not the main fault** (B. already moved from 6 to 8 across on 2026-10-25 and the grid is the best screen). The faults are the missing hero, the wrong tile shape for in-progress items, the always-on web chrome, the flat focus, the full-page flash on every move, and a title page that leaves half the screen empty.

## 2. Tile strategy

### 2.1 One tile per content type

| Content | Shape | Size, device px (CSS) | Always shown | On focus adds | State on the tile |
|---|---|---|---|---|---|
| Film (library, rows, grids) | 2:3 poster | 232 x 348 (116 x 174) in rows; 208 x 312 (104 x 156) in grids | title (one line, 36 px, 2 lines in rows) | year · runtime (36 px) | progress band at the foot when started; "New" dot, 10 days |
| Show (library) | 2:3 poster | as film | title | "3 seasons · 2 of 24 watched" | "New episode" chip (teal, foot band) when an aired episode is unwatched; progress band for the current season |
| In progress (film or episode) | **16:9 still** | 400 x 225 (200 x 112) | title + "S1 E1 · 49 min left" under the still; progress bar inside the still's foot | episode name | the bar is the state |
| Episode (on a show page) | 16:9 still | 400 x 225 | "E1 · My Town Indy" + runtime | air date | chip: Next / Watched / 23m left / Not aired (as JY-192) |
| Person (cast row) | circle | 160 (80) headshot, 232 wide cell | name | role | none |
| Request (Discover, title shelves) | 2:3 poster | 232 x 348 | title | year · Film / TV | **foot band**, not a chip: "On Joey" (green), "Requested" (amber), "Request" (indigo); the art stays clear |
| Collection / franchise | 2:3 poster of the first title with a 3-deep stack edge | 232 x 348 | "Mission: Impossible · 8 films" | watched count | none |
| Hero (one per Home, one per title page) | backdrop, full width | 1920 x 620 top band under a gradient | title 64 px (or logo art), facts 28 px, 2-line synopsis 28 px, the one button | the backdrop crossfades to the focused tile's backdrop after a 350 ms dwell (Q1) | Resume / Play / Request |

Rules: one size per shape (no .sm / .big variants), the title is never ellipsised to fewer than 2 lines in rows, nothing under 36 px, state is a word on a band, never a chip over the art (except the episode chips, which sit on a 400 px still and already read well).

### 2.2 Focus behaviour
- Scale 1.08 (posters) / 1.05 (16:9 and hero buttons), 160 ms ease-out, a 0 24 48 px shadow under the tile, and the 4 px white ring kept (it is the accessibility floor; the lift is what makes it feel native).
- Info reveal: the meta line under the tile (already built in JY-188) stays; on the Home the **hero follows focus**: the backdrop and title block change to the focused tile's (dwell 350 ms, 250 ms crossfade). This is Plex's and Google TV's pattern and it is what makes a black screen feel full with two rows.
- The top row fades to 40 % when focus is below the first row and comes back on Up (Q2).
- The row label of the focused row goes to `--tv-t1`; the others stay `--tv-t4`.

### 2.3 Rows vs grids, row order, tile counts on 1920
Home = hero + rows. Movies / TV shows = grid (8 across stays, JY-186 scale B). Discover = search stop + grid. Title page = hero + rows.

Home row order (each left out when empty; the first row with items is the hero's source):

| # | Row | Tile | Across (1824 px safe width) |
|---|---|---|---|
| 1 | Hero: the first Continue watching item, else the newest addition | hero | 1 |
| 2 | Continue watching | 16:9 400 px | 4 + a peek (4 x 400 + 3 x 32 = 1696) |
| 3 | Next episodes (shows with a new aired episode; from the snapshot's next-up) | 16:9 400 px | 4 + peek |
| 4 | Recently added | poster 232 | 7 + peek (7 x 232 + 6 x 32 = 1816) |
| 5 | Because you rated these 9 or 10 (JY-105; never first focus) | poster 232 | 7 |
| 6 | New on Joey this month | poster 232 | 7 |
| 7 | Top rated on Joey | poster 232 | 7 |
| 8 | Films under 100 minutes | poster 232 | 7 |
| 9 | Recently watched | poster 232 | 7 |

Rows 2 and 3 are new data shapes (`still` = the episode's Primary image, or the film's backdrop at 16:9). Row 3 needs `next_up` per show from the Jellyfin snapshot (JY-057 already computes `up_next` for an item from the cache; the row is the same lookup across the viewer's shows).

Title page rows: show = Episodes (current season, 16:9) → Seasons as a chip row (not posters) → Cast (circles) → More on Joey. Film = Cast → More on Joey → Part of (collection). Hero buttons on one row always: Play / Resume · Trailer · Watchlist · Rate (Rate opens the JY-192 strip in place).

## 3. Options: three directions

### A. Evolve the WebView TV mode (big tiles, hero-led, in `tv.css` + templates + `tv.js`)
- **Scope:** the tile kit of §2 as Jinja macros (`_tv_tile.html`), the Home hero with follow-focus backdrop, landscape rows, the fading top row, a Search stop, foot bands on Discover, the title page as a hero with rows on the first screen, image placeholders and preloading of the first two rows, and a persistent bar: TV mode swaps `<main>` only (hx-boost target + `historyCacheSize` raised in TV mode) with a 200 ms crossfade (the View Transitions API is in WebView 155).
- **WebView vs shell:** everything in the hub. The Kotlin shell is untouched in phases 1 to 3; phase 4 restyles the JY-057 player overlay to the same tokens (title block, bar, buttons).
- **Effort:** P1 tiles + rows M · P2 hero + chrome + transitions M · P3 grids, Discover, title page, loading L · P4 player overlay S.
- **Risk:** low to medium. The TCL's WebView must crossfade a 1920 px backdrop and scale tiles at 60 fps: a 20-minute spike on the device (phase 2 step 1) decides whether the hero crossfade is a transform/opacity fade (cheap) or a cut. Full-page flashes shrink but do not vanish for cross-section moves. Every fault so far reproduced in headless Chrome (evaluation §0.1), so this path is testable without the TV.
- **Shared with web and phone:** the data, the templates, the tokens, the tile macros (phone Home can take the same 16:9 continue row). Deploys like any hub change; friends' TVs need no app update.

### B. Native Compose-for-TV browse in the Kotlin shell, WebView for detail pages
- **Scope:** Home, Movies, TV shows, Discover and Search as Compose-for-TV screens (`androidx.tv:tv-material`, `ImmersiveList` hero, `TvLazyRow`s) over a new read-only JSON API (`/api/tv/home`, `/library`, `/discover`, `/search`, cookie-authenticated like the JY-057 player calls). Title, episode, person, Diary and the request panel stay WebView pages opened from the native rows; Back returns to the native screen.
- **WebView vs shell:** the hub gains the JSON API and keeps TV mode for the detail pages (which still need §2's title-page work). The shell gains a navigation layer, image loading (Coil), the focus engine, the hero, and every row.
- **Effort:** P1 JSON API + tests M · P2 Compose Home + rows L · P3 grids, Discover, search, keyboard L · P4 polish, transitions, the hand-off to WebView pages and back M. Plus a TV release per phase.
- **Risk:** high. Two UIs for one product (a Home row added on the web must be added in Kotlin); the shell builds only in GitHub Actions (`tv/README.md`), so every iteration is a CI build + a TV sitting; JY-057 is an L in `tv/` right now (two items never share an area), so B cannot start until it ships; a friend's TV (the Samsung Frame stick) updates only when it accepts the release; the pytest suite and `tv_ui_capture.py` cover none of it.
- **Shared with web and phone:** the data only. No template, CSS or focus code is shared.

### C. Hybrid: native Home only, WebView for everything else
- **Scope:** one Compose-for-TV screen (Home: hero + rows from one `/api/tv/home` answer); Movies, TV shows, Discover, Search, title pages and Diary stay WebView in the evolved TV mode (so A's phase 3 still runs for them). The section row lives in the native Home; the WebView pages keep their own bar.
- **WebView vs shell:** hub: one JSON endpoint + the A phases for the non-Home pages. Shell: Home screen, Coil, the hero, focus memory for one screen.
- **Effort:** P1 endpoint + native Home L · P2 A's title-page and tile work M · P3 grids and Discover M · P4 player S. Plus a TV release.
- **Risk:** medium-high. Two chromes (native Home bar, WebView bar on every other page) that must look the same; the seam shows on every OK and Back between Home and a title page; the same area clash with JY-057; the same CI-only build loop. Gains the native hero and focus on the one screen that matters most, at the cost of two codepaths for the rows.
- **Shared with web and phone:** data, and the WebView pages (title, grids) share templates as in A. Home does not.

### Recommendation: A
1. The evidence says the WebView is not the problem: the 2026-10-23 evaluation reproduced every visual fault pixel-for-pixel in headless Chrome. The faults are design (no hero, wrong tile shapes, always-on chrome, full-page swaps), and all of them are reachable in `tv.css`, the templates and `tv.js`.
2. A ships through the hub deploy with the pytest suite, the 18 px audit and `tv_ui_capture.py` already covering it; B and C need a CI build, a TV sitting and a release per iteration, and the TV is already booked for JY-057.
3. B. said "stop any tv development" on 2026-10-27 and then "go for tv change again": keep the TV release cadence to the one item that needs it (JY-057). A keeps `tv/` for the player and nothing else.
4. The one thing a WebView does worse than native, page transitions, is bounded: `<main>`-only swaps with a crossfade and image preloading take the black flash out of the common moves (row → title → Back); the device spike in phase 2 tells us early if the crossfade must be a cut.
5. If, after phase 2's TV checkpoint, the hero or the row scroll stutters on the TCL, C is the fallback and its Home-only scope is exactly what phase 1 to 2 have specified (tiles, row order, data shapes): nothing is wasted.

## 4. Questions for B.
1. **Home hero.** A) a hero that follows focus (backdrop + title block change to the focused tile, Plex / Google TV) · B) a fixed Resume hero (the 03-overview B mock) · C) no hero, taller rows. *Recommend A: it fills the screen with two rows and makes focus visible from the couch.*
2. **Top row.** A) keep the top row (Joey Media · Movies · TV shows · Discover · search · user) and fade it to 40 % while focus is in the rows · B) a left rail with icons (Jellyfin / Compose TV drawer) · C) unchanged. *Recommend A: JY-248's "Joey Media is Home" stays, nothing to relearn.*
3. **In-progress tiles.** A) 16:9 stills with the progress bar inside (Continue watching, Next episodes, episodes) · B) keep 2:3 posters with the foot bar. *Recommend A.*
4. **Poster size.** A) rows 7 across (232 px), grids 8 across (208 px, JY-186 B) · B) 8 across everywhere · C) 7 across everywhere. *Recommend A: rows carry 2-line titles under a hero; grids stay dense.*
5. **Request state on Discover.** A) a foot band on the tile ("Request" / "Requested" / "On Joey"), art clear · B) a corner dot with the word on focus only · C) keep the top chip. *Recommend A.*
6. **Search.** A) its own top-row stop (a magnifier) that opens the JY-194 field over the current page · B) stays inside Discover. *Recommend A: one press from anywhere.*
7. **Page moves.** A) TV mode swaps `<main>` only, keeps the bar, crossfades 200 ms, `historyCacheSize` 10 in TV mode (Back is instant, JY-187 memory kept) · B) full page as today. *Recommend A.*
8. **Sub-tabs on Movies / TV shows.** A) fold Tonight, To rate and Awards under one "More" chip at the end of the sub-tab row (Watchlist stays) · B) keep all five. *Recommend A: fewer stops past on every visit; JY-196's Awards view stays reachable.*

## 5. Phased plan (direction A)

Pass bar for every phase (on top of the hub budgets): 0 text nodes under 36 device px (18 CSS); `outsideSafe 0`, `offscreen []`; a visible ring on every stop; JY-187 memory holds (J3 / J4); p95 Home render <= 50 ms; the first two rows' images within 2 s on the LAN; nothing wider than the viewport (no body x-scroll); desktop, iPad and phone screens unchanged byte-for-byte where the spec says "TV only" (`tests/hub` snapshot asserts).

Builder and review per phase: L row (Opus builder, two Sonnet reviewers, Opus verifier). `tv.css` is one file: phases land in order, one worktree at a time.

**Phase 1: tile kit + Home rows** (hub only)
1. `_tv_tile.html` macros: poster (232 / 208), land (400 x 225), person, request band, collection stack; `tv.css` tile block replaces the JY-188 scale block → verify: `test_tv_mode.py` renders each macro, 18 px audit green, hover audit green.
2. Home rows reordered per §2.3; Continue watching and Next episodes become 16:9 rows (`media_guest_home.py` adds `still` + `next_up` rows from the cache only) → verify: unit tests on the row builder with a 2 + 2 library and a 40-title library; no Jellyfin call on render.
3. Focus lift (1.08 + shadow + ring), row-label highlight → verify: headless 960 x 540 shots match the options page mock within the tile grid (`tv_ui_capture.py local`).
4. **TV review checkpoint 1:** `tv_ui_capture.py device --only overview,title_movie,movies`; B. looks at Home on the TCL. Gate: "the Home fills the screen and the tiles read".

**Phase 2: hero + chrome + transitions** (hub only)
1. 20-minute device spike: a 1920 px backdrop crossfade (opacity on a second layer) and 8 tiles scaling, measured with `tv_ui_capture.py probe` frame timing → verify: >= 50 fps on the TCL, else the crossfade becomes a cut (record the number in the spec).
2. Home hero: first row's item, title 64 px, facts, 2-line synopsis, Resume / Play; follows focus with a 350 ms dwell (`tv.js`) → verify: journeys J2 (poster → title → Back) keep focus and the hero shows the focused tile after Back.
3. Top row fade (Q2), Search stop (Q6) → verify: Up from any row lands on the current pill at full opacity; OK on the magnifier focuses the JY-194 field; Back closes it.
4. `<main>`-only boosted swaps in TV mode, crossfade 200 ms, `historyCacheSize` 10 (TV mode only), image placeholder shapes, `<link rel=preload>` for the first two rows' images → verify: time from OK to the title page's first paint <= 400 ms on the LAN (was 0.8 to 1.3 s); desktop / phone keep `historyCacheSize: 0`.
5. **TV review checkpoint 2:** `tv_ui_capture.py all`; compare `capture.json` against 2026-10-25 (tiny / lowContrast / outsideSafe / offscreen must not rise). Gate: "moving around no longer flashes; the hero follows the remote".

**Phase 3: title page, grids, Discover, loading** (hub only)
1. Title page as a hero: full-width backdrop (gradient to `--bg` at 60 % height), poster optional (Q: kept at 232 px floated), one button row that never wraps, Episodes row (16:9) first on a show with Seasons as chips, Cast circles, More on Joey → verify: `device --only title_movie,title_series,title_episode`: the first row's tiles inside the first 1080 px, 0 wrapped buttons (a DOM assert), J6 OK on an episode plays it.
2. Grids: 8 across kept; score glow off in TV mode (ring is the only white/gold border); sub-tab fold per Q8 → verify: Movies grid shows 24 posters on the first screen, Down x 2 reaches row 3, the "More" chip opens Tonight / To rate / Awards.
3. Discover: foot bands, search results in the same grid → verify: `device --only discover`: 0 chips over art, bands read "On Joey / Requested / Request".
4. Loading: placeholder tile shapes, lazy rows below the fold, a 3-tile skeleton row for slow shelves → verify: `images_ms` for the first two rows < 2000 on the TCL.
5. **TV review checkpoint 3:** the 40-check list from `TV_UI_PLAN.md` re-run (it is the regression set), screenshots to `review\tv-ui-<date>\`. Gate: B.'s accept on the TCL for Home, a film, a show, Discover.

**Phase 4: the player overlay** (`tv/`, after JY-057 ships; a release)
1. Restyle the look-A overlay to the tile kit's tokens: 64 px title block, 28 px method line, the bar, 56 px buttons, the up-next card as a 400 px landscape tile → verify: `PlayerUi` tests unchanged; CI `tv` green.
2. "Back to Joey" lands on the title page with the hero showing the new progress → verify: JY-057 checklist row 5 re-run.
3. **TV review checkpoint 4:** the JY-057 device checklist rows 1 to 7 on the debug APK. Gate: B.'s accept, then the release.

## 6. Phase 1 build (2026-10-28): tile kit, Home rows, backdrop, scaling

Scope: the tile kit (`_tv_tile.html`), the 16:9 Continue watching and Next episodes rows (cache only), the focus lift,
the Home row order, the backdrop layer (Home only in this phase, with a static hero area), the scaling system (points 1
and 3). Left for phase 2: the hero following focus, the fading top row, `<main>`-only swaps. The web and phone pages do
not change; the friends' media front shows each friend their own data only.

Steps (step -> verify):
1. Scaling: `html.tv { font-size: max(16px, min(calc(100vw / 60), calc(100vh / 33.75))) }`; every length in `tv.css`
   becomes rem (1rem = 16 CSS px at 960x540, 21.3 at 1280x720, 32 at 1920x1080, 64 at 3840x2160). `tv.js` scales its
   overscan, padding and ring numbers by the same rem (`px()`). -> verify: `test_the_18px_floor_holds_at_every_panel`
   (four viewports), `test_no_fixed_px_length_is_left_in_the_sheet`; captures at the four sizes with a DOM audit of 0
   text under 18 CSS px.
2. Tile kit as Jinja macros: `poster`, `land` (16:9), `person`, `request` (foot band), `collection` (stack edge), `row`;
   `art()` is the one place a TV tile's image URL is made (point 5). -> verify:
   `test_every_tile_macro_renders_one_focusable_link_with_its_shape`, `test_the_poster_source_is_one_place`.
3. Home rows (`hub/tv_home.py`, TV mode only): Continue watching (16:9: an episode's own still, a film's backdrop),
   Next episodes (16:9: per show in the friend's Recently watched, the next aired unwatched episode from that friend's
   cached show read; a show already in Continue watching is left out), Recently added, Because you rated (never first
   focus), New on Joey this month, Top rated on Joey, Films under 100 minutes, Recently watched. -> verify: the row
   builder tests (a 2 + 2 library, a 40-title library, the Next episodes rules), `test_no_network_on_render`,
   `test_each_friend_sees_only_their_own_rows`, `test_the_web_and_phone_home_are_unchanged`.
4. Backdrop (point 2), Home only: a fixed layer behind the page; the chain is the Jellyfin backdrop (`jfb:` from the
   snapshot row), then the TMDB backdrop (`tmdb:` from the Jellyseerr title cache, `media_film._cpeek`), then the poster
   blurred and dimmed; a left-to-right and top-to-bottom scrim; the static hero says what it shows (eyebrow, title,
   facts). The hero item is the first Continue watching item, else the newest addition. -> verify:
   `test_backdrop_chain_jellyfin_then_tmdb_cache_then_blurred_poster`,
   `test_tv_home_draws_the_backdrop_hero_and_16x9_rows`; captures.
5. Focus lift: scale 1.08 (1.05 on a 16:9 tile), 160 ms ease-out, a soft shadow under the picture, the 4 px white ring
   kept; the focused row's label goes brightest. -> verify: `test_tile_sizes_spacing_and_the_focus_lift`,
   `test_focus_growth_and_ring_stay_inside_the_overscan_margin` (POSTER_GROW 0.04 = (1.08 - 1) / 2).
6. Captures of Home at 960x540 dpr 2, 1280x720, 1920x1080 and 3840x2160 into `JoeyTV\review\JY-259\p1-shots\`,
   with the DOM audit (text under 18 CSS px, text outside the 5 % safe area).
7. TV review checkpoint 1 (B., on the TCL): "the Home fills the screen and the tiles read". Not run by the builder.

Sizes (960x540 CSS px; x2 on the TCL and on a 1080p panel, x4 on a 4K panel at dpr 1, all from rem):

| Thing | Before | Phase 1 |
|---|---|---|
| Row poster | 104 x 156, 14 px gaps | 92 x 138, 18 px gaps (8 across + a peek: 8 x 92 + 7 x 18 = 862 of 864) |
| 16:9 tile | none (a 2:3 poster in Continue watching) | 158 x 89, 18 px gaps (5 across) |
| Library / Discover grid | 8 across, 8 / 14 px gaps | 9 across, 18 / 16 px gaps |
| Focus | 1.06, 120 ms, ring | 1.08 (1.05 on 16:9), 160 ms, ring + shadow |
| Row label | 18 px, uppercase grey, "· n" count | 20 px, sentence case, no count; the focused row's label brightest |

Areas loosened (point 3): the row tile gaps (14 -> 18 px); the space between Home rows (+22 px); the grid gaps (8 / 14 ->
18 / 16 px); the top bar's item gap (20 -> 24 px) and the section pills' gap (4 -> 6 px); the sub-tab gap (4 -> 8 px);
the title page's button row gap (14 -> 18 px) and its top margin (20 -> 24 px).
Calmer (point 4): row labels lose the uppercase, the tracking and the count; tile pictures carry no border; the hero
eyebrow is sentence case. The title page's eyebrows and rating label keep their uppercase until phase 3 rebuilds it.

Test changes (CLAUDE.md rule 4), 2026-10-28:
- `tests/hub/tv_css.py` (new): `design_px` reads `tv.css` back in 960x540 CSS px, so every older pin keeps its meaning
  after the rem conversion; each test that reads `tv.css` calls it. No assertion weakened.
- Pins changed because B. asked for the new values (point 3): the row card 104 -> 92 px and its gap 14 -> 18 px, the
  grids 8 -> 9 across with 18 / 16 px gaps (`test_jy188_density_b_with_compact_chrome`,
  `test_tv_discover_is_the_eight_column_grid_with_chips_and_the_panel`,
  `test_episode_cards_keep_236px_over_the_jy188_carousel_width`); `tv.js`'s margin lines now read `px(OVERSCAN_Y)`,
  `px(PAD)` and `px(OVERSCAN_X)` (`test_focus_growth_and_ring_stay_inside_the_overscan_margin`).

## Data
Phase 1 adds two row shapes to the guest Home builder (`still` for a 16:9 image ref, `next_up` per show) from the Jellyfin snapshot and the hub's item cache only. No `media.db` change, no new connector call. Images: the 16:9 still is `/img/<ref>?h=225` style (a new allowed height, warmed by `media_warmup` for the Continue watching and next-up items only).

## Performance budget
- Hub page render, warm, p95 <= 50 ms (Home) and <= 150 ms (title): the row builder is list work on memoised snapshot views (JY-195's `_lib_memo`); the hero adds one dict read.
- joey-hub memory <= 200 MiB: the 16:9 warm set is at most 30 images.
- TV: first paint <= 400 ms after OK on the LAN; first two rows' images <= 2 s; >= 50 fps on the hero crossfade and tile scale (the phase 2 spike).

## Out of scope
- The private front (B.'s own Home on the laptop) and the phone layout: untouched, except that the 16:9 continue row may be adopted there as a later S item.
- Friends' player (JY-058), casting, voice search, a TV-side settings screen.
- Directions B and C beyond the fallback note in §3.
- Awards, Diary and To rate TV views beyond the Q8 fold (JY-196 shipped them).

## Accept checklist (filled per phase at the checkpoint)
- [ ] Phase 1: Home on the TCL fills the screen; tile titles read; `device` audit 0 tiny / 0 outsideSafe.
- [ ] Phase 2: hero follows focus; no black flash on poster → title → Back; the top row fades and returns.
- [ ] Phase 3: a show page shows its episodes on the first screen; Discover bands; grid 24 up.
- [ ] Phase 4: the player overlay matches the kit; Back lands on the hero with progress.
- [ ] Desktop / iPad / phone: unchanged (screenshots attached to the accept message, as PROCESS step 9 asks).

## Shipped notes
Not yet.
