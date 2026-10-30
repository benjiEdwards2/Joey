# JY-270 TV feature parity: bring the web features (Awards, Discover search, ...) to the TV app

Status: spec (audit done 2026-10-29; B. decides the questions in section 5, then `ready`)
Size: L overall, in S/M phases (section 4)
Live risk: phases change what every friend's TV draws on the next hub deploy (hub templates, `tv.css`, `tv.js`; no TV release). They carry the `live-risk` label.
Area: `hub/templates/` (TV branches), `hub/static/tv.css`, `hub/static/tv.js`, `hub/media_discover.py`, `hub/media_awards_pages.py`, `hub/guest.py` (route tables, only where Q1 says so), `tests/hub/`. Never `tv/` (the Kotlin shell) unless a phase says so.
Needs: nothing open. JY-259 phases 1 to 4 are shipped.

B., 2026-10-29, after using the TV: "There are a lot of things that need to be fixed though. It seems a lot of Joeys features for awards, etc are not on the TV app? Are you able to review and understand what is missing? Discover does not have the search functions."

## 1. How the audit was done

Read: `CLAUDE.md`, `docs/PROCESS.md`, `HITLIST.md`, `docs/specs/JY-259-tv-revamp.md`, every route in `hub/media_*.py`, the route tables in `hub/guest.py`, and the templates behind them. TV mode is `tv_mode(request)` (`hub/media_front.py`): the media front plus the shell's `JoeyTV/` user agent, or the `tv=1` cookie.

Also rendered with the demo hub (`JOEY_FRONT=media`, `HUB_DEV=1`, `GUEST_DEV_OWNER`, TV user agent, headless Chrome 960x540 dpr 2): Movies, Awards and Discover. The demo data is empty (library "not available yet", Discover "Not connected"), so the renders only prove the structure: the tab fold, the Awards route and the search box exist. They do not prove content. D-pad reachability is read from `tv.js` (focus rules, the search stop, the field locked read-only until OK), not measured. Two things only B.'s TV can settle are in section 5.

## 2. The finding that frames everything

The TV is the media front. `hub/guest.py` serves the media front only the routes in `GUEST`. Features in `PRIVATE` (Following, Wrapped / year, play history, Remove, Quality switch, Search now / Upgrade, Everyone's watchlist, Approve / Decline, Requests, Downloads, Library, the Awards "on your watchlist" count) are not served to the TV at all, whoever is signed in. So the gaps fall into three kinds:

- **Hidden on the TV by CSS or a template branch** although the route is served (cheap to fix: Movies / TV filters, sort, library search; title-page scores, crew, providers, collection, awards; Awards year, categories, filters).
- **Served but only for the web layout** (the Awards ballot, the category cards).
- **Not served to the media front** (private features). Whether the TV should ever show them is Q1.

## 3. Audit table

Verdicts: present, partial, absent, out of scope (JY-259 spec or the media-front rule). "Web" = the private-front page B. uses on desktop / phone.

### 3.1 Home

| Web feature | TV today | Verdict |
|---|---|---|
| Hero (latest / resume) | Follow-focus hero over a backdrop (JY-259 p1-2) | present |
| Continue watching, Next episodes, Recently added | 16:9 and poster rows | present |
| Because you rated, New this month, Top rated, Films under 100 min, Recently watched | rows in `tv_home.ROW_ORDER` | present |
| Resume card actions (mark watched, reset, hide) | none on the tile (`resume.card` is the web branch only) | absent |
| Per-card score pill (`rate.pscore`) | not on kit tiles | absent (minor) |
| Shelf "All" link | `.sechead a` hidden on TV (`tv.css` 107): nothing past the first ~7 of a row | absent |
| Upcoming / calendar, Downloads, Requests status, Weather, Playing now | private areas | out of scope |
| Set up Jellyfin card | full-screen card | present |

### 3.2 Movies and TV shows

| Web feature | TV today | Verdict |
|---|---|---|
| Poster grid | 9 across | present |
| My films / Watchlist sub-tabs | present; Tonight, To rate, Awards folded under "More" | present |
| Library search box ("Search titles") | `form.toolbar` is `display: none` on TV (`tv.css` 149) | absent |
| Filter chips (the `filters` in `media_pages`) | hidden with the toolbar | absent |
| Sort | hidden | absent |
| Grid / List switch | hidden | out of scope (a grid is the TV form) |
| Suggestions chips (New, Continue, Not yet watched) | dropped on TV ("no carousel" in `_library_page.html`) | absent (Home rows cover most) |
| "Waiting for the first episode" list | drawn | present |
| Tonight (three picks, Deal again) | tuned for TV (JY-189) | present |
| To rate (inbox: rate, Skip, Skipped list) | present; picker folds under "OK to rate" | partial: Skip and the Skipped list not checked for D-pad reach |
| Watchlist | grid present; add / remove on the title page | partial: no remove from the grid |
| Everyone's watchlist, Request all | private only | out of scope |

### 3.3 Awards (Movies > More > Awards, TV shows > More > Awards)

| Web feature | TV today (`_award_tv.html`) | Verdict |
|---|---|---|
| Ceremony choice (Oscars, Globes, BAFTA, Critics' Choice, SAG, DGA, PGA, WGA, Cannes) | chip row, current one first focus | present |
| Year picker (decade strip, Latest, years with no data dimmed) | none: the TV shows the latest edition; nothing on screen changes the year | **absent** |
| "No <Ceremony> in <year>, showing <year>" note | not drawn | absent |
| Edition line | present | present |
| Films view filter chips (Unseen, etc.) and sorts | forced to `f=all, s=wins` in `_page`; no chips | **absent** |
| Progress head: ring, "Seen 12 of 40 nominated films", headline line, "N on your server and unseen" | none | **absent** |
| Category pills per film (Won: Best Picture, Nominated: ...) and the Details fold | one gold "N wins" chip only; a nominee-only film shows no category | **partial** |
| Seen tick on a film | not shown (only On Joey / Not on Joey) | partial |
| Categories view (card per category: winner, nominees, "+N more", More categories fold) | none: `v` is forced to `films` | **absent** (the biggest hole: "who won Best Actor" cannot be answered) |
| Winners-as-people strip (acting / directing winners, photos, opens the person page) | none (TV shelves are works) | **absent** |
| Shorts fold | not drawn | absent (minor) |
| Next up / Coming up dates | none | absent |
| Sync freshness line | present | present |
| Watchlist button on a ballot row | none on the tile; the film's title page has Watchlist | partial |
| Title page "Awards" section (the film's wins per ceremony) | `#awards` hidden by `tv.css` 235 | **absent** |
| Award badge on Discover and More-on-Joey posters | `_guest_discover_grid.html` and the TV tiles draw none | absent |
| Person page Awards | none on the TV person page | absent |
| "On your watchlist" count | PRIVATE route | out of scope |

### 3.4 Discover and search

| Web feature | TV today | Verdict |
|---|---|---|
| Search box | present: Discover's own field plus the bar's Search stop (JY-194, JY-259 p2); read-only until OK so the TV keyboard opens | present, but B. says it is not there: see Q2 |
| Results grid with state chips (On Joey, Requested, Request) | present | present |
| Search scope | films and shows only | partial: no People search (`/media/person/find` is GUEST-allowed), no Films / Shows chip |
| Search of my own library from Movies / TV shows | none (the Search stop searches TMDB through Discover) | **absent** |
| Search history, suggestions, voice | none | out of scope (JY-259: voice) |
| Shelves Trending, Popular films, Popular TV | one merged, de-duplicated grid of up to 36 (`GUEST_MAX`) | partial: no shelf labels |
| Shelves Upcoming films, Upcoming TV | `GUEST_SHELVES = SHELVES[:3]` drops them | **absent** |
| Browse by streaming service (13 AU services; per-service page with four shelves) | `/media/discover/service/{id}` is served; no tiles on the TV (`services_row` is the web branch) | **absent** |
| Watchlist "+" on a result | not in the grid; the request panel and title page have it | partial |
| Request flow (panel, seasons, confirm, "Requested, waiting for approval") | present | present |
| Following | PRIVATE | out of scope |

### 3.5 Title pages (film, show, season, episode, person)

| Web feature | TV today | Verdict |
|---|---|---|
| Hero: backdrop, title, facts, synopsis, status line | present | present |
| Play / Resume (the shell player) | present | present |
| Trailer button | in the hero row; opens the in-page YouTube dialog | present, needs a TV check (Q3) |
| Watchlist | present | present |
| Rate (1-10 strip), change / remove rating | Rate button opens the strip (JY-192) | present |
| Request (not on Joey) | request page, seasons, confirm | present |
| Mark watched / unwatched, Reset, Hide (More fold) | episode page: toggle present; film More fold hidden by `.filmbody > :not(...)` | partial |
| Scores strip (TMDB, IMDb, RT, Metacritic, your score) | `.stats.numbers` hidden | **absent** |
| Runtime, Rated | in the facts line | present |
| Cast | circle row | present |
| Crew, directors, writers | `_film_makers`, `_film_crew` hidden | absent |
| Awards section | hidden | absent (3.3) |
| Where to watch (providers) | `_film_providers` hidden | absent |
| Collection ("Part of" series and parts) | `.partof-sec` and `_film_collection` hidden; JY-259 §2.3 listed "Part of (collection)" for films | **absent** |
| More like this / Recommended | one "More on Joey" shelf, on-server only (JY-193 pick 2A) | present, by choice |
| File info (quality, size, audio, subtitles) | hidden | absent (low value on a TV) |
| Dates: release, added, watched N times, requested | hidden | partial |
| Season and episode ratings: strip, season average, "where this sits", per-episode score pills | `#rating-strip`, `#season-place`, pills hidden | **absent** |
| Episodes shelf: season chips, stills, word chips, progress | present | present |
| Episode page: guests, crew, previous / next | prev / next via Back; guests and crew hidden | partial |
| Follow show; Quality switch, Search now, Upgrade, Remove, Open in Seerr | PRIVATE | out of scope |
| Person page: bio, On server shelf | compact | present |
| Person page: Films / TV "everything else" grids, Follow | on-server only (JY-193 2A) | out of scope by choice |

### 3.6 Diary, history, Wrapped

| Web feature | TV today | Verdict |
|---|---|---|
| Diary month card, rows, All / Films / TV chips | slim Diary (JY-196 5A) | present |
| Show: Everyone, year view, Wrapped | PRIVATE | out of scope |
| To rate | "OK to rate" | present |
| Server play log | PRIVATE | out of scope |
| Rate-by (Stars / Tens) setting | chips hidden on TV | absent (minor) |
| Log a watch (search a title, pick, save) | `/media/search` and `POST /media/log` are served; no TV entry point | absent |

### 3.7 Shell

Top bar sections, user chip, Sign out, the Search stop, Back memory, focus restore: all present (JY-187, JY-259).

## 4. Prioritised gaps and phases

Priority is how often a friend would hit the gap, then cost. Each phase is one area and one builder (at most 150 turns). Sizes follow `CLAUDE.md`.

Top gaps, in plain words:

1. Discover search: nothing narrows it (films / shows / people), and shelves are missing (Upcoming, services). Plus Q2.
2. Awards: no way to pick a year.
3. Awards: no categories view, so "who won Best Actor" is unanswerable.
4. Awards: no filters (unseen, on Joey), no progress, no category names on a film.
5. Movies / TV shows: no search, filter or sort of your own library. Later gap: genre / decade / rating filters (the web toolbar lacks them too).
6. Title page: no scores, no crew, no where-to-watch, no collection.
7. Shows: no season and episode rating strip.
8. Discover: no Upcoming shelves and no streaming-service browse.

| Phase | Area | Size | Scope | Verify |
|---|---|---|---|---|
| P1 | Discover search and shelves | M | `media_discover_guest.html`, `_guest_discover_grid.html`, `media_discover.py` (`_guest_grid`). Search type chips (All, Films, Shows, People); a People result opens `/media/person/{id}` (already allowed); the Search stop dialog follows; named shelves (Trending, Popular films, Popular TV, Upcoming films, Upcoming TV) instead of one merged grid; the field's "press OK to type" shown in words | Test per chip and shelf; shots at 960x540 and 1920x1080; D-pad probe: Up from the grid reaches the field, OK types, Down lands on the first result, Back clears |
| P2 | Awards: year and categories | M | `_award_tv.html`, `media_awards_pages.py` (stop forcing `v`). Year chip row (latest 6 years, then "Earlier"), the "No X in year" note, a Films / Categories chip pair, the categories view as one shelf per category (winner first, gold word "Won", then nominees) | Year chip changes the edition; Categories lists the winner first; shots of both; Back returns to the ceremony chip |
| P3 | Awards: ballot depth | S | Filter chips (All, Unseen, On Joey), progress line, the first two category names under a poster ("+N"), winners-as-people shelf, Next up line | Test per chip; the 18 px audit holds |
| P4 | Movies / TV shows: find in my library | M | The existing `filters` / `sorts` as chips (no `<select>`), a "Find" chip opening the JY-194 field scoped to the library (`?q=`), Suggestions as a chip | Chips keep search / sort; D-pad reaches every chip; shots |
| P5 | Title page: facts a friend asks for | M | Scores strip (words with numbers), crew, where to watch, the film collection as a "Part of" shelf, the film's Awards as a shelf of ceremony chips | Per-section tests; JY-259 title page shots; no text under 36 device px |
| P6 | Shows: episode ratings and extras | M | Season average chip and per-episode score on the tiles, a one-line "where this sits", episode guests and crew | Tests; the 16:9 tile keeps its word chip; shots of a show and an episode |
| P7 | Discover: streaming services | S | A service chip row (13 AU services); a service page = four shelves | Tests; D-pad probe |
| P8 | Small things | S | Resume tile actions, watchlist remove from the grid, Rate-by, Log a watch entry, award badge on Discover and More tiles, person Awards | Test per item |

Ordering constraints: P3 starts after P2 merges (both touch `_award_tv.html`); P6 starts after P5 merges (both touch `media_film.html`). Everything else can run in parallel.

### Recommended order

P1 (Discover search) and P2 (Awards year and categories) first, in parallel: different files, and they are the two things B. named. Then P3, P4, P5. Then P6, P7, P8. Nothing blocks. Q1 affects only P8 and later work; Q2 might add a bug fix to P1.

## 5. Open questions

1. **Should B.'s own TV session see the private features (Following, Wrapped, Remove, Quality, history)?** Today the TV is the media front, so none are served, whoever is signed in. Recommend: no. Keep the TV friend-safe under one rule (media front); B. uses the web for owner tools. Revisit only if B. asks for one by name.
2. **What exactly did B. see on Discover?** The search field and the bar's Search stop exist in code (JY-194, JY-259 p2), but the field is read-only until OK, and a live TV keyboard cannot be shown headless. Recommend: treat "no search functions" as the missing narrowing and shelves (P1), and ask B. for one photo of Discover on the TCL so the builder can check whether the field also fails to open. If it does, that bug fix comes first inside P1.
3. **Does the Trailer button play on the TCL?** It opens the in-page YouTube dialog; not verifiable headless. Recommend: B. presses it once during the P5 review; if it fails, hide it on TV.
4. **Awards on the TV: how deep?** Recommend: ceremony chips plus a Films / Categories pair (P2), the web's own structure.
5. **Library filters: chips only, or is typing with the remote acceptable?** Recommend: chips first (P4); the Find chip reuses the JY-194 field, which already works with the TV keyboard.
6. **Title page: show crew, skip file info (size, audio tracks)?** Recommend: yes. File info is an owner's concern.
7. **Confirm out of scope: voice search, Grid / List switch, Everyone's watchlist, Approve / Decline.** Recommend: yes, all four.

## Out of scope

The Kotlin shell (`tv/`), private features (Q1), the friends' player, casting, voice search, a TV settings screen, poster and backdrop changes (JY-260, JY-262), anything on the web or phone layouts.

## Test changes (CLAUDE.md rule 4)

None in this item: it is the audit only. Each phase lists its own tests and may not weaken the JY-259 / JY-194 / JY-196 tests it touches without a dated line.

## Follow-up: major ceremonies and year navigation (2026-10-30)

B., 2026-10-30: "With awards. Can we please only use the major awards ceremonies. We need to allow people to go left or right on awards to years or click a drop down view to select years."

**Ceremony set (config, not code).** `config/awards.yaml` lists the ceremony ids the Awards page offers (picker, TV chips, Next up); anything not listed is hidden there but still synced and still counted on title / person pages. Missing file or empty list = every ceremony.

| | Ceremonies |
|---|---|
| Kept (majors) | Oscars, Golden Globes, BAFTA, Critics' Choice, SAG (Actor Awards), Cannes (Palme d'Or etc.), Emmys |
| Hidden | DGA, PGA, WGA |
| Full set the data holds (to widen later) | oscars, globes, bafta, critics, sag, dga, pga, wga, cannes, emmys (`hub/media_awards_seed.py` BODIES) |

**TV year navigation.** P2's fixed six-chip year row is replaced by one year stepper under the ceremony chips (`‹ 2023 ›`, the year as a word). Focused: Left = previous (older) year, Right = next, wrapping only at the data's ends (the oldest year's Left is the newest, and back). OK opens the year list (one year per line, "Latest" on top when not on the latest year, the shown year focused); Up / Down move, OK picks, Back closes. After a step or pick the new page focuses the stepper again. 18 px floor, `--tv-r` radii, the list padded so every focus ring is whole.

Note: the stepper is its own control rather than the ceremony chip itself, because Left / Right on a ceremony chip already move between ceremonies.

**Web / phone.** A native year `<select>` beside the ceremony button (joey.js follows the pick); the picker sheet's year chips stay.

Shots: `JoeyTV\review\JY-270\5-awards-years-*`, `6-awards-dropdown-*`, `7-awards-web-1440.png` (`JoeyTV\scripts\jy270_years_shots.py`).
