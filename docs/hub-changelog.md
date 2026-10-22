# Hub changelog

The dated narrative of how the hub got its current shape (shell, styling, Media UX rounds, Awards, Server area, hub core). Historical: later entries patch earlier ones in place, so where two disagree the newer date wins and `hub/README.md` is the current architecture. Moved verbatim from `hub/README.md` on 2026-10-09 (corrections: cast photos are h=400, the Server table reads "Sweeps · 24 h").

**Shell (MediaHub guide, Phase 2 of 4, 2026-10-06).** `templates/base.html` is the one frame (guide §5). Sections =
Hub, any area with `rail_section: home`, Weather, then the other visible areas, in `areas.yaml` order (today: Hub ·
Media · Weather · Calendar · Server). Top bar `.topbar` (sticky from 768 px, 56 px row, 72rem wide): the kangaroo mark
`static/brand-joey.jpg` + "Joey" linking to `/`, one pill per section (`.toplinks`, shown from 768 px), and at the right
the user chip from `identity.py` (the Access header decides the owner view, `?owner_view=` only works locally). Phone
tab bar `.tabbar` (< 768 px): five slots, icon over label; with more than five sections the fifth slot becomes "More", a
`<details class="more">` sheet listing the rest. Areas with `hidden: true` are parked: no pill, phone tab or hub card,
page still serves. **Media phone bar (2026-10-07):** every page extending `media_base.html` (it sets `media_mode`; the
shelves area page `/a/<id>` included) swaps the phone bar for the six Media sections from `media_nav.py` (`short` label +
`icon` per section: Home = the shelves area page, Movies, TV, Diary, Server, Discover), six equal slots, no More, active
slot by `media_nav.active_section` (the section-tab rule); the nav carries `hx-swap="innerHTML show:window:top"` so every
tap (Home on Media home too) lands at the top. The top-bar Joey brand is the way out. **Docked Media sections
(media-ux5, 2026-10-09; desktop ≥ 768 px):** on Media pages the top bar wraps its section pills in `.topswap` beside a
server-rendered copy of the Media section row (`_media_tabs.html` `media_dock()`: `nav.toplinks.topdock`, same sections,
amber counts, the active section as `class="on"` — the bar keeps one `aria-current`, its Media pill). The page's own
section row carries a 1 px `.dock-sentinel`; an IntersectionObserver in `base.html` (re-attached after every htmx settle,
so boosted navigations work) adds `.topbar.is-docked` once the sentinel is under the 56 px sticky bar, and CSS slides the
pills out and the Media row in within the same grid cell (no height change; no transition under reduced motion). Phones
keep the bottom bar; no layout is built in JS. **Superseded 2026-10-13 (nav-tidy, desktop):** the scroll-docking is gone (no `.topswap`, `.topdock`, `.dock-sentinel`, `.is-docked`, observer). On Media pages the bar renders the Media row as its own `.toplinks` nav (`media_bar()`, active = `aria-current="page"`) instead of the Joey pills, from the start; the in-page section row (`.sectabs-page`) is hidden from 768 px; the first tab sits flush left; `.waitcount` is a fixed 18 px box with a 6 px left margin. Media pages also link
`static/manifest-media.webmanifest` ("Joey Media", `start_url` `/a/media`, `scope` `/`, shortcuts Movies/TV/Server/
Discover) and set `apple-mobile-web-app-title` "Joey Media"; every other page keeps `static/manifest.webmanifest`. Boosts
swap only `<body>`, so the `htmx:beforeSwap` script in `base.html` copies the response's manifest link + iOS title into `<head>`. No
service worker is involved (the hub registers none). Page frame `main.page`: centred, 72rem, bottom padding clears the tab bar.
**Phone fit (media-ux5, 2026-10-09):** nothing may be wider than the screen — phone library grids (`.libgrid` below
640 px) are exactly `repeat(3, minmax(0, 1fr))` with 10 px gaps (fits 320 px), grid children carry `min-width: 0`,
titles ellipsis, chip rows wrap, sideways rows (`.sectabs`, `.carousel`, cast/makers) scroll inside themselves, and
`html` + `body` have `overflow-x: clip` as the last guard (clip, not hidden, so the sticky top bar keeps working). The
tab bar is `position: fixed` to the screen edges, a direct child of `<body>` with no transformed / filtered ancestor
(either would re-anchor it). Measured in the preview at 320/375/390/430 px on 12 Media pages: `scrollWidth ==
innerWidth`, bar bottom == `innerHeight` after scrolling. The sideways swipe / drifting bar on the iPhone was iOS focus
zoom (14 px inputs), fixed by the 16 px rule below.
**No zoom (media-ux5, B.'s explicit choice 2026-10-09):** pinch / focus zoom kept getting stuck on the iPhone (the page
stayed zoomed, so it panned sideways and the bottom bar drifted), so Joey cannot be zoomed: the viewport meta is
`width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover`; `html` has
`touch-action: manipulation` (no double-tap zoom) and `text-size-adjust: 100%`; every input / select / textarea is 16 px
below 768 px (iOS zooms in on focus under 16 px); and because iOS Safari ignores `user-scalable=no`, `base.html` cancels
its `gesturestart` / `gesturechange` events (they fire nowhere else). **Accessibility trade-off, accepted:** WCAG 1.4.4
(resize text) asks that users can zoom; on this private two-person app B. chose a page that never gets stuck over pinch
zoom. iOS "Larger Text" does not reach a web page (it has no Dynamic Type hook here), but Safari's own page zoom (aA menu)
and the system Zoom accessibility feature still work. Undo by restoring the old meta and removing the gesture guard. Page header: the
`_pagehead.html` macro (`pagehead(title, sub, eyebrow, backdrop, actions)`; called with `{% call %}` the caller's markup,
e.g. section tabs, sits on the band) is used by `hub.html`, `area.html`, `server.html`, `weather.html` and
`media_base.html`: a full-bleed band with a darkened backdrop (Media home uses the hero's) or a faint indigo glow, the
title, and one sub-line of facts joined by " · ". Section tabs `.sectabs` (Media sections; `.sectabs.sub` for sub-tabs):
pills that scroll sideways on a phone, underlined from 768 px, amber `.waitcount` pills. Single dark theme: no theme
toggle, one `theme-color` meta (`#09090b`), Geist self-hosted (no Google Fonts link). All shell CSS is in the "Shell"
section of `static/control-surface.css`; every colour is a token on the one `:root` block and no literal colour appears
outside it (a test enforces it). Page content is described under "Styling" below. `/weather` = Today stats strip + Next 24 hours
(inline-SVG chart + hour rows, `weather_forecast()`) + Rain radar + Next 7 days rows, the chart/hours/days absent for a
pre-2026-10-06 snapshot. Rain radar panel (RADAR SUPERSESSION, 2026-10-07): a Windy embed iframe
(`windy_embed_url()`: `embed.windy.com/embed2.html`, overlay=radar, zoom 8, metric, coords from `WEATHER_LAT`/`WEATHER_LON`
with Newport VIC as fallback; the place name in the labels is `WEATHER_PLACE`, default "Newport VIC", a
Jinja global from `hub/shell.py`), lazy-loaded, captioned, with a static "Needs internet" note; shown even when the weather
snapshot is absent; a square column beside the forecast from 1100 px, below it on narrower screens. The 2026-10-06 BOM
layer-stack panel is parked: `weather_radar()` and `GET /weather/radar/{name}` (allowlisted
names from `SNAPSHOT_DIR/radar/`, else 404) remain, but `/weather` no longer builds its context and its CSS was removed
(2026-10-09, T3); the connector fetch needs `RADAR_LOOP=1`. Greeting
clock: `_now_home()` (Australia/Melbourne).

## Hub core (T3, 2026-10-09)

- **One page shell:** `hub/shell.py` holds the ONE `Jinja2Templates` instance (main.py and server_updates render
  through it; the media routers' own envs get a copy of every shell global until the media WP switches them), the
  asset version `static_v` (a hash of the whole `hub/static` tree), the `weather_place()` / `img_letters()` globals and
  the response layers. Templates are not re-stat'ed per render unless `HUB_DEV=1`.
- **Response headers:** one pure ASGI `ShellMiddleware` — HTML pages `no-store`; `/static/*` with `?v=` →
  `public, max-age=31536000, immutable`, without → one hour; one request log line per page (`METHOD path owner=you|her|none
  -> status`, never the email; `/healthz`, `/static/`, `/img/` are silent; uvicorn's access log is off). `Compress` =
  `GZipMiddleware(minimum_size=1024)` for text; `/img/` and binary files pass untouched.
- **Snapshots:** `store.get_snapshots` parses each envelope once per `(mtime_ns, size)` (a file changed in the last
  second is always re-read; `age_minutes` is recomputed per call — treat `Snapshot.data` as read-only); a request
  reads the dir once (`main.get_snapshots(request=...)` keeps it on `request.state.snaps`). `store.connected()` /
  `data_of()` are the one "anything to show" rule, `store.parse_utc()` the one timestamp parser, `store.ago_text()`
  the one relative time ("just now" / "12m ago" / "3h ago" / "2d ago"; stale tiles "Stale · 5h ago").
- **Constants:** `hub/ids.py` — snapshot ids, `home_tz()` / `home_now()` (Australia/Melbourne), `areas_path()`.
- **Hub page cost:** the Server card is cached 60 s while the snapshots and backup word are unchanged; "Feeds N/M live"
  counts the visible areas' feeds that are fresh or stale; `status` is built for the hub page only. The Server card's
  "Needs attention" is its own `warn` state (amber like stale).
- **Background loops:** one `_every(label, first_s, every_s, fn)` helper; errors are logged by type only.

## Styling (MediaHub guide, complete 2026-10-06)

Spec: `docs/style-guide.md` (Jack's MediaHub guide, adopted for all of Joey). History in one sentence: the Apex look
(2026-10-06 morning) was replaced the same day by the guide in four phases: 1 tokens + recipes, 2 shell, 3 Media, 4 Hub /
area / Server / Weather + copy pass. Everything lives in `static/control-surface.css`; plain CSS, no Tailwind.

**Rules.** One dark theme (no toggle, no light mode, `color-scheme: dark`). Every colour is a token on the single `:root`
block; no literal colour anywhere else (tests enforce it). Colour is for meaning only: emerald good/done, amber "something
to do" (stale, to rate, attention; never a permanent state), red down/danger, indigo the one primary action and active
tabs, sky info/links, teal upcoming, gold a perfect 10. The per-area accent is gone entirely (field removed from `areas.yaml` and
the registry, 2026-10-06). The weather radar ramp (`--rad-*`) and the Dolby/format pills are data colours.
Facts are joined with `<span class="sep"> · </span>` (`_rows.html` `meta()`); a missing value is "—"; lengths are "2h 47m"
(`media_library.runtime_text`); buttons and labels are sentence case (uppercase only via `.seclabel`); British/Australian
spelling; every icon-only control has an `aria-label`.

**Tokens.** `--bg/--fg`, zinc text steps `--text-1…6`, white-alpha surfaces and lines (`--surface`, `--line`,
`--line-soft/-hover/-focus`, `--hover`, `--soft`), `--primary/--primary-hover`, state tokens (`--good`, `--amber`, `--bad`,
`--orange`, `--fuchsia`, `--teal`, `--sky`, `--gold`), row tints/bars (`--watch-*`, `--new-*`, `--done-*`, `--down-*`),
score grades `--score-1…9`, `--appicon-bg` (the white tile behind a service logo). Eight never-read older names and the
parked radar ramp `--rad-*` were removed 2026-10-09 (T3).

**Recipes** (one line each): `.btn` + `.btn-primary/-secondary/-ghost/-danger/-glass/-white/-icon`, `.btn-sm` buttons;
`.chip` (`.on`) filter chips; `.input/.textarea/.select/.label` form controls; `.seclabel` (uppercase section label) and
`.microlabel` (tiny label over a value); `.sec` + `.sechead` a titled group with an "All" link, `.metaline` one line of
facts; `.listbox` + `.row` (`.row-poster/.row-body/.row-title/.row-meta/.row-side/.row-score/.row-rank`, states
`.is-watching/.is-new/.is-complete/.is-down`, `.has-form` for a row holding a form) the list; `.bar` hairline progress;
`.stats` + `.stat` (`.stat-number/.stat-word`, `.stat.wide`) the numbers strip; `.badge` (+ `.badge-watching/-new/-complete/
-wait`) outline pills; `.st-*` status words (`.st-up/.st-down/.st-off` muted grey/.st-warn/.st-good/media words);
`.score-1…9/.score-none`; `.waitcount`; `.panel` (+ `.panel-warn` amber, `.kv` label/value lines); `.empty` one-sentence
empty state; `.confirm*` inline confirmation; `.toolbar/.search/.chips`; `.poster-grid`, `.carousel`, `.card-poster`,
`.card-cell`, `.card-pic`, `.poster-score/.poster-tag`; `.pagehead*` header band, `.sectabs`, `.topbar`, `.tabbar`;
`.fold` (a `<details>` with a `.seclabel` summary); `.cols` side-by-side groups.

**The shell** is `base.html` (top bar from 768 px, phone tab bar, `main.page`) + `_pagehead.html` (see above).

**Where each page's components come from.** *Hub* (`hub.html`): `_kpi.html` summary tiles (`.panel.tile`: `.microlabel`
area name, `.stat-number/.stat-word` value, one `.row-meta` line, icon at the right; stale = `.badge-wait`, not connected
= muted `.st-off` word; a `.bar` or a per-day spark only from real data); `_upcoming_table.html` "Next 7 days"
(`.row.upc`: grid with uppercase column heads from 640 px, stacked on a phone); `_weather_glimpse.html` (a `.stats` strip,
glyph + condition word); `_shelf.html` Recently watched on Media's `.carousel` of `.card-poster`s (the hub's Continue watching band was removed in media-ux2, 2026-10-08 — Media home keeps it). *Area pages*
(`area.html`, also hidden areas): tiles (the weather tile never renders here — hub + /weather only, 2026-10-08), the Calendar upcoming rows, and for areas reading the
jellyfin/media_status snapshots Media-style sections (`.row`s, `.row-score`, `.gold-glow-sm`). *Server* (`server.html`,
`server_update.html`): System = `.stats` strip (volumes carry a `.bar`), Last 24 h = `.spark-band` panel (`.spark-*`,
stroke `--primary`), Services = `.sec` groups of a `.svc-grid` of `.svc-card` links (WP-U3: 40 px `.svc-logo` on
`--appicon-bg`, `.st-up/.st-down` words beside a `.svc-dot`, `.svc-card.is-down` tint; the unused 20 px `.appicon` rule was
removed 2026-10-09), Monitors/Updates/Attention rows (Update now `.btn-primary .btn-sm`, Ignore `.btn-ghost .btn-sm`, the
Ignored `.fold`, pending `.badge-wait`, Attention an amber `.panel-warn`), Counts = three `.panel.kv`s. *Weather*
(`weather.html`): Today `.stats` strip, 24-hour chart `.panel` (+ a `.fold` of hour `.row`s), radar `.panel`, 7 days as
`.row`s (glyph, day, condition word, range in `.row-side`). *Media*: below.

**Media (MediaHub guide, Phase 3 of 4, 2026-10-06).** Every Media page is built from the recipes only (the Media block
at the end of `control-surface.css` holds documented modifiers, tokens only). Lists
are the guide's row recipe with no box round them: `.listbox` of `.row` (an `<a>` when it resolves; `.row.has-form` +
`a.rowlink` overlay when it holds the 1-10 picker or another form), poster `.row-poster`, `.row-body` with `.row-title`
and one `.row-meta` line of facts joined by a dim `.sep` " · " (`_rows.html` `meta()`), the score big on the right
(`_rate.html` `score()`: `.row-score` + `.score-N`, "—" in `.score-none`); state rows `.is-watching` (now playing),
`.is-new` (just arrived), `.is-complete` (finished downloads), `.is-down` (an app down) with the matching `.badge-*`.
Sections are a `.seclabel` ("CONTINUE WATCHING · 3") over the group; poster cards are `.card-poster` /
`.card-cell` (action beside the title, never over the picture) in `.poster-grid` or a snap-x `.carousel`, with a
`.poster-score` badge and a teal `.poster-tag`. Home folds "Playing now" into the page header (eyebrow, title, facts
sub-line, drifting backdrop, `.btn-glass` "Open in Jellyfin"). The film page is the detail hero (`.pagehead.hero-detail`:
backdrop, poster leading — centred 62 %/260 px on a phone, 280 px from 640 px, 360 px from 1024 px — tagline,
`.facts-line`, credits with IMDb/TMDB/Letterboxd site pills (`.scorepill.sitepill`, media-ux4), emerald status line, one `.btn-white` primary plus 36 px
`.btn-icon`s; watchlist toggles sky with `aria-pressed`), then the `.stats` strip, the spec sheet `.panel` (F10 pills
unchanged as the format logos), cast, seasons, shelves. A perfect 10 gets `.gold-glow-sm` on a row poster (`.gold-glow`
on big ones) and `.gold-text-glow` on the number. Toolbars are `.toolbar` (`.search` icon + `.input`, `.chip`s,
`.select`); empty states are `.empty`; confirmations are an inline `.confirm` panel (year Reset), never a browser dialog.
Removed: `.glassbtn`, `.hero*`, `.shelf*` (`.shelfhead/.shelftop/.shelf-row/.shelf-item/.shelf-cell`), `.waitchip`
(now `.badge-wait`), `.libctl`, `.launch`, `.actbtn`, `.ratebox` (now `.ratepick`/`.rated`), `.podium` (rebuilt),
`.fbadge`, `.seasonrow`, `.eprow`, `.num*`, `.yeartile/.yearnum`, `.pgitem/.pgtitle/.pgsub`, `.wl*` grid, the old `.chip`
and `.filters` rules. Phase 4 then removed `.uplist/.uprow`, `.medialist`, `.poster.sm`, `.chip.score` too.

**Media section nav (2026-10-06).** Every `/media/*` page and the Media shelves page render in
`templates/media_base.html`, which extends the Joey shell (the earlier "Return to Joey" frame was retired the same day)
and puts the section tabs **Home · Movies · TV Shows · Diary · Server · Discover** on the page header, with sub-tabs and
amber waiting counts; the phone tab bar stays Joey's. The section map is one module, `media_nav.py`; Home is
the registry area with `layout: shelves`. Movies/TV "My films / My shows / Tonight" went live in F3 (below).
**Nav tidy (2026-10-13, B.).** Five sections: **Overview** (was Home; id / href / icon unchanged) · Movies · TV shows ·
Activity · Discover, every section and tab label sentence case (supersedes the awards-year "To Rate"). Movies / TV tabs:
My films|My shows · To rate · Awards (Watchlist and Tonight left the nav; their routes, pages and the title-page
Watchlist button stay). The Diary section folded into Activity: Live · History (`/media/diary`, title "History") ·
To rate (`/media/history`, carrying the amber to-rate count, as does the Activity section) · Library · Downloads ·
Requests · Health. The play recorder `/media/server/history` ("Play stats") keeps its URL with no tab, linked from a
metaline on the diary page.
Rows are whole-row links everywhere (2026-10-06): the row is the `<a class="row">` (title plain `.row-title` text); rows holding a 1-10 picker use an `a.rowlink` overlay instead; rows with nothing to resolve stay a plain `<div>`.

**Media library pages (F3, 2026-10-06).** `/media/movies`, `/media/movies/tonight`, `/media/tv`, `/media/tv/tonight` and `/media/years?kind=movie|tv`, built from the jellyfin `movies`/`shows` arrays by `media_library.py` (`film_rows`, `show_rows`, `deal_tonight`); "New this week" uses the arr `at` field. Absent arrays render "Library list not available yet". The "By year" tab was dropped from the Movies / TV Shows tab rows (media-ux2, 2026-10-08): `/media/years` and its year pages stay served and reachable by URL only (nothing else in the app linked to it; the Movies / TV "to place" waiting count still counts unranked years).
**Grid view (media-ux4, 2026-10-08).** `/media/movies` and `/media/tv` open as a **grid** by default: `.poster-grid.libgrid`
of `.card-poster` cards at the Media home shelf size (`repeat(auto-fill, minmax(104px | 136px from 640 px, 1fr))`, poster
h=240 — the size the library warm-up warms), each card one link with poster, title, year and the state in words
(`media_library.card_state`: Watched · In progress · Not watched — a film is in progress while it sits in the viewer's
resume list; a show by finished / watching / not started; no word without watch marks) and your score as the poster
badge. A **Grid / List** segmented control (`.seg`, plain links keeping search / sort / grouping) sits at the end of the
toolbar; `?view=grid|list` sets the `media_libview` cookie (path `/media`, a year), so the server draws the remembered view
with no flash; no query → the cookie → grid. Grouping (Watched / Not yet watched; Watching / Not started / Finished),
search and sort work in both views; List is the media-ux2 rows.

**Media home shelves (media-ux2, 2026-10-08).** `build_shelves` now gives Continue watching · Recently added ·
Downloading (when anything is) · New from people you follow · Most played. "This week" (arr airings) and "Recently
watched" were dropped from Media home only — Server → Library keeps This week, Diary > To rate keeps Recently watched.

**Downloads (2026-10-06).** `/media/downloads` (Server sub-tab after Library) lists the live qBittorrent torrents. `media_downloads.py` joins the arr queue to qBittorrent (`download_id` == torrent hash) for live progress on the Home Downloading shelf, Library "This week" badges and title-page badges; a Sonarr season pack (one queue row per episode, one `download_id`) collapses to one row, e.g. "Show · S01 · 13 episodes".

**Server area (WP-S1, 2026-10-06).** Registry area `server` (`layout: server`, last section in the top bar and tab bar,
icon `server`) renders `server.html` at `/server` and `/a/server` — not to be confused with the Media "Server" sub-section.
`server.py` (pure) builds, top to bottom: KPI row per tile (Services = `media_status`, System = `system`, Monitors = `uptime_kuma`,
Updates = `wud`, Homepage + Portainer links), System band (CPU, RAM free/total, uptime, "Last sweep N min ago" from
`_runner.json` `ran_at` with "stale" past 90 min, each volume with a hairline bar and % used),
Services grouped Media / Downloads / System by app id (unknown ids → System) as a card grid (WP-U3, 2026-10-07 — see
below), Monitors
(Uptime Kuma: status word + dot + response ms per monitor, down first; **removed 2026-10-12**, see below), Updates
(`N monitored · N updates` + a row per pending update), Attention (any service Down, any volume ≥ 85 % used, any
Uptime Kuma monitor Down/Pending, the `media_backup` warning — none / older than 36 h, and every connector whose
last `_runner.json` result is an error, with its sanitised reason) and Counts (Jellyseerr pending/approved/available, qBittorrent
downloading/seeding/speeds, arr downloading / this week / disk rows). Each band says "Not connected" on its own when its
snapshot is missing. Tile `detail` links are anchors (`/server#services`, `/server#monitors` — `#services` since 2026-10-12 —, `/server#updates`). `_runner.json` is read by
`store.get_runner()` from the snapshot dir (WP-S4); missing or malformed simply omits Last sweep and runner errors.

**Server → Update now / Ignore (WP-U1, 2026-10-06).** `server_updates.py`. Each pending update row in the Updates band shows
"Update now" when the `wud` row is `auto` (WUD's `dockercompose.local` trigger applies), else the chip "Manual · excluded"
(gluetun, qbittorrent, prowlarr, uptime-kuma, wud are notify-only), plus an Ignore button. Update now opens
`/server/updates/{name}/run?step=confirm` (container, image, current → new, kind, the "about a minute" warning); its
same-origin POST asks WUD to run the trigger (contract doc, tenth exception), records a `server_update_runs` row and
redirects to `/server#updates` with "Update requested for X" / "WUD refused (HTTP n)" / "WUD unreachable". Ineligible rows,
a missing WUD env or a container not pending in the snapshot get an explanatory page (409), never a call. The row shows
"Requested N min ago" until the snapshot's tag moves on. Ignore keys on (container, new tag — or current tag for a digest
update) in `server_update_ignores`; ignored rows fold into "Ignored (N)" with Unignore, and the band reads
`N monitored · N updates · M ignored` (the connector's own tile summary is unchanged). Live check after deploy:
`docs/server-updates-live-check.md`.

**Server card, durable Attention, Sweeps, Discord (WP-U2, 2026-10-06).** The hub's Server KPI card no longer shows the
`services` tile summary: `server.hub_card()` (wired in `hub/main.py` `server_card_state`, keyed by `layout: server`) writes
line 1 "All up" / "2 down · Prowlarr · Sonarr" and line 2 "N updates" (ignored ones excluded, omitted at 0) · "disk N%"
(fullest volume) · "N monitors down" (when > 0). When Attention is non-empty the card wears the amber stale badge with the
words "Needs attention" (no new colour); a missing `media_status` snapshot still reads "Not connected". Attention items are
now keyed (`attention_items()`: `down:<app>`, `disk:<path>`, `kuma:<monitor>`, `backup`, `sweep:<connector>`). Sweep
failures are durable: `store.get_runner_history()` reads the tail of `_runner_history.jsonl` (last 2 MB, up to 1000 lines,
malformed lines skipped) and `server.sweep_stats()` counts the last 24 h per connector — Attention says
"wud failed 3 of the last 24 sweeps · <sanitised reason>" only while the connector's latest run is still an error; the
Attention card's "Sweeps · 24 h" rows list every connector (runs · failed · last ok). No usable history ⇒ the old
`_runner.json` "<id> sweep failed" items. `server_alerts.py` pushes each NEW item to Discord ("Joey Server: <text>", max
5 per cycle, 10 s timeout) when `SERVER_DISCORD_WEBHOOK` is set, remembering keys in media.db `server_attention_seen`
(a key that leaves Attention loses its row, so a recurrence notifies again). It runs after every `/server` render (a
response background task) and on a hub loop beside the media backup one (first ~60 s after start, then every 5 min).
Unset webhook ⇒ no call, no table writes; failures log status/type only.

**Not-configured connectors (WP-U3, 2026-10-07).** B.: "silence parked alerts". A connector is *not configured* — a
setup task, not a failure — when (a) its latest error is a `MissingCredential` (the runner records
"MissingCredential: <id>: missing environment variable …"), or (b) no visible area reads its snapshot (every area whose
tiles reference it is `hidden`, or none does — `server.live_snapshot_ids(registry)`). Rule (a) alone suffices: a live
area's connector with its env unset (e.g. jellyseerr) is also not configured. Not-configured connectors never become
Attention items, never post to Discord and never put the hub card in its warn state; the "Sweeps · 24 h" table still
lists them with the words "Not configured" instead of "Failing". Because they leave Attention, `server_alerts.sync`
deletes any `server_attention_seen` row they had, so a later genuine failure notifies again. The hub loop passes the
loaded registry; `check_once()` without one reads `AREAS_PATH` / `config/areas.yaml`.

**Services card grid (WP-U3, 2026-10-07).** B.: "logos … so much easier to find them in the card form". Each group is a
Homepage-style grid (1 column on a phone, 2 from 640 px, 3 from 1100 px): one card per app, the whole card the link
(`target=_blank rel=noopener`, no nested `<a>`), logo left (`<img alt="" width=40 height=40>` from
`/static/svc/<file>?v={{ static_v }}`), name + one-line subtitle (`server.SERVICE_SUBTITLES`; unknown ids name only),
the Up/Down WORD beside the dot, and the Uptime Kuma response ms of the monitor whose name IS the app name
(case-insensitive, exact since 2026-10-09; a Down card shows its note instead). Logos are vendored in `hub/static/svc/` (dashboard-icons,
Apache-2.0; sources in its README) and mapped in `server.SERVICE_LOGOS`; an id with no logo renders a neutral tile with
its initial letter and the area's line icon, and a test fails if a `MEDIA_APPS` id has neither a logo nor a `NO_LOGO`
entry. **LAN links (T3, 2026-10-09):** `gated_hrefs:` in `config/areas.yaml` (app / tile id → https hostname;
homepage → `https://homepage.joeyhome.net` only) overrides a card's or link tile's href; a href that is still a LAN
address (`server.is_lan`: private / loopback IP, dot-less, `.local`, `.lan`) renders as a plain card / tile with the
word "LAN" and no link, since it is dead off the home network. **Since 2026-10-10 a Services card links to its LAN address
anyway** (still saying "LAN"; it opens on the home network only) — B. asked for clickable cards; link tiles are unchanged. The Services tile on this page says what the hub
Server card says (`server.services_words`: "All up" / "1 down · Prowlarr"). Discord pushes stop retrying an item
after 3 failed posts (`server_attention_seen.fails`) until it clears and returns.

**Server → Last 24 h history (WP-U4, 2026-10-06).** `server_history.py` samples the `system` snapshot into media.db
`server_system_samples(ts, cpu_pct, ram_pct_used, ram_free_gb, load_1m, volumes)` — `ts` is the envelope's `updated_at`
(UTC `…Z`), `volumes` JSON `[{path, pct_used, free_gb}]` with `pct_used` recomputed from free/total to two decimals. A row
is inserted only when `updated_at` is newer than the last stored `ts` (≤ 1 row per 2-min snapshot; renders never
duplicate); no row when the snapshot is missing or `status != ok`; each insert deletes rows older than 8 days. It runs on
the WP-U2 paths: after every `/server` render (a second response background task) and on the same 5-minute hub loop as
the Discord push. `server.history_band()` builds the "Last 24 h" band directly under System: three inline-SVG
sparklines (no JS; the weather chart's conventions) for CPU %, RAM % used and the fullest volume's % used, each with
"CPU 4–38 %, now 15 %" text, plus a 7-day disk line "Disk: 8.0 % → 8.4 % over 7 days · ~N days to 85 % at this rate"
(least-squares slope; "flat" when not rising or the projection is ≥ 10 years; under 24 h of history it says
"projection after 24 h of history"). Fewer than 2 samples in 24 h ⇒ "Collecting history — first chart after a few
sweeps". Reads never create media.db.

Media modules: `media_discover.py` (live Jellyseerr search, shelves, title pages, Request),
`media_db.py` (ratings + diary, per owner), `media_backup.py` (nightly `media.db` dump),
`media_write.py` (same-origin write guard). The hub's Media KPI card is first (`hub_rank: 1`,
`media_hero()` inside `_kpi.html`) with a sibling Jellyfin "Jump back in" deep link. A hx-boosted page that
carries a new `joey-asset-v` meta forces a full reload so new CSS is never mixed with old pages.

**Film page (F9 + F10, 2026-10-06).** Cast and director names open `/media/person/{tmdb}` (F11, `media_person.py`: portrait, bio, "On your server" shelf, every credit with status words). Library rows are whole-row links; New this week items open the film page (item page when on the server, title page by TMDB id, title-match fallback for Sonarr's tvdb keys). `media_film.py` + `media_item.py` + `media_files.py` render ONE Cinema-layout page for
every title, on the server or not: `/media/title/{kind}/{tmdb}` and `/media/item/{jf_id}` build the same page (live reads:
`docs/connector-contract.md`, eighth exception; each section degrades to words when its source is down). Top to bottom: a
status line in words ("On your server · 4K · HDR · watched 3 Oct · you rated 8", or "Not on your server · Requested ...");
the backdrop hero; a numbers strip (score pills — IMDb · RT · Metacritic · TMDB · Yours, media-ux4 below — then runtime with
"ends HH:MM if you start now" and the certificate); a button row — **Play ▶ (Resume / Play again / Next to watch) is the only Jellyfin hop**, plus Rate,
Watchlist, Request, Trailer and Open in Jellyseerr (the hub hero's "Jump back in" stays a direct Jellyfin link). The file strip
reads Jellyfin live (10 min cache, Available / Partly available only) as Dolby-style pills: black Dolby pills with a double-D
glyph, DTS and HDR pills, plain pills for resolution, codec, container, channels and size; the word is always present.
`hub/static/badges/<id>.svg|.png` overrides a pill with official artwork; no brand files are shipped (see its README). Below:
poster + facts (languages, release dates, added, watched, requested), overview, cast portraits (initials when none), director /
creators as headshot cards in the hero (media-ux4), where to watch (AU, JustWatch links); on a TV page the seasons sit directly
under the overview (2026-10-08) — an episode list for on-server shows (below), lazy `<details>` for off-server ones
(`GET /media/title/tv/{tmdb_id}/season/{n}`) — and Collection (a banner under Overview since media-ux3, below) /
Similar / Recommended shelves marked "On server". Every row with a Jellyfin id opens this page; an episode id shows an episode
header over the show page.

**Film page speed (media-speed, 2026-10-07).** A cold open overlaps its live reads instead of chaining them: the Jellyseerr
title / ratings / similar / recommendations start as soon as the TMDB id is known (from the URL, else from the library
snapshot — an episode via its up-next / history row's show key), alongside the Jellyfin item read; the collection read
starts the moment the title body names one; a show's per-season episode reads run side by side; an episode page reads its
show once (the episode build fetches it through the cache) and a film's file strip rides on the item read itself. One
snapshot read per film request is shared with the Media frame. Caches: request / availability state (title body, similar,
recommendations, collection, person credits, Jellyfin item + seasons) keeps the 10 min in-process cache; metadata with no
user state (ratings, a person's biography, a season's episode list) rides a 6 h cache kept in memory **and** on disk
(`META_CACHE_DIR`, default `<IMG_CACHE_DIR>/meta/`, one JSON file per path) so a deploy restart doesn't empty it. A 404 is an
answer and is remembered (short cache for the short paths, 6 h for metadata); a network failure is not. TV titles ask
`ratings` only — Jellyseerr has no `tv/{id}/ratingscombined`, which was the 404 every TV page logged. **Warm-up**
(`media_warmup.py`): ~60 s after startup and every 3 h, a background pass walks the Media home shelves' titles (Playing now,
Continue watching / Up next, Recently added, Recently watched; both profiles; at most 60, one at a time with a 0.5 s pause),
reads each title body + ratings and pre-fetches the film page's poster (h=600), backdrop (h=1280) and top-8 cast photos
(h=400) into the `/img` disk cache. Everything it touches is cached, so a repeat pass is stats and short reads.
**Library pass** (media-warm-library): after the shelf pass, at most once per 24 h (stamp `warmup_library.stamp` in the meta cache dir, written only after a pass with no failures), the whole library — jellyfin snapshot movies + shows, both profiles, de-duplicated — gets what `/media/item/{jf_id}` renders: poster h=600, backdrop h=1280, top-8 cast photos h=400, plus ratings and the title body through the 6 h disk meta cache (so later passes cost stats). Sequential, 0.3 s pause after each upstream fetch; a cold pass takes ~20 min and logs one summary line (titles, fetched, cached, failures, seconds). `MEDIA_WARMUP=off` disables everything, `MEDIA_WARMUP=shelves` keeps only the shelf pass; without Jellyfin / Jellyseerr keys it skips. Cast portraits and posters are
`loading="lazy" decoding="async"`. Measure with `scripts/bench_item_page.py` (inside the hub container; its docstring has
the command); `scripts/profile_item_page.py` prints a cold open's call timeline against the test fakes.

Follow (2026-10-07): `media_follow.py`. **Films only.** Follow a person from their page (header "Follow" / "Following ✓ ·
Unfollow") or a film series from the film page's collection shelf ("Follow series"); following is instant and reversible
(`POST /media/follow/{person|collection}/{tmdb}` and `…/unfollow`, behind `same_origin`, redirect back with a flash word).
New and future films only — a film released before the follow date is never added. A person's film qualifies when they are
top-5 billed (cast `order` 0–4, read from the film's own Jellyseerr credits) or its Director; a series' film always does.
Qualifying films not yet in Jellyseerr are requested through the Discover Request call (max 10 a run, the rest next run),
recorded in media.db `media_follow_adds` (never requested twice by a follow) and announced on Discord ("Joey Media: added
<Title> (<year>) — <reason> · following <Name>"; `MEDIA_DISCORD_WEBHOOK`, else `SERVER_DISCORD_WEBHOOK`). The check runs
right after a Follow and every 6 h (first ~2 min after start; `MEDIA_FOLLOW=off` disables the loop). Discover has a
**Following** tab (`/media/following`: each follow, then the last 20 adds) and Media home gains "New from people you
follow" once anything is followed. Person pages show the first 24 titles of each grid and fold the rest under "Show more".

Rating level (2026-10-06): each owner chooses Show / Season / Episode with the chips on To rate
(`POST /media/settings/rating_level`, stored per owner in `media.db` `setting`). The To rate inbox, the rate
picker and the score shown on rows follow it; a row lacking that level's key falls back to its show, and
rankings count show + season ratings only.

To rate on Movies / TV Shows (media-ux2, 2026-10-08): `/media/movies` and `/media/tv` open with a "To rate · N" section —
the same inbox (`_to_rate`, viewer's own history and ratings) filtered to the page's kind, rendered by the shared
`templates/_to_rate.html` rows Diary > To rate uses. It is absent when nothing waits. Each row's picker carries
`back` (the page path); `POST /media/rate` returns a plain form there (fixed list `RATE_BACK`: history, movies, tv;
anything else → `/media/history`); htmx swaps in the usual "Rated N · Undo" row in place.
**Superseded by media-ux4 (2026-10-08):** To rate is a **tab** beside Tonight — My films · Watchlist · Tonight · To rate
(and My shows · … · To rate) at `/media/movies/to-rate` and `/media/tv/to-rate` (`main._to_rate_page`,
`templates/media_to_rate.html`): the same rows for the page's kind with a "N films watched in the last 30 days, not
rated yet" line, "Nothing to rate." when empty. The tab always shows; its amber count (`main.to_rate_tab_counts`, the
viewer's inbox split by kind; screen-reader word "to rate") only when > 0. The list pages no longer hold the section.
`RATE_BACK` adds both tab paths (the list paths stay for forms already open). Label case (awards-year, 2026-10-09, B.):
the tab reads **"To Rate"** on Movies, TV Shows and Diary (and the tab page's `<title>`); body copy ("Nothing to rate.",
the Diary section label, the count's screen-reader words) stays sentence case.

Browse by service (media-ux2, 2026-10-08): `/media/discover` gains a **Services** row (above the shelves, hidden while
searching) — logo tiles for `media_discover.SERVICES` (Netflix, Disney Plus, Amazon Prime Video, Stan, Binge, Apple TV
Plus, Paramount Plus, HBO Max, Foxtel Now, SBS On Demand, ABC iview, 9Now, 7plus, in that order), matched by name against
Jellyseerr's AU watch-provider lists (`norm_provider`: case, spacing and "+"/"Plus" don't matter; a miss is skipped and
logged once per list read). Logos come through the `/img` proxy (`tmdb:` logoPath), the name always under the logo. Each
tile opens `/media/discover/service/{provider_id}` (Discover section, Discover tab lit): Popular films · Popular TV · New
this month (released in the last 30 days, films and TV interleaved) · Top rated (vote_average.desc, ≥ 200 votes), each a
carousel of the Discover poster cards (title page, +, status word). Provider list cached 24 h, shelves 6 h; a failed
shelf says "Unavailable", an empty one "Nothing to show right now"; an id not in the AU list 404s.

Watchlist (F6, 2026-10-06): `media_watchlist.py` + `media_watchlist_db.py`. A "Watchlist" tab under Movies and TV Shows
(`/media/movies/watchlist`, `/media/tv/watchlist`); add from a title page (the bookmark icon button) or the small "+" beside a Discover
result. Each row carries a status word: On disk, Requested, Processing, Partly available or Not on server. A title the owner has
watched leaves the list by itself when the page renders.

Play recorder + History (F7, 2026-10-06): `media_plays.py` / `media_plays_db.py` record every watch (see
`docs/connector-contract.md`, seventh exception). Server tabs are Live · History · Library · Downloads · Requests · Health;
History shows plays, hours, top ten, busiest day and plays by hour over 7 / 30 / 90 days, this year or all time. Home gains a
"Most played · 30 days" shelf (`build_shelves` in `main.py`).

Diary per episode (F8, 2026-10-06): jellyfin-synced diary rows are one per episode; `media_db.group_diary` folds a day's
episodes of one show season into a single line ("S2 E3-5"), and a rewatch mark shows when the title was logged on an
earlier day. The "where" filter is not built. Older show-level rows still render.

Poster sizes (updated media-ux4, 2026-10-08): list rows use `.row-poster` (44 px wide, fetched h=120); the Movies / TV
Shows lists, every To rate list (Diary > To rate, the Movies / TV To rate tabs) and every Diary list use the bigger
`.listbox.libposters` size (55 px on a phone, 66 px from 640 px, fetched h=240; a picker under such a row is indented
to the title); poster cards are 116 px wide on a phone and 144 px from 640 px (`.carousel > *`), fetched h=240. History's
Recently watched keeps the 44 px rows. All in `static/control-surface.css`.

Back / Forward (2026-10-08): history navigation always shows fresh server state. `base.html` sets
`<meta name="htmx-config" content='{"historyCacheSize":0,"refreshOnHistoryMiss":true}'>` (htmx 2.0.4 names: no
localStorage page snapshots, a Back is a full reload), the `no_store_pages` middleware in `main.py` sends
`Cache-Control: no-store` on every `text/html` response (not `/static/`, not `/img`), and a small script strips the flash
params (`main.FLASH_PARAMS`: follow, requested, error, flash, c, code, done) from the address bar after render with
`history.replaceState`, so a "Following" / "Requested" / "Removed" line is shown once. GET routes never toggle anything; the
only GET-side writes are idempotent syncs (the diary page's Jellyfin history sync, the watchlist's prune of watched titles,
the local-only `?owner_view=` cookie) and caches (meta, `/img`).
Actions add no history entries (media-ux2, 2026-10-08): a boosted POST (Mark watched, Remove, Follow, a rating, the
watchlist …) 303s back to a page, which htmx would push as a new entry. A `htmx:beforeHistoryUpdate` hook in `base.html`
turns that push into a replace for every non-GET request (`detail.requestConfig.verb`), so one Back goes to the page you
were on before; GET boosts (links, search) still push.

Remove a request (2026-10-08): `media_requests.py`. Each Requests row (still a whole link to Jellyseerr, via an
`a.rowlink` overlay) has a right-aligned **Remove** button opening an inline confirm (`details.confirm-wrap`, no browser
dialog). `POST /media/requests/{id}/remove` (behind `same_origin`) deletes the Jellyseerr request, then — only when nothing
is on disk — sets the Radarr movie / Sonarr series `monitored: false` (never a file or entry delete; see
`docs/connector-contract.md`, thirteenth exception). The row leaves the page at once (`media_hidden.py`: hidden until a
snapshot newer than the removal + 90 s; the film page's "Requested" line and the watchlist status read the same visible
rows) and the page flashes "Removed" (`?done=removed|stopped|ondisk|arrfail|arrunset&app=…`; errors `?error=…`, words only).

Search now (media-ux5, 2026-10-09): `media_arr_search.py` + `_arr_search.html`. The film / series page (library item or
Discover title — one template; not on an episode page, where it would search the whole series) holds a hidden
`span#arr-search` that htmx swaps on load for `GET /media/title/{kind}/{tmdb}/arr?back=<page>[&tvdb=]`: a `.btn-glass`
"Search now" form when the title is in Radarr (film) / Sonarr (series), else nothing (the Request flow applies). The page
render makes no *arr call. Any viewer may press it. `POST /media/title/{kind}/{tmdb}/search` (`same_origin`) sends
`MoviesSearch` / `SeriesSearch` (`POST /api/v3/command`) and 303s back with `?search=started|unmonitored|missing|unset|
unreachable|refused&app=radarr|sonarr[&code=]` — flashed under the hero status line ("Search started in Radarr"; an
unmonitored title is still sent and the line says it may find nothing, because the apps search monitored items only).
Contract: seventeenth exception.

All seasons + future (media-ux5, 2026-10-09): the TV Request confirm step (`_request_block.html`) opens with a ticked
**All seasons + future** checkbox (`name="seasons" value="all"`) above the season ticks (dimmed via `:has()` while it is
ticked; it wins over them). Ticked, `media_discover._send` posts Jellyseerr `"seasons": "all"` (seerr-api.yml POST
/request: `number[] | "all"`), then `media_arr_search.follow_all` reads the series from Sonarr (full list by `tmdbId`; up
to 3 reads 2 s apart, because Jellyseerr hands it over a few seconds later), PUTs it back with `monitored: true,
monitorNewItems: "all"` (other fields kept) and sends SeriesSearch. The done line gains one note
(`?future=set|searchfail|notyet|unset|failed` without JS): emerald when Sonarr now follows new seasons, amber when it was
skipped (not added yet / not connected / refused). Unticked, the ticked seasons are requested exactly as before and
Sonarr is not touched. Worst case the request waits ~4 s on the retries.

Move on from Continue watching (2026-10-08): `media_resume.py`. **Mark watched** and **Reset progress** (the latter only on
a resume row, not a "Next episode" suggestion) on the Media home Continue watching cards (the hub page's band is gone since media-ux2) (folded under a "Move on"
button below the card, outside its link: `_resume_acts.html`, `.card-wrap`), beside each Server → Playing "Up next" row
(`.rowwrap`, the row stays one whole link) and beside "Resume ▶" on a film / episode page (B.'s views only — the page's
watch state is read as `JELLYFIN_USER`). Acts as the viewer's Jellyfin user (you / her; a signed-in viewer is always
themselves); see `docs/connector-contract.md`, fourteenth exception. On success the item leaves every resume list at once
(`main.get_snapshots` applies `media_hidden`), the item-page cache is cleared, and the page it returned to flashes
"Marked watched" / "Progress reset" (`?done=…`, rendered by `base.html`). A watched mark lands in the diary at the next
jellyfin sweep, dated the day it was marked. Reset progress on an episode may bring it back as "Next episode" after the
next sweep (Jellyfin's Next Up).
**Hide** (media-ux2, 2026-10-08): a "Next episode" suggestion also offers Hide (Move on panel and beside Mark watched on
Up next). `POST /media/resume/{id}/hide` (same_origin, form `series` + `owner` + `back`) writes media.db `nextup_hidden`
(owner, series key, suggested episode id) — no Jellyfin call — and `apply_hidden` drops that suggestion for that owner
everywhere until Next Up suggests a different episode of the series (or the episode turns into a resume row). Flash
"Hidden". The table rides the normal whole-DB backup.

Episode list (2026-10-08, replaced the numbered squares and their legend): on an on-server show's page each season is a
`<details class="seasonbox epseason">` headed "Season 4 · 3 of 6 watched", open for the page's episode's season, else the
next episode's, else the latest (`media_film.episode_list`). Each episode is one whole-row link (`.row.has-form.epline` +
`a.rowlink` to `/media/item/{id}`, at least 64 px): its 16:9 still (`/img/jf:<episode id>?h=240`), "E3 · Name", air date ·
runtime, and its state in words + colour (`episode_state`: Watched · In progress · 23m left · Not aired · Not watched; an
in-progress row gets the Watching tint). The Play / Resume / Play again deep link sits beside the row, outside the link
(aired episodes only). At ≤ 480 px the still shrinks to 96 px and the button drops under the text. The episode facts ride on
the existing per-season read (`media_item._seasons`: PremiereDate, RunTimeTicks, UserData).

Watched / unwatched (media-ux3, 2026-10-08): `media_resume.py` serves three more places, no confirm step. A season's open
list starts with **Mark season watched** (until every aired episode is watched, then **Mark season unwatched**:
`.seasonacts`); each aired episode row carries **Mark watched / Mark unwatched** beside Play in `.row-side`, outside the
row link; the film and episode pages carry the same toggle in the hero buttons (not while in progress — the Move-on pair
covers that). B.'s views only, like the Move-on buttons (the pages read watch state as `JELLYFIN_USER`). Routes:
`POST /media/resume/{id}/watched` (a season sends its season id with `scope=season` + `show` — Jellyfin marks every
episode) and `POST /media/resume/{id}/unwatched` → `DELETE /UserPlayedItems/{id}?userId=` (legacy `DELETE
/Users/{uid}/PlayedItems/{id}` on 404/405), both same_origin, acting as the viewer's Jellyfin user. On success the
item-page cache is cleared so the 303 re-reads Jellyfin, and the form's `season=N` rides along so the list reopens that
season; flashes "Marked watched" / "Marked unwatched" / "Season marked watched" / "Season marked unwatched". Continue
watching: a watched mark hides the item (a season: every episode in it) until the next sweep; a season marked unwatched
hides its in-progress episodes (their positions are reset); a single item marked unwatched hides nothing. **Diary:** a
watched mark (a season: one row per episode, folded to "S4 E1-6") reaches the diary at the next jellyfin sweep as today's
watch; marking unwatched never deletes a diary entry — remove it from the Diary by hand if it was a mistake.

One rating style (media-ux4, 2026-10-08): the numbers strip's scores are `.scorepill`s in one `.stat.wide` ("SCORES"): a
small monogram logo (`hub/static/logos/<id>.svg`, self-made marks — `hub/static/badges/logo-<id>.svg|png` overrides
one), the source's name, then the score in one format — IMDb `8.0` · RT `90%` · Metacritic `74` · TMDB `8.1` (Jellyfin's
community rating, else the Jellyseerr vote; `media_film.score_text`) · Yours `8` (grade colour, gold at 10, Undo beside
it; unrated: "Rate", a link to the picker). Metacritic alone is tinted by its band (`mc_band`: good ≥ 61, mid 40–60,
bad < 40; tokens `--good` / `--score-6` / `--bad`), the number always shown. Runtime and the certificate stay plain
stats. The hero's IMDb / TMDB / Letterboxd links are the same pill without a score (`.sitepill`), neutral — the
yellow / sky / green link chips and their tokens are gone. A pill with no source is not drawn.

Directed by / Created by (media-ux4, 2026-10-08): the hero's inline "Director …" text is a block of headshot cards
(`.makers` > `.makerrow` > `a.makercard`): a 52 px round photo (the TMDB profile through `/img`, `MAKER_H` = 240; Jellyfin's
person image when Jellyseerr has none; initials when neither) and the name at 16 px, each card ONE glass link to
`/media/person/{id}` (a Discover search without a TMDB id). Films say "Directed by", shows "Created by", up to four cards
(`MAKERS_MAX`). Phone: one sideways row, centred while it fits; from 640 px they wrap. The site pills follow on their own
line; the Crew section below still lists every role.

Trailer player (media-ux4, 2026-10-08): the hero's Trailer button (now a word button, `btn-glass` + film icon) links
to the trailer and, when it is a YouTube video (`media_film.youtube_key` / `_trailer`: Jellyfin RemoteTrailers, then
Jellyseerr `relatedVideos`, first with an 11-character key), carries `data-yt`; a click opens `<dialog id="trailer">` and
the inline script creates the `youtube-nocookie.com/embed/{key}?autoplay=1&rel=0` iframe only then; Close / Esc / the
backdrop closes it and removes the iframe. No JS: the plain link. Recorded privacy exception in the contract doc.

Metacritic (media-ux4, 2026-10-08): `media_omdb.metascore(imdb_id)` fills the Metacritic pill from OMDb when
`OMDB_API_KEY` is set (contract doc, fifteenth exception): one lookup by IMDb id, every answer remembered 7 days in memory
+ on disk (`omdb:<id>` in the meta cache), ≤ 800 calls per process per day, a refused key stops calls for the day; no key,
"N/A" or a failure ⇒ no pill. Logs never carry the URL (it holds the key) — status or exception type only.

Awards (2026-10-08, AWARDS_PLAN): Movies and TV Shows gain an **Awards** tab after To rate (`/media/movies/awards`,
`/media/tv/awards`, `?body=&year=&unseen=1`; `media_awards_pages.py`, `media_awards.html` + `_award_card.html`). Ceremonies:
Oscars, Golden Globes, BAFTA, Critics' Choice, SAG, DGA, PGA, WGA, Cannes on Movies; Globes, Critics' Choice, SAG, Emmys on TV
(film or TV categories each). Year = ceremony year (2025 = the 97th Oscars, "films of 2024"). Page: an "Updated 3 Oct · 388 of
402 ceremonies" line (amber "Sync failed · retrying" only when the last pass landed nothing), Coming up (the next four months
with a ceremony; a known date in teal), the ceremony chips, the year stepper + Not seen chip, the hero category (winner
poster, "Won · 3 of 7 nominations", nominees carousel) and every category as a card in curated rank order
(`media_awards_seed.py`; shorts / documentary / technical fold under "More categories"). Seen ✓ = the viewer's own Jellyfin
played flag or any diary row for the title; a work matches the library by TMDB id (shows also by TheTVDB), never by title.
The film / TV page gains an Awards section under the stats strip ("BAFTA 2025 · Won 3 of 7 nominations" + categories, each
line linking to that ceremony) and the person page one ("2 wins · 5 nominations" + "Oscars 2025 · Best Actor" / "Won · The
Brutalist"); both are absent when there is nothing. Data: `media_awards.py` syncs into the media.db `award_*` tables
(`media_awards_db.py`; contract doc, sixteenth exception) — the Oscars from Wikidata per edition, Globes / BAFTA / Critics'
Choice / SAG / Emmys from the Wikipedia ceremony page (`media_awards_parse.parse_award_blocks`: the `{{Award category}}`
shape every page since the mid-2000s uses; older pages without it are `skipped`), Cannes and the guilds as winners only (v1).
`AWARDS_CONTACT` (required) and `MEDIA_AWARDS=off` are in `docs/setup.md`; `scripts/awards_sync.py --edition oscars:97`
runs one edition by hand. Backfill runs newest first, 40 editions a pass, every 6 h until done (~2½ days), then weekly.

Awards visual pass (awards-ui, 2026-10-09; supersedes the chips / plain-text look above). **Marks:** `_award_icons.html`
draws each ceremony as a simple self-drawn silhouette in currentColor (not the official logos): Oscars statuette, Golden
Globes globe, BAFTA mask, Critics' Choice star, SAG two figures, DGA clapper, PGA reel, WGA pen nib, Cannes palm frond, Emmys
winged figure, plus trophy / laurel / seen / person. `award_icon(name, size, label, src, deco)` is labelled (`role=img` +
`aria-label`) or `aria-hidden` when words sit beside it; `media_awards_icons.cat_icon` picks a category's mark (acting →
person, directing → clapper, writing → nib, picture / series → reel, else trophy). A file `hub/static/awards/<id>.svg|png|webp`
replaces a ceremony's drawing everywhere (checked once per process). **Page:** ceremony tiles (mark + name; the picked one
gold-outlined, the row scrolls sideways inside its own box below 1024 px), Coming up with a mark per ceremony and the next
one underlined + "Next", the stepper `‹ [year select] ›` (native `<select>` of every known year, 18 px, submits on change;
a Go button without JS) + edition line + Not seen, then the **Most wins podium**, the hero (the winner's backdrop — library
row, else the Jellyseerr meta cache, else a faint gold glow — a gold-framed poster, gold trophy pill, "Won 5 of 6
nominations" in gold, the Nominated row) and the category cards (mark + name; the winner gold-framed beside the gold word
"Won"; nominees with a faint neutral outline). Gold means won (`--gold`, `--gold-soft`, `--gold-line`); the podium adds
`--silver` / `--bronze`. **Podium:** the edition's top 3 works by categories won (ties: more nominations, then title), set out
2nd · 1st · 3rd (the `<ol>` stays 1-2-3), three across on every width; hidden unless two works won something and the top one
won 2+ (winners-only ceremonies — Cannes, the guilds — would show three 1-win ties). **Poster winner badges**
(`media_awards_badges.py`): a round badge at a poster's bottom right with the mark of the most prestigious win (Oscars >
Cannes > BAFTA > Globes > Emmys > Critics' Choice > SAG > DGA / PGA / WGA) and "+N" more ceremonies, labelled "Won Best
Picture · Oscars 2025", and a gold frame on the poster — wins only, a nomination shows nothing. On the Movies / TV grid,
Discover (shelves, search, service pages), the film page's collection + Similar / Recommended rows and the Awards pages.
`media_awards_db.win_rows` answers every poster on a page in ONE statement (ids as JSON arrays through `json_each`), cached
60 s per key set: a 200-poster grid measured the same with and without badges (151 vs 153 ms, noise; the query alone 5 ms
cold, 0.2 ms cached). **Film / TV and person sections:** grouped per ceremony (prestige order) under its mark + tally; film
lines "2025 · Won 2 of 3 nominations" (older editions fold after 3) over category pills — won gold with the laurel, nominated
neutral, each saying Won / Nominated to a screen reader; person rows "2025 · Best Actor" over a Won / Nominated pill + the work.

Awards year kept (awards-year, 2026-10-09): each ceremony tile links `?body=X&year=<the year on screen>` (+ `unseen=1`), so
switching ceremony keeps the year instead of jumping to the latest. A year the target ceremony has no edition for lands on
its closest earlier year, else its closest later one (`media_awards_pages.nearest_year`, over `years_of`), under a muted
note "No Emmys in 1946 · showing 1949"; a bad `body` still means plain defaults. A "Current year" chip beside the stepper
links to the ceremony's latest synced year (the no-year URL) and is hidden when already there. Each tile also carries a
small muted month line under its name ("Mar", "Feb", "Jan"): the selected year's edition date (`media_awards_db.held_months`,
one query), else the body's `usual_month` (the constant Coming up falls back to); tile order unchanged.

Episode pages (media-ux4, 2026-10-08): the hero has no "Episode of <Show>" line (the part-of banner leads to the show) and
only the **episode's** Play button — the series-level "Next to watch: …" / "Play ▶" stays on the series page. The hero's
watch state (toggle, Move-on pair, Play label) comes from the show's season list the banner counts and the rows show
(`media_film.listed_episode`: by id, else by season + episode number for a duplicate Jellyfin item, whose listed id the
toggle then acts on); before, the hero read the episode's own item — a separate 10-minute cache entry — and could say
"Mark watched" beside "10 of 10 watched".

"Part of" banners (media-ux3, 2026-10-08): `.partof` is a wide card with a backdrop under the guide's page-header scrim
(`--pagehead-side-*` left to right + `--pagehead-foot-*` from the foot; on a phone the stacked `--pagehead-fade-*`), the
poster, one " · " line and glass buttons; no backdrop → a plain panel; ≤ 640 px it stacks and its buttons go full width.
An **episode page** shows its show directly under the hero ("Slow Horses · Season 6 · Episode 4 · 3 of 6 watched", the
show's backdrop only when Jellyfin has one — `media_item` `has_backdrop` from `BackdropImageTags`) with **This season**
(`/media/item/{show}?season=N#season-N`) and **All seasons** (`#seasons`); a **season page** links to All seasons only and
opens its own season. The series page reads `?season=N` (junk ignored) to open that season; every season `<details>`
carries `id="season-N"` and the Seasons section `id="seasons"`. A **film page** (item and Discover title URLs alike)
shows its collection directly under Overview (`media_film.collection_banner`): the collection backdrop (Jellyseerr
`backdropPath`), else the first part's, else a plain panel; "The Dark Knight Collection · 3 films · 2 on server"; the
Follow series form inside; then the parts in release order (undated last) as `.card-poster`s with On server / Not on
server words, the page's own film outlined with "This film" (`.is-current`, `aria-current`). Similar / Recommended stay
as the bottom shelves.

Empty shows (2026-10-10): the Jellyfin feed leaves out a Series whose `RecursiveItemCount` is 0 — the empty folder Sonarr
makes for an unaired show (Harry Potter, VisionQuest) — so it is not on the TV page or any other show list until an
episode lands; a missing count is kept. `media_library` no longer calls a 0-episode show "finished" / "All watched".

TV directors (2026-10-10): TMDB's show-level crew has no directors (they are credited per episode), so a show page's
Crew never had a Director row. `media_film.crew_for` now takes the Director and Writer rows for TV from Jellyfin's People
— the episode's on an episode page, the series' on a show page — and falls back to TMDB crew; films are unchanged.
Same day, follow-up: Jellyfin keeps directors on episodes, not the series, so a show page's rows now add up the
People of every episode on the server (`/Shows/{id}/Episodes` reads `People`; `media_film.show_crew`, most episodes
first) when the series has none of its own; and the item's 30-person cap no longer cuts a Director / Writer listed
after many guest stars.

## 2026-10-11 — show pages get "Directed by" cards
A show page now shows a second hero card row, "Directed by", below "Created by": the same headshot cards a film
has, with the directors of the most episodes on the server first (`media_film.show_directors`, the series' own
Director People outrank the count), capped at `MAKERS_MAX`. Episode crew entries carry the Jellyfin headshot ref
(`jf:<person id>`) when the person has an image; without a TMDB person id the card links to a Discover search, as a
film's maker card does. Episode pages and films are unchanged (`tests/hub/test_media_tv_crew.py`).

## 2026-10-12 — F1 keep scroll on the same-page controls
htmx boosts every link and GET form and, by default, scrolls a boosted swap to the top, so changing the awards
ceremony or year, or sorting Movies / TV, threw the reader back to the top of a long page. The controls that re-render the
SAME page now carry `hx-swap="innerHTML show:none"` (htmx 2.0.4 parses any `show:` value after its boosted `show:top`
default and only scrolls for `top` / `bottom`): the awards ceremony tiles and the whole stepper row (prev / next, year
select, Current year, Not seen) in `media_awards.html`, and the Movies / TV `.toolbar` form (search, Grouped, sort,
Grid / List) in `_library_page.html`. The year select now calls `this.form.requestSubmit()` instead of
`this.form.submit()`: the native `submit()` skips the submit event, so htmx never saw it and the page fully reloaded.
Section tabs, the phone bar and posters are unchanged (still land at the top), as is Back / Forward
(`historyCacheSize` 0). Tests: `tests/hub/test_keep_scroll.py`.

## 2026-10-12 — Search all monitored (F3)
B. asked for a button to search everything monitored in Radarr and Sonarr himself. Activity › Requests and › Downloads
now open with a shared action row (`_arr_sweep.html`): **Search missing** and **Search upgrades**, sub-line naming the
connected apps ("Radarr · Sonarr"). Each opens an inline confirm card in place (htmx `GET /media/arr/sweep?step=confirm
&kind=…&back=…`, the Update now / Request two-step; no browser dialog; no-JS fallback `?sweep_ask=`), then a
`same_origin` `POST /media/arr/sweep` sends `POST /api/v3/command` to both apps in parallel worker threads, 10 s timeout
each: missing → Radarr `MissingMoviesSearch` + Sonarr `MissingEpisodeSearch`; upgrades → Radarr
`CutoffUnmetMoviesSearch` + Sonarr `CutoffUnmetEpisodeSearch`. It 303s back with `?sweep=started&ran=radarr,sonarr`
("Search started · Radarr · Sonarr"), `partial` ("Search started · Sonarr only") or `failed` ("Couldn't start the
search"); logs carry the HTTP status or exception type only. Repeating a kind inside 10 min is allowed but the card says
"Started N min ago · run again?" (in-process, reset by a restart). With neither app configured the row reads "Not
connected" and has no buttons. `_command` gained an optional `body` / `timeout` for this; Search now is unchanged
(`tests/hub/test_media_arr_sweep.py`).

## 2026-10-12 — F2 fast item pages: the page first, the upstream sections after
B.: "The phone and sometimes computer still take seconds in between loading pages … at least load the page and have
the photos come after." A film / show page (`/media/item/{jf_id}`, `/media/title/{kind}/{tmdb}`) used to wait for the
Jellyseerr bundle (body, ratings, similar, recommendations, collection) and OMDb before its first byte — 0.8–1.4 s on
the NAS on a first open. It now renders from Jellyfin + whatever is cached and never waits on Jellyseerr or OMDb; the
sections still waiting are placeholders (`film.pending`) and ONE htmx request (`.../part/all?p=…`, out-of-band swaps)
fills them: the hero's makers and Request block, the IMDb / RT / Metacritic pills, the film series, Crew, the Details
release dates / Seasons row, Cast, Where to watch and the shelves. Placeholders hold the Jellyfin fallback (directors,
crew, cast with headshots) or one "Loading" word. The upstream read starts in the background the moment the TMDB id is
known (one bounded job per title, `media_film.warm_extras`), so the part request usually finds it done; a title whose
answers are all cached renders whole, as before. An off-server title still waits for its one title body (it is the
page); a request step (`?step=confirm`, `?requested=1`) reads it too, so the Request block draws its state. The tagline
is drawn only when the body is cached (no jump in the hero). The part routes never read Jellyfin again
(`media_item.peek`); `media_item.once` makes concurrent reads of one item / Jellyseerr path share a call. Links to
film / show pages prefetch on touch or a 60 ms hover (`static/joey.js`, `X-Joey-Prefetch: 1`, once per link, one at a
time): the route runs the reads and answers an empty 204. The Awards page no longer reads hero posters before render
(M-46): they, the rest of the edition's posters and a missing hero backdrop fill in its BackgroundTask. Measured on the
test fakes with Jellyfin 100 ms / Jellyseerr + OMDb 300 ms a call: a film page's first byte 0.95 s → 0.25 s (no
Jellyseerr / OMDb call waited for). `tests/hub/test_media_fast_pages.py`; tests that read a deferred section fetch the
parts through `tests/hub/film_page.whole()`.

## 2026-10-12 — Server: manual Update now for notify-only containers
**Server → manual Update now (2026-10-12).** `server_updates.py`. Notify-only containers (gluetun, qbittorrent, prowlarr,
uptime-kuma) keep the "Manual · excluded" chip but now also get Update now: the confirm page says it is a manual update
and the POST calls WUD's `dockercompose.manual` trigger (`WUD_TRIGGER_DOCKERCOMPOSE_MANUAL_AUTO=false` on the NAS, so
it never fires on its own). Warnings on the confirm page: qbittorrent/prowlarr route through gluetun (brief network
drop); gluetun may leave them needing a restart; a leading-number tag jump is flagged "Major version jump". The `wud`
row reads "Update WUD by hand" and is always refused (409, no call). `auto` rows still use `dockercompose.local`.

## 2026-10-12 — Upgrade available (F4b)
B.: "show me if an upgrade is available, such as a small light-blue text underneath the movie saying 'Upgrade
available', and allow me to decide if I want to download that upgrade." The hub side of F4a's `arr` `data.upgrades`.
`hub/media_upgrades.py` (pure): `index(snaps)` keys both lists by `item_key`, `note(row)` = "Upgrade available ·
WEBDL-720p → Bluray-1080p" / "Upgrade available · 3 episodes · SDTV → WEB 1080p" (no arrow part without `want`; "to
<want>" without `have`), `find` / `attach` match a film on `tmdb:` only (TMDB movie and TV ids are separate spaces) and
a show on its `tvdb:` key, a known TheTVDB id (Jellyfin ProviderIds.Tvdb cached by the show page via
`media_item.peek`, or a request's `tvdb_id`), else the normalised title when exactly one Sonarr row and one library
show carry it. The line (`.upnote`, appended; one token `--upgrade: var(--sky)` in the single `:root` — colour for
meaning, the words say it too) renders under Movies / TV cards and rows, Requests rows and the film / show hero's status line (core, from the
snapshot: no call, F2's order kept; not on an episode page). Activity › Downloads gains an "Upgrades" block (poster,
title, note; "3 films · 2 shows" from `totals`; "Sonarr not connected" for one null list; "Not connected" for both;
absent for an older envelope). "Search for upgrade" sits in the lazy Search-now fragment when the app's own id (from its
lookup) is on the list — an inline `<details>` confirm, then the `same_origin` `POST /media/title/{kind}/{tmdb}/upgrade`
looks the title up and sends `{"name": "MoviesSearch", "movieIds": [id]}` / `{"name": "SeriesSearch", "seriesId": id}`
in a worker thread, 303 back with `?upgrade=started|failed` ("Upgrade search started" / "Couldn't start the search");
logs carry the HTTP status or exception type only. Picking a specific release is a possible v2
(`tests/hub/test_media_upgrades.py`, `test_media_upgrades_pages.py`, `test_media_upgrades_film.py`).

## 2026-10-12 — F5 follow shows + show creators
B.: "TV directors should have a way for me to follow them too — or at least the show, so I can auto-request future
seasons once announced." **Follow show:** a show page (not an episode) has one line under the hero's makers rows
(`_follow_show.html`): "Follow show", or "Following ✓ · future seasons" + Unfollow. Following sets the show in Sonarr to
`monitored: true, monitorNewItems: "all"` (its own resource PUT back, nothing else changed, no search); a show Sonarr
doesn't have is requested "All seasons + future" first (Jellyseerr `seasons: "all"`, then `media_arr_search.follow_all`).
The follow is kept either way and the flash says what Sonarr did. Unfollow sets `monitorNewItems: "none"` — monitored,
seasons and files stay; nothing is deleted. The 6-hourly check repeats the PUT for a followed show Sonarr added later or
that was changed by hand (one series-list read a run). The line reads media.db only: no upstream call on render (F2).
**Show creators "like movies":** under a show's "Created by" cards, a small "Follow <name>" button per creator with a
TMDB id (the card stays the person link); on the person page, Follow for someone with TV Creator / Director credits
carries `tv=1`. Either follows them as a TV maker (dept `creator`, "Creator · films + shows"): their new films by the
existing rules plus their new SHOWS — TV crew Creator or Director, or Executive Producer when they are a Creator
somewhere; a known first air date after today; requested with `seasons: "all"`, once per follow, capped with the films,
Discord "added show …". Actors and directors followed before keep films only. **Following** has a "Shows · future
seasons" group (poster, name, Unfollow) and a TV maker's count reads "1 film · 3 shows". media.db `user_version` 3:
`media_follows.kind` takes `show`; `media_follow_adds` is keyed on (follow, media, TMDB id) so a film and a show sharing
a number never collide (tables rebuilt, rows kept). `tests/hub/test_media_follow_shows.py`.

## 2026-10-12 — Jellyseerr shows as "Seerr"
The app was renamed upstream (the NAS now runs `ghcr.io/seerr-team/seerr`), so every user-visible string says **Seerr**:
the film page's "Open in Seerr" link, the Requests / Discover / Follow / person-page error and flash texts ("Seerr
declined the request", "Couldn't reach Seerr", "Follow needs Seerr", "In Seerr", …) and the Server status light /
Services card name (`media_status` catalogue). Env vars (`JELLYSEERR_*`), connector and snapshot ids, tables, modules and
URLs keep the old name. A Services card now also takes its Uptime Kuma ms from a monitor named like the app's **id**,
so a Kuma monitor still called "Jellyseerr" keeps feeding the Seerr card.

## 2026-10-12 — Server: Joey's own containers update on deploy
**Server → Updates, `joey-*` rows (2026-10-12).** WUD's compose triggers only manage
`/volume1/media-server/docker-compose.yml`, so a pending row for one of Joey's own containers (joey-cloudflared,
joey-macromates, any `joey-` name) has no Update now: it reads "Updates on next Joey deploy" (Ignore stays), and
`POST /server/updates/{name}/run` refuses it (409, no WUD call). One rule in `hub/server.py` (`WUD_SELF`, `JOEY_PREFIX`,
`update_hold`, `HOLD_TEXT`); `split_updates` gives every shown row `hold` / `hold_text`, which the band and
`server_updates.refusal` both read (the `wud` row's "Update WUD by hand" moved onto the same rule).

## 2026-10-12 — Server: Update all
**Server → Update all (2026-10-12).** An "Update all" button at the top of the Updates band whenever at least one
pending, non-ignored row may run (`updates.n_eligible`: no `hold`). `GET /server/updates/all/run?step=confirm`
(`server_update_all.html`) lists every row that will run — current → new tag, the WUD trigger
(`dockercompose.local` / `dockercompose.manual`) and that row's warnings — then "Not included" with the reason (wud:
"Update WUD by hand.", joey-*: "Updates on next Joey deploy.", ignored rows: "Ignored."). The `same_origin` POST
re-reads the snapshot (`server_updates.plan_all`) and calls each row's trigger in turn through `run_trigger` /
`trigger_name` / `record_run`, gluetun first when pending (qBittorrent and Prowlarr then come back up inside the new
VPN namespace), and redirects with "N requested · M refused" (flash params `n` / `m` / `u`, stripped from the address
bar like the others). Decision: a WUD that doesn't answer ends the run (" · WUD unreachable"; the rows not tried count
as refused) rather than timing out 10 s per remaining row. The "all" routes are declared before the per-row ones, so
a container literally named `all` could not be updated singly (none exists).

## 2026-10-12 — Server: Restart + update media stack (stackctl)
**Server → Restart + update media stack (2026-10-12).** WUD can't pull and restart the whole media-server compose, so a
new top-level `stackctl/` holds a tiny stdlib-only helper (`stackctl.py`, `python:3.12-alpine` + docker-cli +
compose, root for the Docker socket) that B. adds to `/volume1/media-server/docker-compose.yml` (`stackctl/NAS_INSTALL.md`):
`POST /media/pull-up` (202, or 409 while a job runs) lists the compose services, drops `EXCLUDE` (`wud stackctl`),
then `pull` + `up -d --no-deps`; `GET /status` gives running / times / exit code / last 50 log lines. Bearer token on
every endpoint (constant-time), no token = no start, the token is masked from output. Hub: `hub/server_stack.py` — a
"Restart + update media stack" button beside Update all (shown only with `STACKCTL_URL` + `STACKCTL_TOKEN`), a
"Media stack · …" line under the band head (Updating now · started 3m ago / Last run finished OK · 1h ago / Last run
failed (exit 1) · … / No run yet / stackctl unreachable / Not connected; `GET /status`, 2 s cap), a confirm page
(`server_stack.html`) listing exactly what happens, and the `same_origin` POST → flash (`?stack=started|busy|refused|
unreachable`). The flash line now sits under the band head, outside the WUD-connected branch, so stack flashes show
even with WUD down. Decision: stackctl mounts `/volume1/media-server` at the SAME path (not `/compose`) and defaults
`COMPOSE_FILE` to it, so compose's relative binds, `.env` and project name (`media-server`) match the host's — a
`/compose` mount would start a second project. `tests/stackctl/test_stackctl.py`, `tests/hub/test_server_stack.py`.

## 2026-10-12 — Server: Monitors band removed
B.: the Monitors band duplicated what the Services cards above it already show. `server.html` drops the band and
`build_server` no longer builds a `monitors` band; the `uptime_kuma` connector, its snapshot, the Monitors KPI tile and
the Attention lines ("Uptime Kuma: X is Down / Pending") are unchanged, and the cards still take their response ms from
the Kuma rows (`service_card`). The Monitors tile's `detail` now opens `/server#services`. What the band showed that
nothing else does: Uptime Kuma monitors that are not one of the Services apps (e.g. a "NAS" ping monitor) when they are
UP, with their ms, and the band's "N of M up" line (the tile still says it). Down / pending ones still reach Attention.

## 2026-10-13 — UI polish batch (WP E2; review_ui.md (c), P3c, P6)
Templates / CSS / `joey.js` only. **U1** every action form that re-renders its own page (Mark watched / Reset / Hide / season
toggle, watchlist ×, Follow / Unfollow, server Ignore / Unignore) carries `hx-swap="innerHTML show:none"` (the F1 pattern), so
the page keeps its scroll position. **U2** `body` has `hx-indicator="#loadbar"` and `base.html` a `#loadbar.htmx-indicator`:
a 2 px `--primary` bar (bottom edge above the phone tab bar, top from 768 px) that appears 150 ms into a request, static
under reduced motion; `a.htmx-request, button.htmx-request` dim to 60 %. **U6** the film page says runtime and certificate
once (the Numbers strip), Details values no longer repeat their label's verb, and the extra Rate star is gone (the
"Yours · Rate" pill stays). **U8** phone tap targets (rating chips 40 px, `.btn-mini` and section "All" ~40 px hit area,
`.seg` / `.sectabs` 36 px). **U10** weather under 1100 px: 7 days, then hours, then the Windy map; chart text 24 units
under 640 px (about 11 px rendered). **U11** carousels: 104 px phone cards (a 4th card peeks), `scroll-padding-inline: 16px`.
**U15** `--text-5` #82828b, tab labels / `.btn-mini` on `--text-4`, `.fmt small` 10 px (see the style guide's deviations).
**U16** every `div.seclabel` is `h2.seclabel` (VoiceOver headings rotor). **U17** a shelf count is left off when the shelf
is full (15 = `SHELF_MAX`, so it is a cap not a total); the hub's Recently watched gets an "All" link to `/media/diary`.
**U18 / U19** poster lifts only under `@media (hover: hover)`, none under reduced motion; `[id] { scroll-margin-top: 72px }`.
**U21 / U22** the hub glimpse's four stats stay one row; a tile value is `.stat-number` only when numeric, else `.stat-word`.
**U23** placeholder posters are zinc (`#18181b` card, `#52525b` letters, `system-ui`). **P3c** `joey.js` cancels the pending
film-page prefetch when a finger scrolls (`touchmove`) and fires it on `touchend` / after 60 ms held; hover is unchanged.
**P6** backdrops take a second inline size: `--bd` (h=1280) and `--bd-sm` (h=600), `--bd-pick` chooses under 768 px; not
for Jellyfin `jfb:` refs, which `/img` sizes at maxWidth 1280 whatever `h` says (so h=600 would be a second, cold cache key
for the same bytes). The awards hero `<img>` uses a `<picture>` source for the same switch. **Font preload** `base.html`
preloads `/static/fonts/GeistVF.woff2` (the exact URL the stylesheet's `url("fonts/GeistVF.woff2")` resolves to; it has no
`?v=`, so it is cached for an hour, not `immutable`). Tests: `tests/hub/test_polish_e2.py`.
## 2026-10-13 — E1: resilience + per-request costs
From the 2026-10-12 evaluation (§3 P2, P2b, P3/P3b, P3c server side, P4, P5, P10, P12) and the E2 follow-ups. The NAS's
internet link was dropping DNS replies and TCP handshakes under torrent load, so anything leaving the NAS took 7-12 s
or failed; Joey now degrades instead of waiting.
- **Discover never blocks** (`media_discover.py`). Shelf and provider-list reads wait `SHELF_TIMEOUT` = 3 s (title
  reads keep 8 s). Each shelf's last good rows are kept in memory and on disk (META_CACHE_DIR, key `shelf:<path>`); when
  a refresh fails they are served with their age in the shelf heading ("Trending · 12m ago"; the page also gets
  `stale_note`, "Shelves from 12m ago", for a future metaline). A failed read is remembered `FAIL_TTL` = 60 s, so the
  next loads do not wait again; with nothing stored the shelf says "Discover unavailable" at once. The provider list gets
  the same fallback (`meta_get(..., stale_on_fail=True)`); service pages share the shelf path. 10-min fresh TTL kept.
- **`/img` never stalls pages** (`images.py`). The route is `async`. A hit is read in a short worker call; a miss waits
  on the event loop (no thread held) for one of `MISS_SLOTS` = 6 slots of a per-loop anyio CapacityLimiter, then fetches
  + stores in a worker of its own limiter, re-checking the disk cache first. After `MISS_WAIT_S` = 8 s without a slot
  it gets the fallback card (`FALLBACK_CACHE`, 1 h). Measured on the laptop with 20 misses stuck upstream: a cached hit
  3.8 ms median / 26 ms max, never more than 6 upstream reads at once (`tests/hub/test_images_burst.py`).
- **Phone backdrops** (`images.py`, `media_warmup.py`). A `jfb:` backdrop's `maxWidth` follows `h`
  (`JF_BACKDROP_WIDTH`: 120->320, 240->480, 400->640, 600->800, 1280->1280; it was 1280 whatever `h` said); the allowed
  heights are unchanged. Both warm-up passes warm h=600 beside h=1280.
- **Jellyfin items stay warm** (`media_item.py`, `media_warmup.py`, `tasks.py`). The item cache serves an entry up to
  6 h old (`CACHE_TTL`) and re-reads it in the background once it is over 10 min old (`FRESH_S`; one 1-worker refresh
  pool, one refresh per item; a failed refresh keeps the entry). Joey's watch marks call `media_item.invalidate()`
  (drops the cache, and a read in flight across the mark is not cached); the resume write path reads the show fresh.
  Series pages read ONE `/Shows/{id}/Episodes` (grouped by each episode's SeasonId / SeasonName / ParentIndexNumber,
  Specials first, at most 12 seasons) instead of `/Seasons` + one read per season. The warm-up loop ticks every 60 s:
  the full pass still every 3 h, and each new jellyfin snapshot (`updated_at`) reads the Playing now / Continue watching
  / Recently added items (both profiles) that are not fresh — at most 20 per pass, 0.5 s apart.
- **Prefetches yield to taps** (`media_film.py`). An `X-Joey-Prefetch` request's background read runs in its own
  1-worker lane; at most one more prefetch waits there (later ones are skipped); a tap on a title whose prefetch has not
  started cancels it and reads in the 2-worker page lane (a running one is joined).
- **Server page** (`server_stack.py`, `store.py`). stackctl's `/status` answer is kept 30 s (an unreachable answer too;
  words unchanged, ages worked out per request; Restart + update drops it). `store.get_runner_history` keeps the parsed
  tail per (file, max_bytes) with the file's device, inode, size and mtime: unchanged -> the same list (so `/server`
  reuses the hub card's parse), grown -> only the new bytes are parsed, rotated / shrunk / rewritten -> read afresh;
  answers equal the old full re-read (randomised test). 2 MB tail: 10.5 ms -> 0.35 ms per call on the laptop.
- **media.db readers** (`media_store.py`). One kept reader connection per thread (`_Kept`: close() only rolls back),
  replaced when the file's identity changes, closed when its thread ends or on `media_store.reset()` (the tests'
  autouse fixture calls it); 1 MiB page cache each; writes keep `connect()`. A Media page opens at most one connection
  per thread. Laptop, warm, DB present: Media home 32 -> 6.5 ms, film page 57 -> 12 ms, show page 54 -> 12 ms.
- **Smaller waste.** `/media/library` builds its library index once per request (`media_library.library_index`). The
  Diary syncs Jellyfin history only when the jellyfin snapshot moved for that owner and file, and keeps its stats per
  (owner, file, snapshot, today, `diary_signature`). The lifespan pre-compiles every template and pre-parses the
  snapshots (`tasks.prewarm`). The Search now fragment's Radarr / Sonarr lookup is kept 5 min (`media_requests.
  find_kept`; failures not kept; every Joey write to an *arr app or a Seerr request drops it; write paths read live).
  `hub/upstream.py`: one keep-alive `requests.Session` per upstream (jellyfin, seerr, arr, omdb, tmdb; no cookies kept)
  for the Media modules and `/img` — the Server side (stackctl, WUD, Discord) keeps plain calls. `/static/fonts/*` is
  `immutable` without a `?v=` (the CSS names the fonts by a plain URL; a font only changes with the CSS hash).
- **Tests changed with the behaviour** (not weakened): the Discover failure test now pins "remembered 60 s" (was "not
  cached"); the Jellyseerr fake expects 3 s on shelf / provider reads; the season-read tests pin the one Episodes read
  (the Jellyfin fake's episodes name their season, as Jellyfin's do); the warm-up counts include the h=600 backdrop; one
  speed test drains the F2 background read before counting. `tests/hub/conftest.py` routes `upstream.session` back
  through the `requests` module so every fake still sees every call.

## 2026-10-13 — First screens (WP E3; EVALUATION_2026-10-12 §4.2 / §4.4, review_ui.md U3, U4, U9 a, U10, U12, U14, U17, U27)
B. approved the items on 2026-10-13. **Hub (U3)** the H1 is the greeting (`main.hub_greeting`: "Good evening, Benji", no
full stop; no name when not signed in), the sub-line the date ("Tue 13 Oct") plus feed problems only when there are any
("Feeds 8/10 live" while a feed is down, "<Area> stale" per stale feed; nothing when all are live). The calendar feed's
card and the Weather tile carry `.dup` and are hidden under 640 px (they repeat the band, which now follows the Media /
Server tiles on a phone). The calendar card's value is the next event's title and its meta "Next up · Today · 09:00"
(`upcoming.next_event`, any distance ahead; the 7-day band and its per-day bars are unchanged; events gained
`start_text`). The Media card no longer says "Playing now" before the snapshot's "2 playing now". The owner word is shown
only for You / Her: no "Shared" on tiles, Next 7 days rows, the Media detail foot or the weather source line.
**Media heads (U4)** `media_nav` returns `title` (the active tab's label, else the section's) and `media_base.html` uses it
as the H1 ("My films", "Diary", "Requests", "Awards"…; Live too); the person page draws its own H1 (the name, was an h2)
under a tabs-only band (`pagehead(none)` renders no H1 / foot); Awards lost its second "Awards" title (and `.awtitle`); an
eyebrow equal to the title is dropped. A page head with no backdrop is a plain page: `min-height: 0` and a 24 px / 600
title at every width (`.pagehead:not(.hero-detail, :has(> .pagehead-bd))`); the backdrop variant keeps 30 / 48 px.
**Phone chrome** in Media mode under 768 px the section pill row is hidden (the sub-tab row stays) and the to-rate count
is a `.waitcount` on the tab bar's Diary icon; **U9 (a)** the brand reads "‹ Joey" (`.brand-back`, Media pages only) and
the top bar is sticky at 48 px (`.topbar:has(.topswap)` — `.topswap` exists only in Media mode, so the header markup is
unchanged). Desktop is unchanged. **Weather (U10)** the Today strip (`.wxstats`) keeps every value on one line and is 2
columns under 640 px (not only under 400: at 3 columns the "Now" stat — glyph + "18.3 °C" — still needs more than a
third of a 430 px screen); "Today" and "Rain radar" no longer repeat the place (the page head's sub-line has it).
**Toolbars (U14)** the Movies / TV toolbar and the Watchlist sort apply themselves: `hx-get` the same path,
`hx-target="body"`, `hx-swap="innerHTML show:none"`, `hx-push-url="true"`, triggers `submit, change, search, keyup changed
delay:400ms from:find input[type=search]` (Watchlist: `submit, change`); the search box has `id="libq"` so htmx keeps its
focus across the swap; Apply is inside `<noscript>`. Grid / List is one icon link to the other layout ("Show as list");
the form never sends `view`, so the `media_libview` cookie keeps the choice (`media_pages.library_view` unchanged).
**Server (U12)** Attention renders first, under the page head, and only when non-empty ("All clear" is the sub-line, once);
Sweeps · 24 h is its own section after Updates; the tile row (`.srvtiles`) is hidden under 640 px; a row's Update now is
`btn-secondary` ("Update all" is the page's one primary). LAN-only links (`server.is_lan`: the Portainer tile and the
Services cards that say "LAN") are drawn only when `shell.from_lan(request)` — no Cloudflare Access header and an RFC 1918
/ IPv6 ULA / loopback client address (the tunnel always sends the header). **Copy (U27)** a `duration` Jinja global
(`media_text.duration`): "Started 4m ago · run again?"; uptime "12d 4h" / "5h 20m" / "40m" (`server.uptime_text`);
"Rewatch" (was "↻ rewatch"); "Last OK 3h ago"; "Update and restart media stack" (button and confirm page; was "Restart +
update"); the rated line shows the number once with a "Rated" label (the title keeps "Your rating: 8 out of 10"); Requests
counts leave out zero parts (template-side); the Diary › To Rate section label is Title Case like its tab (style guide
deviation line). **U17** `shelf_max` (= `media_home.SHELF_MAX`) is a Jinja global and the hub / Media home shelves compare
against it. Not done here (Python outside this WP): "N h this month" on Diary › To Rate (`media_pages.py`). Tests:
`tests/hub/test_first_screens_e3.py`.

**Awards page weight (WP E7, 2026-10-13).** `/media/movies/awards` was the heaviest page (130 KB, 154 posters; 0.5 s on the NAS). The page now draws the first screen only (Coming up, tiles, year stepper, hero, Most wins podium, the first 4 category cards, `FIRST_CARDS`) and ends in a sentinel `.awrest` that fetches every other card (the remaining core categories, then "More categories") in ONE request, `GET /media/{movies,tv}/awards/part/categories?body=&year=&unseen=` (`hx-trigger="revealed"`, `hx-swap="outerHTML"`, its own `hx-indicator` so the page load bar stays off). Without JS the sentinel is the plain link "All categories" to `?all=1`, which renders the whole page as before; a ceremony with nothing past the first 4 cards has no sentinel. The part route reads the same data as the page (same edition, the Not seen filter included) and queues no poster fill (the page already does). Category cards get `content-visibility: auto; contain-intrinsic-size: auto 320px` (a gold winner glow can clip at a card's edge while the card is off screen); winner-row posters in category cards use the 120 px fetch size (they show at 44-56 px; nominee thumbnails already did, and every poster is `loading="lazy" decoding="async"` through `_poster.html`). Local preview (Oscars 2025): HTML 143.5 KB to 43.2 KB, `<img>` 187 to 34 on the first load, the part carrying the other 100.6 KB / 153; server time 30 ms to 22 ms (the part 25 ms). The optional Cloudflare edge-cache checklist for `/static/*` and `/img/*` is in `docs/setup.md` ("Edge caching behind Access", unverified). Tests: `tests/hub/test_awards_weight_e7.py`.
## 2026-10-13 — Film page order + action row (WP E4; review_ui.md U5, U7; EVALUATION_2026-10-12 §4.2 "U5–U7")
B. fixed the order on 2026-10-13. **Order (U5)** the hero reads poster → episode code / name (episode pages) → title →
tagline → facts line → status line (+ upgrade note, note, search / upgrade flashes) → the ONE action row → "More" →
Directed by / Created by cards (+ a show's directors, Follow show) → an episode's overview; one DOM, so desktop reads the
same: the poster still leads beside the text column from 640 px, and the makers moved from above the status line to under
the row there too (they were in the text column before, not beside the facts). The phone poster is `width: 50%;
max-width: 200px` (under 640 px; was 62 % / 260 px). **Sub-tabs** an item / title page (a forced section,
`request.state.media_section`) draws no sub-tab row — `media_nav.nav_context` treats a forced section like
`tabs_only_on` when no tab matches; the page still names the section (Movies / TV Shows) in the pill row. **Action row
(U7)** at most four md (36 px) controls: Play (`btn-white`; Request as the white primary when there is no Play) · Trailer
(glass) · watchlist (icon) · Seerr (icon). Everything else is under `<details class="fold heromore">` "More", whose panel
is the guide's inline `.confirm` (as the cards' "Move on"): Mark watched / Reset progress, Mark (un)watched, Request beside
Play (a secondary), Search now / Search for upgrade. Every form, route and hx attribute is unchanged (the resume forms keep
E2's `hx-swap="innerHTML show:none"`). The actions part draws into two slots (`_film_actions.html` `slot`: `row` = Request
without Play + the late Trailer; `more` = Request beside Play), so `_film_parts.html` answers `fp-actions` and, beside
Play, `fp-actions-more`; `_film_wait.html` `wait(name, pending, slot)` names the second placeholder. The More fold hides
itself while its panel holds no form / link / button / line (`:has`), so a title Radarr / Sonarr does not have shows no
empty "More" once the Search now fragment comes back empty. In the panel every button is 36 px and outlined (ghost ones
get the hairline). **Site pills** IMDb / TMDB / Letterboxd (`_film_macros.html` `sitepills()`) left the hero for the
Scores strip, on a line under the score pills; a title with no strip gets a Details "Links" row. **Verified, not redone
(E2):** no runtime / certificate in the facts line, Details values without their verb, no Rate star button (the "Yours ·
Rate" pill in the strip is the one way to the picker, so no Rate link was added to More). CSS: one tail block under
`/* ---- E4 film page (2026-10-13) ---- */`; the E2 tap-target pin now allows later tail blocks that leave its controls
alone. Tests: `tests/hub/test_film_page_e4.py` (and `film_page.whole` splices `fp-actions-more`).
**Features batch 1 (E5, 2026-10-13; review_features H1, W1, M2, M3, H2, B. approved).** **Today line (H1)** `hub/today.py`
`today_line(snaps, upcoming, weather, server_card, view, now)`: one sentence after the hub's date in the page head
("Tue 13 Oct · Rain from 15:00 · 2 events · first 9:30 Dentist · New: Severance S02E03"), clauses joined by " · ", each
from data the hub already holds and dropped when its source has nothing: rain timing (`weather.rain_words`, short form;
nothing without hourly data), today's events from the Next 7 days groups ("Nothing on today" only while the calendar is
connected; media release rows never count), arr `arrived` rows whose `at` is since the start of yesterday (two titles,
"Severance S02E03" form, then "+N more"), and "<Server area's name> needs attention" only when the Server card is `warn`
(the card is found by `layout: server`, the name comes from the registry). Feed problems still follow it. **Rain words +
7 days on the glimpse (W1, BACKLOG "7-day forecast on the weather glimpse")** `weather.rain_words(hourly, now, short)`:
the first hour left today at 30 % or more and the day's peak — "Rain likely from 15:00 · 70%" / "Dry until tomorrow" (the
glimpse's meta line, before "Updated …"); `weather.week_strip` draws ONE extra row of seven cells (day letter, glyph, max;
the day name and condition word are visually hidden text, so the glyph is never the only encoding; class `.wxstrip`, not
the /weather page's `.wxweek`). The percentage reads "70%" like the glimpse's own Rain stat (the review wrote "70 %").
**375 px fix** (eyes-on of the merged eval): the glimpse's four 24 px stats wrapped "18.3 / °C". Option (b) chosen: every
value is number + `&nbsp;` + unit with `white-space: nowrap`, and under 400 px the numbers are 18 px, the Now column 1.4fr
and its glyph 24 px — four stats still fit one row (merging Low–High into one 24 px value did not fit a third of the
width either). **Show progress in words (M2)** `media_text.progress_words(unplayed, episodes, next_runtime_min)`: "4 left ·
~3h 10m" — hours only when a runtime is known, from `media_plays_db.show_runtimes` (the recorded plays' average episode
runtime per `show_key`); "All watched" at 0; nothing when the counts are unknown or a show has 0 episodes. Shown on
Continue watching cards after the remaining time (`media_home.continue_progress`: the view owner's own library counts —
her view without her list says nothing; a next-up show never says "All watched"), on My shows rows ("26 episodes · 6
left · ~4h 30m", was "· 6 to watch") and under a watching show's grid card; a Jinja global `progress_words` so the show
hero (E4's file) can use it. **To rate: Skip / Skip show (M3)** media.db `user_version` 4 (`media_store` step
`_rating_skip` → `media_db.migrate_skip`): `rating_skip(owner, key, kind, forever, created_at, title, poster)` — title and
poster added so the Skipped group needs no read. `POST /media/rate/skip` (the inbox row's rating key), `/media/rate/skip-
show` (the show's key, `forever` 1: every season and episode, later ones too), `/media/rate/unskip`; `same_origin`,
threadpooled, plain forms with `hx-swap="innerHTML show:none"`, 303 back to the To rate page (`RATE_BACK`) with
`?skip=item|show|unskip|failed` → "Skipped" / "Show skipped" / "Back in To rate" / "Couldn't save that". A movie or a
season / episode row offers Skip; a TV row offers Skip show (at the show level that is its only button). `Ratings`
carries its owner and reads the skips once when an inbox is built, so the inbox, the Diary badge and the Movies / TV
"To Rate" tab counts all drop together. A "Skipped · N" group at the foot of Movies / TV / Diary To Rate lists them with
Unskip. **Media releases in Next 7 days (H2)** `Tile.show_media_releases` (default false; on for the gcal tile in
`config/areas.yaml`) merges the arr snapshot's `this_week` rows while some registry tile reads `arr`: films as Radarr's
calendar returns them (monitored only), episodes only for shows watched in the last 30 days (the jellyfin `shows` rows),
in progress (`up_next`) or followed (`media_follows`, kind show), matched on the normalised show title. They follow each
day's own events as `.upc-release` rows: "Premiere" / "Finale" / "New episode" / "Digital release" / "In cinemas" / "On
disc" in the When column and a "Media" word chip in the Owner column. The Calendar card's per-day bars and Next up stay
calendar only. **CSS** one block at the end of `control-surface.css` ("E5 features"); E2's tap-target pin now checks that
nothing after its block touches those selectors (instead of "no @media after it"). Tests: `test_today_line.py`,
`test_weather_glimpse_e5.py`, `test_show_progress_words.py`, `test_to_rate_skip.py`, `test_media_releases_upcoming.py`.

## 2026-10-13 — Month in Review → Wrapped (WP E6; review_features M1, EVALUATION_2026-10-12 §5 row 6)
A SUMMARY, never a ranking UI (B., 2026-10-09: the By-year rankings stay deleted — no Rank / Place, no podium of your own
films; a "Top rated" list is fine). Pure reads, no new table: `hub/media_wrapped.py` reads media.db (`diary`, `play`,
`rating`, the award tables) and the jellyfin snapshot's library rows, owner-scoped by `media_db.owner_filter(view)` (the
signed-in owner; both when not signed in), and keeps each answer in memory per (file, owner, year, month, a one-SELECT
row signature of diary / play / rating / award rows, the jellyfin snapshot, today), at most 32.
**Data-source rules (no fabrication).** Films / episodes / days / rewatches / firsts and lasts / shows: the diary, one line
per (item key, date) — a watch both synced and logged, or the both view's two owners watching together, counts once;
days add a recorded play's local date. **Hours:** every recorded play (capped at its runtime, `media_plays_db._hours`;
the both view keeps one play per item and day), plus the snapshot's `runtime_min` for each diary film that no play of
that film covers within a day (watched before the recorder started, or missed by it); an episode without a play adds
nothing; with neither source the hours are "—" in a strip and left out of a sentence. A note names the sources
("Plays since 6 Oct + film runtimes" / "Plays + film runtimes" / "Films only"). **Busiest weekday / hour** and
"mostly Sunday nights" (weekday + mornings / afternoons / evenings / nights, 3 plays at least): recorded plays only.
**Scores:** the view owner's ratings (`owner_of`: the both view reads B.'s, as every score in Joey). **Award winners you
saw:** wins at the ceremonies held that year (`award_edition.year`) of a title in the diary up to the year's end or the
year's plays, the badge from `media_awards_badges.badge_of`. **The recorder's start** is the earliest `play` row, never a
constant ("Plays recorded by Joey since 6 Oct 2026").
**Month in Review** (`_month_card.html`): the Diary's first block, above the filters — one `.panel` with "This month"
(home time), a flat stats strip (Films · Episodes · Hours · Days watched · Average score) and ONE sentence ("4 films · 4
episodes · 7h 36m · mostly Sunday nights · best: Ember 10"; zero parts left out), plus "All of 2026 →". An empty month
shows the month before ("November · nothing yet", "October: …"; January falls back to last December and links that year).
**Wrapped** `GET /media/diary/year/{year}` (`media_wrapped.html`, title "2026 · Joey", H1 the year): a ‹ year › stepper
between years with a diary row or a play and this year; Numbers (films, episodes, hours, days watched, longest streak,
busiest month, busiest weekday, busiest hour), Top rated (9s and 10s, max 12, posters in a `.carousel`, "4 films rated ·
average 8.5"), Most watched shows (episodes per show, max 8, E5's progress words while episodes are left, from the view
owner's own list), Firsts and lasts (first / last watch, oldest / newest film — the year from the diary, else the
snapshot), Rewatches (count + 6), Award winners you saw (gold frame + badge), then one quiet sources line. An empty year
reads "Nothing watched in 2019". `/media/diary/year` redirects (307) to this year; a non-number or a year outside
1900–2100 is the 404 page. **Nav:** the Diary tabs are Diary · To Rate · Year (`media_nav.YEAR_TAB`, lit on every Wrapped
page, href this home-time year via `tab_href`); the hub gets no card (Media already pushes one fact). **Show hero:** a
show's status line reads "On server · 26 episodes · 6 left · ~4h 30m · S2 E3 next" (`progress_words` with the show's
average recorded episode runtime; "N left" without one; "all watched" and episode pages unchanged) — two older pins moved
from "2 to watch" to "2 left" deliberately. **Eyes-on** (local preview, 375 px): "Days with a watch" truncated, so the
label reads "Days watched"; the first hours rule (plays from the recorder's start, film runtimes only before it) left out
films the recorder missed, hence the "no play covers it" rule above. CSS: one tail block `/* ---- E6 wrapped (2026-10-13)
---- */` (tokens only). Tests: `test_wrapped.py`, `test_month_in_review.py`, `test_show_hero_progress.py` (builders and the
`wrap` fixture in `tests/hub/helpers.py`).
## 2026-10-13 — Diary: Show Mine / Everyone
B.: a per-owner setting `diary_scope` (`mine` default / `everyone`), set by a "Show" chip form in the diary toolbar
(`POST /media/settings/diary_scope`, 400 on any other value). Like Jellyfin, where only the admin sees every user's
history, only owner "you" (and the not-signed-in local view, as `owner_of`) may pick Everyone; Georgina never sees the
toggle and her POST is 403. Everyone lists both owners' rows (`list_diary(owner=None)`; `group_diary` already folds per
owner and now carries `owner`), each naming whose it is in words ("You" / `OWNER_NAME_HER`). Stats, streak, Log a watch,
On this day and the Jellyfin sync stay the viewer's own.

## 2026-10-13 — Merge: evaluation round (E1–E7) × nav-tidy
B.'s nav-tidy (five Media sections, Diary folded into Activity, sentence-case labels, permanent Media top bar) landed on
main while E1–E7 were built, and it wins on navigation structure and labels. The round's features were re-homed: the
Wrapped page has no Year tab (reached from the Diary's Month in Review card; lights Activity › History); the phone bar's
to-rate count sits on the Activity slot; "To Rate" reads "To rate" everywhere (style guide lines 15–16); E3's sticky
48 px Media bar is keyed on `.brand-back`; the Diary page runs E1's memoised history sync and nav-tidy's Mine / Everyone
scope together. Suite 2,322.

## 2026-10-13 — Library pages: Suggestions, one flat grid, more sorts, diary picker
B. ("go for all"). **Suggestions** `/media/movies` and `/media/tv` open with a "Suggestions" carousel (was "New this
week") under a chip switch New · Continue watching · Not yet watched (`?s=new|continue|unwatched`, remembered in the
`media_libsugg` cookie, path `/media`, like Grid / List; default New). New = the arr arrivals this week; Continue watching
= films in the viewer's resume list in Jellyfin's most-recently-played order (the card says "32 min left") / shows in state
watching, latest watch first; Not yet watched = films not played and not in progress / shows not started, newest added
first; at most 12 (`media_library.suggestions`, `SUGGEST_MAX`). An empty set is one line ("Nothing in progress"); the
switch never hides. **One flat grid** the Grouped chip and its section labels are gone: grid and list show every title
in one sorted section, narrowed by toolbar filter chips (`?f=`, links keeping q / sort / s / view; films All · Continue
watching · Not yet watched · Watched, shows All · Watching · Not started · Finished; active chip `on` + `aria-current`;
the form carries `f` so a search keeps it). A filter adds the section label "Not yet watched · 35"; All adds nothing.
`arrange()` is filter + sort; an old `group=` is ignored. Without her own list (her view) there are no chips.
**Sorts** Last watched, Shortest first, Longest first (unknown runtime last), Oldest release, Genre A-Z (first genre, no
genre last), Shuffle (fresh each request) and, on TV only, Most to watch (`sort_labels(kind)`); Your score stays the
default. **Diary** in Everyone, the other person's rows carry no 1-10 picker and no score (`row["theirs"]`); the viewer's
own rows keep both. Tests: `test_media_library_pages.py` (library round block), `test_media_diary.py`, one count in
`test_first_screens_e3.py`.
**2026-10-22 — merged onto main 5d3c536** (the awards ballot, TV episode flow, WP-T1 season words, request
quality, Why?, Joey TV rounds). What moved: WP-T1's "Caught up · more to come" group became a fifth TV filter chip,
"Caught up" (All · Watching · Not started · Caught up · Finished; `?f=caught_up`, label "Caught up · 1"); the
Suggestions carousel keeps Joey TV WP-B3's rule (none in TV mode; the TV hides the toolbar, so no chips there either);
the "Waiting for the first episode" block sits after the flat grid. Two opens closed: on a phone (< 640 px) the filter
chips are one row that scrolls sideways like the Media section pills (`.libchips`, a dated tail block in
`control-surface.css`); her shows' Continue watching without her own list reads "No marks for her yet", not "Nothing in
progress". Tests re-pointed: `test_season_state.py` (caught-up label under `?f=caught_up`), the chip lists in
`test_media_library_pages.py`.

## 2026-10-14 — Awards ballot (Plan C)
B. chose Plan C of the awards UX review (review/2026-10-13-awards-ux/AWARDS_UX_REVIEW.md; decisions in BALLOT_DECISIONS.md,
all defaults). The Awards page is now a ballot of films / shows (described under "Decisions pinned by tests" in
`hub/README.md`): WP-C1 built the context (`awards_ctx` `ballot`: the edition pivoted by work, filters, sorts, shorts,
progress, people, `/awards/part/rows`), WP-C2 the templates, the picker sheet and one dated CSS tail block, WP-C3 the
worded Watchlist button on a row (`_watchlist_btn.html` `style="ballot"`, handed back by the watchlist routes), pills that
name a person only for acting and directing, "Writing (Original Screenplay)" → "Orig. Screenplay", the row year fallback
(the edition's "films of" year), the rows sentinel inside the list, and a phone row whose pills take the full width.
**Reversal:** the awards-ui visual pass (2026-10-09) backdrop hero and Most wins podium are removed (decision B5: the
winner was shown twice; the first row is the headline winner and "Most wins" is the sort), along with the ceremony tile
row, the year stepper and the native year dropdown (all now inside the picker). Eyes-on at 375 px (sample seed, Oscars
2025): the picker at 235 px from the top; the default view 3,166 px tall (target 2,500 — open); every filter / sort /
ceremony / year change keeps the scroll and does not re-fetch posters already on screen.

**Awards older page shapes (WP-D1, 2026-10-16).** Live on the NAS the sync had finished with most older editions
`skipped` as "no page shape (none)" (Globes 80 of 84, SAG 26 of 33, Critics' Choice 6 of 32, BAFTA 17 of 80): the parser
only read the `{{Award category}}` shape. `parse_award_blocks` now also reads wikitables whose `!` header cells name the
categories (Globes to 2023, SAG to 2020, early BAFTA; a header row followed by another is a group caption; a linked cell's
label is the link target minus "<…> Award for ", so "Drama" becomes "Best Motion Picture – Drama" and the category key stays
the award page's QID across years), `* '''Best Actor:'''` bold-label lists (Critics' Choice 1996–2001, winners only) and,
only when nothing else reads, `===Category===` headings with a bare bold winner line ("[[Person]] in [[Film]]" read like a
dash; page-structure headings are never categories). `{{Award category}}` pages parse exactly as before. `PARSER_V = 2`
(`media_awards.py`, stored as `award_sync.parser_v`): the first pass after a bump puts every "no page shape" skip back to
pending, so they re-enter the normal backlog. WP-D3 (same day, same bump): inside an `{{Award category}}` block a bare bold
line (not a list item) is the block's winner — Critics' Choice 2002–2018 and BAFTA 1965–1972 write the winner that way and
had landed `done` with nominations but no winners — and the bump also re-queues every `done` Wikipedia-sourced edition
with nominations and no winner (logged as two counts; the re-pull rewrites the edition whole). Tests:
`tests/hub/test_awards_parse.py` (one per shape, eleven recorded pages under `tests/hub/fixtures/awards/`),
`tests/hub/test_awards_sync.py` (table page pulled done, the re-queue of both kinds).

**TV episode flow (2026-10-16).** Show, season and episode pages (`media_film.html`, kinds series / season / episode) gain
the episode-rating layer and the episode drill-down B. asked for from an IMDb screenshot (review/2026-10-16-episodes-ux:
shell, notes, contract). Ratings (`hub/media_episode_ratings.py`, WP-E1): one OMDb `?i=<series imdb>&Season=<n>` call per
season (every episode's imdbRating), votes for the current season only (≤ 12 per-episode calls), stored in media.db v5
`episode_rating`, refreshed every 7 days while a season is airing and never afterwards, FAIL_TTL memo, a 401 stops OMDb
for the day, the 800/day budget shared with the Metacritic pill, TMDB `voteAverage` (Jellyseerr season read) as the
fallback; all reads run in a BackgroundTask after the render (0 calls on a warm view; `ratings` is None until a first
view has queued them). Pages (WP-E2, `_episode_flow.html`): the show page's "Seasons compared" (one SVG line per season
on a shared 6–10 scale, dashed 8.0, average + seen of total, the current season gold, best episode + trend) and the
IMDb-style rating strip (a bar per episode, green = seen, gold = the page's episode, dashed = not aired); the season page's
S-switch + strip + rated rows ("above avg" / "below avg"); the episode page's crumbs (the show and the season as the two
ways back), the "Show · S4 · E3 of 6" eyebrow, the ★ score line, Guests (GuestStar people not in the main cast, with
"k eps this season"), Crew (Directed by / Written by — the show-level Crew block is skipped there), the "where this sits"
mini strip and Previous / Next. People and navigation (WP-E3): `nav` / `guests` / `crew_ep` from the Jellyfin People the
pages already read (`people_names` kept on the season episodes read; no extra calls); person hrefs stay None because
Jellyfin People carry no TMDB id. Two earlier rules superseded: the media-ux4 "no series link in the episode hero" (the
crumbs are that link now) and the episode page's show-level Director / Writer block (its own rows replace it). Tests:
`tests/hub/test_episode_ratings.py`, `test_episode_flow_templates.py`, `test_episode_flow_nav.py`; schema pins moved
to v5.

Health logos + Server app links (2026-10-19, WP-H1). Each row on Media › Health now shows the Server grid's service logo
(32 px, `alt=""`; the neutral initial tile when the id has none) and takes the gated hostname from areas.yaml when there
is one — the page decorates the snapshot's apps through `server.service_card`; the backup row is unchanged. On the Server
page every Services card now shows from anywhere and links to its gated hostname or LAN address (the "LAN" word stays in
the subtitle): this reverses E3's off-LAN hiding of cards (back to the 2026-10-10 rule); the summary link tiles (Portainer)
still show only on the LAN. Tests: `test_media_detail.py` (two Health tests added), `test_first_screens_e3.py`
(`test_lan_only_links_show_on_the_lan_only` re-pointed).

Season state words (2026-10-19, WP-T1). B.: WAR (2026) read "all watched" with 3 of 8 episodes on disk and 5 still to
air. New `hub/media_season_state.py` reads Sonarr live from the hub (no connector change): ONE `GET /api/v3/series`
(the whole list, statistics per season, matched by TheTVDB id then TMDB id, never by title) serves every show on every
page, and a show / season / episode page adds `GET /api/v3/episode?seriesId=&seasonNumber=` for each incomplete season
(the latest 3) for exact aired / to-come counts and the next air date; both kept 10 min, a failed read keeps the last
good answer and is not retried for 60 s. Pages never call Sonarr before the render: they draw from the cache and queue
the reads as the response's BackgroundTask (the first view may lack the words, the next has them; a Sonarr failure
never fails a page). Words: "Complete" · "5 to come · next airs 2 Nov" ("date TBA") · "2 aired, not downloaded" ·
"Waiting for the first episode · airs 5 Dec" · "Season 3 announced"; a series with everything Sonarr knows of says
"Complete" when Sonarr calls it ended, else "Up to date". Where they show: the show hero status line ("On server · 3 of 8
episodes · all watched · 5 to come · next airs 2 Nov" — the state is always the last word), each Seasons row head
("Season 4 · 3 of 6 watched · 5 to come · …"), the season / episode page "part of" line, My shows (a fully watched show
with more due is "Caught up", grouped "Caught up · more to come", not "Finished"; the head line adds "N caught up" only
when there are any), and Requests (a partly downloaded show: "Partly available · 3 of 8 episodes · 5 to come · …").
On-server rule: a show is "On server" only with an episode file. A series Jellyfin lists with 0 episodes (Sonarr's
folder before the first file; the connector already drops a counted 0, the hub now guards too via
`media_library.empty_series`) is no library entry — left out of My shows (listed under "Waiting for the first episode"
instead), the library keys (watchlist "On disk", shelf / collection "On server"), the Activity › Library links and the
title page's library row; its item page and a Sonarr-only show's title page read "Requested · waiting for the first
episode · airs 5 Dec" (no Play), and its Requests row says "Requested" whatever Seerr's word. Without Sonarr connected,
or for a show Sonarr does not have, every page keeps its words. Tests: `tests/hub/test_season_state.py` (new, 25);
`test_media_follow_shows.py`, `test_media_discover_search_now.py`, `test_media_requests_remove.py` re-pointed (their
"no call at all" pins now allow the one background series-list read, `helpers.not_season_state`).
2026-10-19 (WP-T2): the hub's Weather tile left the top row (now the three area cards in three equal columns, one on a phone) and the weather glimpse runs full width directly under "Next 7 days", its 7-day strip spreading across the row; tests: `test_hub_page.py` (two added, one re-pointed), `test_first_screens_e3.py` / `test_hidden_areas.py` / `test_weather.py` (re-pointed), `test_style_pages.py` (CSS block test added).
Server clean-up (2026-10-19, WP-T3; review/2026-10-19-server/SERVER_REVIEW.md §1, S1–S9). The Server page is five bands:
Attention → System → Services → Updates → Last 24 h. Gone: the tile row (S3; it only linked down the page, the hub card
is the summary — Portainer is already a `media_status` app, so its LAN link tile simply dropped and its Services › System
card stays; `_tile_row` and `.srvtiles` removed) and the Counts band (S1 + S2; Requests / Torrents / arr downloading
repeated Activity, the arr disk bars repeated System's volumes; `_counts` and `.cols` removed). The Counts band's unique
figures are ONE "Library health" line under Services › Downloads (`library_health`: "Radarr 2 wanted · 3 missing ·
Sonarr 7 wanted · Prowlarr 3 failed grabs", only the non-zero parts, "all clear" otherwise, amber on failed grabs, and a
Search missing link to `/media/requests?sweep_ask=missing` when anything is wanted or missing). The "Media stack" line
shows only when stackctl is connected (S4). Sweeps · 24 h is one line under System ("7 connectors · all sweeps OK · Last
sweep 12m ago" / "1 failing: gcal" / "2 not configured"; `sweep_summary`) with the rows in a fold that opens itself on a
failing or not-configured row; the Last sweep stat moved into that line (S5). The disk projection (`disk_days`, lifted
out of `disk_trend`) joins the PAGE's Attention under 30 days ("/volume1 reaches 85% in 23 days at this rate") — not
`attention_items`, so the hub card and the Discord push are unchanged (the hub loop has no samples); Last 24 h is the
last band, a `<details>` open on a desktop and closed on a phone (`data-phone-closed`, a small `joey.js` hook) (S6).
Attention items carry their action (`attention_action`, S7): a down service "Open" (its card link, new tab) or
"Services"; an Uptime Kuma monitor "Services"; a failing sweep "Sweeps" (#system). The Updates line reads "17 monitored
· 2 updates · checked 2h ago", amber "Stale · checked …" only past the Updates tile's `stale_after_minutes` (S9). Tests:
`tests/hub/test_server_cleanup.py` (new), `test_server_library_health.py` (was `test_server_counts.py`), and
re-pointed `test_server.py`, `test_server_cards.py`, `test_server_history.py`, `test_server_not_configured.py`,
`test_server_stack.py`, `test_server_updates.py`, `test_first_screens_e3.py`, `test_area_pages.py`,
`test_style_pages.py`.
Request quality profile (2026-10-21, WP-R1). Seerr has one Radarr and one Sonarr server (neither 4K), so 1080p / 4K is the
arr app's quality profile, as Seerr's Advanced › Quality Profile. New `hub/media_quality.py`: `profiles(kind)` (Radarr /
Sonarr `GET /api/v3/qualityprofile`, names as the app has them, `is_4k` from the name — 4k / 2160 / uhd — and the default
from Seerr's `GET /api/v1/settings/radarr|sonarr` `activeProfileId`, else the first non-4K; kept 10 min, a failure keeps
the last good list and is not retried for 60 s, never raises). The Request confirm step shows a "Quality" row of radio
chips ("1080p · Default" preselected, "4K"; none with one profile or a failed read; TV: under the seasons picker, and
the seasons onchange no longer unticks "All seasons + future" for a quality click); the POST validates `profile` (422
"Pick a quality" for an id the app does not offer) and sends `profileId` to Seerr — no `serverId` needed (Seerr's
MediaRequestSubscriber applies a profileId to the default server). Safety net: after a non-default request the arr
entry is read back (3 reads, 2 s apart, before Sonarr's "All seasons + future" follow) and PUT + searched when its
profile differs; the done line says "Requested in 4K ✓ — shows in Requests within the hour", plus a warning when the app
had not added it yet. The title / item page lazy-loads `GET /media/title/{kind}/{tmdb}/quality` under the status line:
"Quality · 1080p" from the arr entry's `qualityProfileId` (never a request's stored id) and "Switch to 4K" (a 4K title:
"Switch to 1080p"), an inline confirm ("Radarr will look for a 4K file and keep the 1080p one until it arrives."), then
the same-origin `POST …/quality` PUTs the app's own resource with the new profile and sends MoviesSearch / SeriesSearch
("Switched to 4K · searching" / the failure word); no-JS: `?quality_ask=1` draws the panel, the POST 303s with
`?qswitch=&qk=&qp=`. Requests page: a "4K" badge after a row's title when its arr profile is not the default — from
caches only (Sonarr's series list the season words keep; media_requests' Radarr lookups), the missing reads (profile
lists, up to 10 film lookups) in the response's BackgroundTask. `media_requests.find_kept` now shares one in-flight read
between concurrent askers (the Search now and Quality fragments load together), and `kept()` peeks its cache. Call
budget: a title view 0 before render, then ≤1 lookup (shared, 5 min) + ≤2 profile reads (10 min); a request +1
validation read (cached) and, non-default only, ≤3 lookups + ≤1 PUT + ≤1 command. Tests: `tests/hub/test_media_quality.py`
(new, 49 cases), `helpers.not_quality` (new), `conftest` (clears the profile cache), re-pointed `test_media_episodes.py` (confirm
step reads the profiles), `test_media_requests_remove.py` (two call-list pins), `test_season_state.py` (Requests page pin).

**App links (WP-L1, 2026-10-21).** Activity › Downloads and Activity › Requests carry a small "Open qBittorrent ↗" / "Open Seerr ↗" glass button under the page head (`templates/_app_link.html`, `media_pages.app_link`): the Health row's logo (or initial tile) and the gated hostname, else the media_status snapshot's LAN address with a "LAN" word; nothing when that snapshot or the app is absent. Tests: `tests/hub/test_app_links.py` (new).

**Below cutoff + Why? (WP-U1, 2026-10-21).** B. saw "Upgrade available" on Brothers (2026) S01E01 (HDTV-1080p) after
"Search upgrades" had run — Sonarr's own words: "Completed search for 1 episodes. 0 reports downloaded." — and its
interactive search showed why: 30 releases, all rejected, nearly all by the "1080p" profile's minimum custom-format score
(1000) that nothing reaches. So: (1) the label reads "Below cutoff · <have> → wants <want>" on every surface (list rows,
cards, hero, Requests, Downloads; `media_upgrades.LABEL`), and the `arr` connector names a cutoff quality GROUP by its
members ("WEB/Bluray 1080p", never "Default"). (2) The connector reads each app's `GET /api/v3/command` (one call per app
per sweep) into `upgrades.last_search`; Downloads shows "Last upgrade search · Sonarr · 21 Oct 00:59 · 1 searched ·
0 downloaded" under the Search buttons. (3) Each Downloads › Upgrades row gets "Why?" (`media_upgrade_why.py`,
`_upgrade_why.html`, `.upwhy` CSS): confirm → the app's interactive search (90 s, threadpooled, kept 1 h) → summary,
grouped reasons, the custom-format hint, top 5 releases with "Grab anyway" (confirm → `POST /api/v3/release` with the kept
guid + indexer id; "Grab sent · check Downloads in a minute" or the failure word). The connector also adds `profile` to
every row and `episode_id` to Sonarr rows (the episode Why? searches). Arr call budget: page render 0; Why? confirm 0;
Why? 1 interactive search per row per hour; Grab 1 POST; connector +1 small call per app per 120 s sweep. Tests: new
`tests/hub/test_media_upgrade_why.py` (28); `tests/connectors/test_arr_upgrades.py` (+6, 3 re-pointed),
`test_contract_doc.py` (+1), call counts in `test_arr.py`, `test_arr_counts.py`, `test_http.py`; the three F4b hub files
re-pointed to the new wording (dated docstrings); `conftest` clears the Why? cache; `config/sample_snapshots/arr.json`
regenerated.

**Guest front: `joey-media`, `JOEY_FRONT`, route classification (Joey TV WP-B1, 2026-10-21).** The hub image can now run as a
second, guest-facing process. `hub/guest.py` holds `front()` (`JOEY_FRONT` = unset / `private` / `media`, anything else stops
startup), the GUEST / PRIVATE / RESERVED route tables, `allows()` (deny by default, HEAD = GET, the guest home `/a/<shelves id>`
resolved at runtime), the `GuestGate` middleware (registered first, so it is innermost and the request log sees its answers)
and the media-mode snapshot scrub. On the media front `/` redirects to the guest home, an allowed route without an identity
redirects to `/signin?next=`, and every other path, unknown ones included, gets the same Joey 404 page; the media front
ignores the Cloudflare Access email header. The private front only gains a Host guard: a request for `MEDIA_PUBLIC_HOST`
(default `media.joeyhome.net`) answers 404. `shell.get_snapshots` is the one read point and, on the media front, keeps only
`jellyfin`, `jellyseerr` and `arr` with B.'s played state and the requester name removed; `tasks.lifespan` starts no loop there.
`Identity` gained `jf_user_id` and `jf_token` (default `None`) and `guest.TV_UA_TOKEN = "JoeyTV/"` is the TV shell's user-agent
token; both are frozen interfaces (`hub/README.md`). `/healthz` adds `front` and, on the media front, `home`. Compose gained
`joey-media` behind `profiles: [media]`: dark, no published port, snapshots `:ro`, no backups mount, 384m, `media.env` only
(`deploy/README.md`, `docs/network.md`, `docs/setup.md`); `deploy.sh` runs its smoke only when the profile is active. A route
that is not in one of the three tables fails `tests/hub/test_guest_routes.py` by name. Tests: new `test_guest_routes`,
`test_guest_surface`, `test_guest_snapshots`, `test_guest_lifespan`, `tests/deploy/test_joey_media_service.py` and
`test_route_sweep.py` (`tests/README.md`); `test_compose_limits` and `tests/connectors/test_container.py` gained the service.

**Guest sign-in and fail-closed owners (Joey TV WP-B2, 2026-10-21).** The media front now has its own sign-in. A guest signs
in with Jellyfin Quick Connect (code on the page, approved on a phone) or username and password; the Jellyfin access token is
the session, kept in `__Host-jm_session` (90 days absolute) beside `__Host-jm_qc` (10 min) and `__Host-jm_dev` (the device id).
`hub/guest_auth.py` re-validates it against Jellyfin `/Users/Me` (verdict kept 60 s, up to 300 s more while Jellyfin does not
answer; a dead token clears the cookie, an unreachable Jellyfin is a 503 with the cookie kept) and refuses a disabled user, an
administrator or a user with remote access off (P1). Wrong passwords are counted per username, 5 in 15 min, in process, and
refused without calling Jellyfin so Jellyfin's own lockout is never reached. The five routes (`GET /signin`, `POST /signin/qc/start`,
`GET /signin/qc/poll`, `POST /signin/password`, `POST /signout`) replaced the RESERVED `/signin*` entries; `GET /signout` is a 404.
`media_db.owner_of` / `owner_filter` now raise on a malformed `jf:` key and, on the media front, on any view that is not
`you` / `her` / a friend key, so a friend can never read or write B.'s rows (the gate flagged in WP-B1 before the `media` profile
is enabled); plays, home shelves, resume, `shell.resolve_owner_view` and the diary scope follow. P3: on the media front Jellyfin
reads and resume writes use the signed-in user's own id and token, never the admin's. `GUEST_DEV_OWNER` must now be a
well-formed `jf:<32 hex>` key. Tests: new `test_guest_owner`, `test_guest_auth`, `test_guest_signin`, `test_guest_no_leak`
and the fake Jellyfin `tests/hub/fake_jellyfin.py` (`tests/README.md`). Docs: `hub/README.md` "Guest sign-in", `docs/setup.md`.

**TV app download and update endpoints: `/app` (Joey TV WP-B8, 2026-10-21).** The media front gains `hub/tv_app.py`: `GET /app` (plain HTML,
no JS: version, notes, one big Download link, Downloader steps; "No build published yet" while empty), `GET /app/version.json`
(`Cache-Control: no-cache`, the app's daily update check), `GET /app/latest.apk` (302 to the versioned APK, `no-store`, a short URL for
Downloader) and `GET /app/<joey-media-semver-code.apk>` (`application/vnd.android.package-archive`, `public, max-age=31536000, immutable`);
anything else under `/app` is the ordinary byte-identical 404. They read `TV_APP_DIR` (`/data/tv-app`, mounted `:ro` from
`/volume1/Docker/joey/data/tv-app`), which `deploy.sh`'s `deploy/tv_publish.py` fills from the GitHub Release `tv-<versionCode>`. In
`hub/guest.py` GET `/app` and `/app/{rest:path}` moved from RESERVED to GUEST and PUBLIC (Q37: no sign-in); on the private front every
`/app` path is the same 404. Tests: `tests/hub/test_tv_app_routes.py`. Docs: `docs/tv-release.md`, `hub/README.md` "Guest front".

**Recorder: a finished play seen again is not a second play row (Joey TV playfix, 2026-10-21).** After a play crossed
`FINISHED_PCT` (90 %), every later poll that still saw the session at >= 90 % inserted a new `play` row, inflating play counts,
History stats and `watch_count` (found by WP-B3). `media_plays_db.record_sighting` now takes the latest row of the same `owner` +
`jf_id` seen within `OPEN_GAP`; a finished one seen again at >= `RESTART_PCT` (10 %) only has its `last_seen_at` / `position_pct`
updated and stays finished. Below 10 % (a re-watch from the start) or after `OPEN_GAP` it is still a new row. Schema unchanged;
the friend diary (WP-B3) stays one row. Tests: four new in `tests/hub/test_media_plays.py` and `tests/hub/test_friend_diary.py`.

**TV mode matched to the signed-off mockup (Joey TV WP-B3 follow-on, 2026-10-21).** The WP-B3 build shipped TV mode as a first
pass; `hub/static/tv.css` now follows `JoeyTV/mockups/tv-mode.html`. Overview: no page-head band (the template skips it in TV
mode), shelves run edge to edge with 14 / 10 px padding, an orange 5 px progress bar over the poster foot. Movies / TV shows: the
head band shrinks to a sticky sub-tab row under the top bar, a six-column grid, the search / Grouped / sort toolbar, "New this week"
and the freshness lines hidden, grid captions show the year only. Title page: hero layout with a three-line synopsis, the worded
Watchlist button and the 1-10 chips (`media_film.html` branches on `tv_mode(request)`; `_rate.html` `picker(r, label)` takes the
label). Set up Jellyfin: a full-screen card, `:8443` gold and underlined. Sign-in: spacing around the waiting line and the
"Get a new code" button. Brand 22 px bold; 16 px floor; no `:hover`. `tv.js`: the D-pad stays on the Set up card, scroll-into-view
accounts for the sticky sub-tabs. Guest manifest shortcuts read Movies / TV shows / Discover. Tests: `test_tv_mode.py` pins no
`:hover` in `tv.css` and that the private front links no TV asset. Docs: `hub/README.md` "Guest surface and TV mode".

**Friend requests through Seerr (Joey TV WP-B4, 2026-10-21; TV styling follow-on same day).** `GET` + `POST
/media/title/{kind}/{tmdb_id}/request` moved from RESERVED to GUEST (`RESERVED` is now empty): a friend's request is sent
with the admin key plus `X-Api-User: <their Seerr id>` so Seerr creates it AS them, pending (DECISIONS B #19). The Seerr id is
looked up by `jellyfinUserId` (1 h cache); a friend with none is imported on their first request (that friend only, Q29). A
friend whose Seerr user could approve is refused before sending; no quality profile and no Sonarr follow on the media front
(Q19); nothing approves, declines or removes (B. declines in Seerr; the friend sees Declined). New `hub/media_guest_requests.py`;
the one POST stays `media_discover._send`. The Discover screen (WP-M screen 10) is a poster grid with In library / Requested /
Request / Declined chips and a request panel in a `<dialog>`. Follow-on: `tv.css` styles Discover and the panel to the mockup
(six columns, the one-tab sub-tab row dropped, 780 px panel card), and the panel's answer keeps its poster, title and overview.
Tests: `test_guest_requests.py`, `fake_seerr.py`, `test_tv_mode.py` (Discover pin). Docs: `hub/README.md` "Requests",
`docs/public-edge.md` R1 step 4.

## 2026-10-22 — P4 Quiet mode

**Server › Downloads: "Quiet (5 Mbps) · Full speed" (P4, SERVER_REVIEW §2; B. accepted the defaults 2026-10-22).** The
2026-10-12 evaluation's biggest cause of slow pages was qBittorrent saturating the download link (E0: B. capped it by hand);
the knob is now on the Server page. One row under Services › Downloads, right after the Library health line: "Downloads"
then two chips — the active mode filled, the other a link to its confirm — plus "NAS sleeps 22:00–07:00" in muted text
(`NAS_SLEEP_WINDOW`, words only). A cap set elsewhere ("custom") shows "Capped at 2 Mbps" with both chips as links. No row
when the hub lacks `QBIT_URL` / `QBIT_USER` / `QBIT_PASS` or the snapshot has no `dl_limit_bps`. New `hub/server_quiet.py`
(the server_stack pattern): `GET /server/downloads/cap?mode=quiet|full` = confirm card (`server_quiet.html`), `same_origin`
POST = the feed's login, `POST /api/v2/transfer/setDownloadLimit` (Quiet = `QUIET_MBPS`, default 5 Mbps = 625000 B/s; Full =
0), then `transfer/info` re-read to confirm (modes compare by words: qBittorrent keeps KiB/s, so 625000 reads back 624640),
303 to `/server?cap=quiet|full|failed#downloads` with "Quiet mode on" / "Full speed" / "Couldn't reach qBittorrent". The
render makes no call; a confirmed change is kept until a newer snapshot lands, so the page after the redirect already shows
it. `upstream.UPSTREAMS` gains "qbittorrent" (the SID cookie is passed per call; the Session stays stateless). The
connector adds `dl_limit_bps` / `dl_limit_text` from the `transfer/info` it already reads (schema, contract doc, sample
snapshot). The routes are PRIVATE in `hub/guest.py`, never GUEST. CSS: one dated tail block (`.quietrow*`, the shared
`.chip` recipe reused). `deploy/.env.example`: `QUIET_MBPS=5`, `NAS_SLEEP_WINDOW=22:00–07:00`; QBIT_* moved to the "both
files" line of the env split. Tests: `tests/hub/test_server_quiet.py`. Not tried live: qBittorrent 5.2.4's real answer to
`setDownloadLimit`.
## 2026-10-22 — P2 Overnight digest

One Discord message a day with the night's state in words (assistant idea P2, `review/2026-10-19-server`; B. accepted the
defaults 2026-10-22: 07:30 hub-local, the existing Discord channel). New `hub/server_digest.py`: `build(snaps, now)` joins
" · " parts from the snapshots the hub already holds — "Joey digest · Thu 23 Oct · Arrived: 3 episodes, 1 film · 1 update
pending · Disk 71 % · All 11 services up · 2 torrents stalled" (arrivals = the arr snapshot's `arrived` rows from the last 24 h,
a `season` row counted by its "N episodes"; updates = WUD rows through `server.split_updates` with the ignores; disk = the
fullest volume; services = media_status apps, "Down: Radarr, WUD" when any; torrents = qBittorrent "Stalled" rows, else
"N downloading"). A part whose snapshot is missing is left out, none at all ⇒ no message; at most 300 characters. `tick()` runs
on a new 5-minute loop in `hub/tasks.py` (first check 90 s after startup): it posts through `server_alerts.post` to
`SERVER_DISCORD_WEBHOOK` once per hub-local day once the time reaches `DIGEST_AT` (default 07:30), records `media.db`
`server_digest_sent(day, at, text)` only after a successful post, retries a failed post on the next tick (at most 3 per day),
and does nothing without a webhook or with `DIGEST=off`. A hub that starts at 09:00 still sends that day. The Server page's
System band gets one line under the sweeps line — "Digest · sent 07:31" / "Digest · not sent today" / nothing without a
webhook (`last_sent`, passed from the `/server` route as `digest`). `deploy/.env.example`: `DIGEST_AT`, `DIGEST`. Tests:
`tests/hub/test_server_digest.py`.
## 2026-10-22 — P1a Free space page

**Free space (P1a, B.'s decision 2026-10-22: LIST ONLY).** New owner-only `GET /server/space` (`hub/server_space.py`,
`server_space.html`; PRIVATE in `hub/guest.py`, so the media front 404s it): the 10 biggest watched films and the 10
biggest finished shows still on disk, one list by size. Row: title, year · "12.4 GB" · "Watched 3 Mar" / "Finished ·
8 episodes", the whole row linking to the Joey item page (`row_href`). Head line "Removing all 20 frees ~84 GB", plus
"(≈ 19 days at this rate)" when the Server page's disk forecast exists (the freed share of that volume over the
`disk_days` rate); empty state "Nothing watched is taking space yet"; "Not connected" without sizes or Jellyfin. No
delete, no form, no button that changes anything. A watched film is a Jellyfin `played` row; a finished show has episodes,
`unplayed == 0` and Sonarr `ended`. Joined by provider ids (`item_key` `tmdb:` / `tvdb:` against the arr rows'
`tmdb_id` / `tvdb_id`), never by title. Sizes: the arr connector's new `library_sizes` block (radarr `tmdb_id, title,
year, size_bytes` from `/api/v3/movie` `hasFile` + `sizeOnDisk`; sonarr `tvdb_id, tmdb_id, title, size_bytes, ended`
from `/api/v3/series` `statistics.sizeOnDisk`), built from the lists the counts already fetch (no extra call); contract
doc, schema, fixtures and `config/sample_snapshots/arr.json` updated. Links: the Attention disk-forecast item's action is
now "Free space" (`attention_action`), and the System band's first disk block has a small "Free space" link. Tests:
`tests/hub/test_server_space.py`, `tests/connectors/test_arr_library_sizes.py`, a contract-doc pin; the two WP-T3
forecast-has-no-action assertions in `test_server_cleanup.py` now expect Free space.
