# hub

FastAPI + Jinja/HTMX dashboard shell. Areas are config, not code — see `config/areas.yaml` (WP16).

**Apex shell (2026-10-06).** `templates/base.html` is the one frame: 260 px labelled rail (brand = kangaroo photo
`static/brand-joey.jpg`, the whole block links to `/`; Home group = Hub, any area with `rail_section: home`, Weather;
Areas group = the rest, in `areas.yaml` order), sticky top bar (theme toggle → `data-theme` on `<html>`, saved in
localStorage `joey-theme`, applied by a pre-paint script; user chip from `identity.py` — the Access header decides the owner view, `?owner_view=` only works locally), page heading block, phone bottom bar. Areas with `hidden: true` are parked: no rail entry, phone tab or hub card, page still serves.
`static/control-surface.css` keeps its filename but is the Apex port: light values on `:root`, the two dark blocks
redefine tokens only, no literal colour outside the token blocks (a test enforces it); `--brand` is the red, per-area
`--accent` is injected by templates. Hub page (`hub.html`, `_kpi.html`, `_upcoming_table.html`, `_shelf.html`): KPI
row per area in `hub_rank` order + Weather, sparks only from real data, Next 7 days table (`build_upcoming`), Weather
card, Continue watching / Recently watched shelves. Area pages (`area.html`): KPI row per tile; Calendar adds the
table + Weather band; `/weather` = Today hero + Next 24 hours (inline-SVG chart + hour list,
`weather_forecast()`) + Next 7 days strip, the last two absent for a pre-2026-10-06 snapshot. Rain radar panel
(2026-10-06, `weather_radar()`): stored BOM PNGs stacked as `<img>` layers, 6 frame slots cycled by CSS keyframes
(no JS; reduced motion = latest frame), time-range text + worded intensity legend; its own column beside the rest
at ≥ 1440 px, a full row below that; "Radar unavailable" note when the snapshot has no `radar`. Files served by
`GET /weather/radar/{name}` (allowlisted names from `SNAPSHOT_DIR/radar/`, else 404). Greeting clock: `_now_home()` (Australia/Melbourne).

**Media section nav (2026-10-06).** Every `/media/*` page and the Media shelves page render in
`templates/media_base.html`, which extends the Apex shell (rail + top bar; the earlier "Return to Joey" no-rail frame
was retired the same day) and adds an in-content sections nav
**Home · Movies · TV Shows · Diary · Server · Discover** with sub-tabs, a phone bottom bar and amber waiting counts. The section map is one module, `media_nav.py`; Home is
the registry area with `layout: shelves`. Movies/TV "My films / My shows / Tonight" went live in F3 (below).

**Media library pages (F3, 2026-10-06).** `/media/movies`, `/media/movies/tonight`, `/media/tv`, `/media/tv/tonight` and `/media/years?kind=movie|tv`, built from the jellyfin `movies`/`shows` arrays by `media_library.py` (`film_rows`, `show_rows`, `deal_tonight`); "New this week" uses the arr `at` field. Absent arrays render "Library list not available yet".

**Downloads (2026-10-06).** `/media/downloads` (Server sub-tab after Library) lists the live qBittorrent torrents. `media_downloads.py` joins the arr queue to qBittorrent (`download_id` == torrent hash) for live progress on the Home Downloading shelf, Library "This week" badges and title-page badges; a Sonarr season pack (one queue row per episode, one `download_id`) collapses to one row, e.g. "Show · S01 · 13 episodes".

**Server area (WP-S1, 2026-10-06).** Registry area `server` (`layout: server`, last in the Areas rail, accent `#9AA4B2`,
icon `server`) renders `server.html` at `/server` and `/a/server` — not to be confused with the Media "Server" sub-section.
`server.py` (pure) builds, top to bottom: KPI row per tile (Services = `media_status`, System = `system`, Updates = `wud`,
Homepage + Portainer links), System band (CPU, RAM free/total, uptime, each volume with a hairline bar and % used),
Services grouped Media / Downloads / System by app id (unknown ids → System; Up/Down word beside the dot), Updates
(`N monitored · N updates` + a row per pending update), Attention (any service Down, any volume ≥ 85 % used, the
`media_backup` warning — none / older than 36 h) and Counts (Jellyseerr pending/approved/available, qBittorrent
downloading/seeding/speeds, arr downloading / this week / disk rows). Each band says "Not connected" on its own when its
snapshot is missing. Tile `detail` links are anchors (`/server#services`, `/server#updates`). Not yet: "Last sweep" and
connector-error attention items (the hub does not read `_runner.json`; TODO for WP-S4).

Media modules: `media_discover.py` (live Jellyseerr search, shelves, title pages, Request),
`media_db.py` (ratings + diary, per owner), `media_backup.py` (nightly `media.db` dump),
`media_write.py` (same-origin write guard). The hub's Media KPI card is first (`hub_rank: 1`,
`media_hero()` inside `_kpi.html`) with a sibling Jellyfin "Jump back in" deep link. A hx-boosted page that
carries a new `joey-asset-v` meta forces a full reload so new CSS is never mixed with old pages.

**Film page (F9 + F10, 2026-10-06).** Cast and director names open `/media/person/{tmdb}` (F11, `media_person.py`: portrait, bio, "On your server" shelf, every credit with status words). Library rows are whole-row links; New this week items open the film page (item page when on the server, title page by TMDB id, title-match fallback for Sonarr's tvdb keys). `media_film.py` + `media_item.py` + `media_files.py` render ONE Cinema-layout page for
every title, on the server or not: `/media/title/{kind}/{tmdb}` and `/media/item/{jf_id}` build the same page (live reads:
`docs/connector-contract.md`, eighth exception; each section degrades to words when its source is down). Top to bottom: a
status line in words ("On your server · 4K · HDR · watched 3 Oct · you rated 8", or "Not on your server · Requested ...");
the backdrop hero; a numbers strip (your score or the picker, community, IMDb, Rotten Tomatoes, runtime with "ends HH:MM if you
start now", rating); a button row — **Play ▶ (Resume / Play again / Next to watch) is the only Jellyfin hop**, plus Rate,
Watchlist, Request, Trailer and Open in Jellyseerr (the hub hero's "Jump back in" stays a direct Jellyfin link). The file strip
reads Jellyfin live (10 min cache, Available / Partly available only) as Dolby-style pills: black Dolby pills with a double-D
glyph, DTS and HDR pills, plain pills for resolution, codec, container, channels and size; the word is always present.
`hub/static/badges/<id>.svg|.png` overrides a pill with official artwork; no brand files are shipped (see its README). Below:
poster + facts (languages, release dates, added, watched, requested), overview, cast portraits (initials when none), director /
creators as search chips (no follow or lists), where to watch (AU, JustWatch links), then seasons — an episode map of squares
for on-server shows, lazy `<details>` for off-server ones (`GET /media/title/tv/{tmdb_id}/season/{n}`) — and Collection /
Similar / Recommended shelves marked "On server". Every row with a Jellyfin id opens this page; an episode id shows an episode
header over the show page.

Rating level (2026-10-06): each owner chooses Show / Season / Episode with the chips on To rate
(`POST /media/settings/rating_level`, stored per owner in `media.db` `setting`). The To rate inbox, the rate
picker and the score shown on rows follow it; a row lacking that level's key falls back to its show, and
rankings count show + season ratings only.

Watchlist (F6, 2026-10-06): `media_watchlist.py` + `media_watchlist_db.py`. A "Watchlist" tab under Movies and TV Shows
(`/media/movies/watchlist`, `/media/tv/watchlist`); add from a title page ("+ Watchlist") or the small "+" on a Discover
result. Each row carries a status word: On disk, Requested, Processing, Partly available or Not on server. A title the owner has
watched leaves the list by itself when the page renders.

Play recorder + History (F7, 2026-10-06): `media_plays.py` / `media_plays_db.py` record every watch (see
`docs/connector-contract.md`, seventh exception). Server tabs are Live · History · Library · Downloads · Requests · Health;
History shows plays, hours, top ten, busiest day and plays by hour over 7 / 30 / 90 days, this year or all time. Home gains a
"Most played · 30 days" shelf (`build_shelves` in `main.py`).

Diary per episode (F8, 2026-10-06): jellyfin-synced diary rows are one per episode; `media_db.group_diary` folds a day's
episodes of one show season into a single line ("S2 E3-5"), and a rewatch mark shows when the title was logged on an
earlier day. The "where" filter is not built. Older show-level rows still render.

Poster sizes: list rows use `.poster.sm` (56 px tall); shelf cards are 144 px wide (`.shelf-item`, `.shelf-cell`), both in
`static/control-surface.css`.
