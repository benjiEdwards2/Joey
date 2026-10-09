# hub

FastAPI + Jinja/HTMX dashboard shell. Areas are config, not code — see `config/areas.yaml` (WP16).

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
keep the bottom bar; no layout is built in JS. Media pages also link
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
with Newport VIC as fallback), lazy-loaded, captioned, with a static "Needs internet" note; shown even when the weather
snapshot is absent; a square column beside the forecast from 1100 px, below it on narrower screens. The 2026-10-06 BOM
layer-stack panel is parked: `weather_radar()` context, the `.wxradarbox` CSS and `GET /weather/radar/{name}` (allowlisted
names from `SNAPSHOT_DIR/radar/`, else 404) remain; the connector fetch needs `RADAR_LOOP=1`. Greeting
clock: `_now_home()` (Australia/Melbourne).

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
score grades `--score-1…9`, `--rad-*`, `--appicon-bg` (the white tile behind a service logo).

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
`--appicon-bg`, `.st-up/.st-down` words beside a `.svc-dot`, `.svc-card.is-down` tint; the 20 px `.appicon` rule is now
unused), Monitors/Updates/Attention rows (Update now `.btn-primary .btn-sm`, Ignore `.btn-ghost .btn-sm`, the
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
(Uptime Kuma: status word + dot + response ms per monitor, down first), Updates
(`N monitored · N updates` + a row per pending update), Attention (any service Down, any volume ≥ 85 % used, any
Uptime Kuma monitor Down/Pending, the `media_backup` warning — none / older than 36 h, and every connector whose
last `_runner.json` result is an error, with its sanitised reason) and Counts (Jellyseerr pending/approved/available, qBittorrent
downloading/seeding/speeds, arr downloading / this week / disk rows). Each band says "Not connected" on its own when its
snapshot is missing. Tile `detail` links are anchors (`/server#services`, `/server#monitors`, `/server#updates`). `_runner.json` is read by
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
line 1 "All up" / "2 down: Prowlarr, Sonarr" and line 2 "N updates" (ignored ones excluded, omitted at 0) · "disk N%"
(fullest volume) · "N monitors down" (when > 0). When Attention is non-empty the card wears the amber stale badge with the
words "Needs attention" (no new colour); a missing `media_status` snapshot still reads "Not connected". Attention items are
now keyed (`attention_items()`: `down:<app>`, `disk:<path>`, `kuma:<monitor>`, `backup`, `sweep:<connector>`). Sweep
failures are durable: `store.get_runner_history()` reads the tail of `_runner_history.jsonl` (last 2 MB, up to 1000 lines,
malformed lines skipped) and `server.sweep_stats()` counts the last 24 h per connector — Attention says
"wud failed 3 of the last 24 sweeps · <sanitised reason>" only while the connector's latest run is still an error; the
Attention card's "Sweeps (24 h)" rows list every connector (runs · failed · last ok). No usable history ⇒ the old
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
Attention items, never post to Discord and never put the hub card in its warn state; the "Sweeps (24 h)" table still
lists them with the words "Not configured" instead of "Failing". Because they leave Attention, `server_alerts.sync`
deletes any `server_attention_seen` row they had, so a later genuine failure notifies again. The hub loop passes the
loaded registry; `check_once()` without one reads `AREAS_PATH` / `config/areas.yaml`.

**Services card grid (WP-U3, 2026-10-07).** B.: "logos … so much easier to find them in the card form". Each group is a
Homepage-style grid (1 column on a phone, 2 from 640 px, 3 from 1100 px): one card per app, the whole card the link
(`target=_blank rel=noopener`, no nested `<a>`), logo left (`<img alt="" width=40 height=40>` from
`/static/svc/<file>?v={{ static_v }}`), name + one-line subtitle (`server.SERVICE_SUBTITLES`; unknown ids name only),
the Up/Down WORD beside the dot, and the Uptime Kuma response ms of the first monitor whose name contains the app name
(case-insensitive; a Down card shows its note instead). Logos are vendored in `hub/static/svc/` (dashboard-icons,
Apache-2.0; sources in its README) and mapped in `server.SERVICE_LOGOS`; an id with no logo renders a neutral tile with
its initial letter and the area's line icon, and a test fails if a `MEDIA_APPS` id has neither a logo nor a `NO_LOGO`
entry. `server.GATED_HREFS` overrides a card's LAN href where a gated hostname exists (homepage →
`https://homepage.joeyhome.net` only); the KPI-row Homepage/Portainer link tiles are unchanged.

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
(h=120) into the `/img` disk cache. Everything it touches is cached, so a repeat pass is stats and short reads.
**Library pass** (media-warm-library): after the shelf pass, at most once per 24 h (stamp `warmup_library.stamp` in the meta cache dir, written only after a pass with no failures), the whole library — jellyfin snapshot movies + shows, both profiles, de-duplicated — gets what `/media/item/{jf_id}` renders: poster h=600, backdrop h=1280, top-8 cast photos h=120, plus ratings and the title body through the 6 h disk meta cache (so later passes cost stats). Sequential, 0.3 s pause after each upstream fetch; a cold pass takes ~20 min and logs one summary line (titles, fetched, cached, failures, seconds). `MEDIA_WARMUP=off` disables everything, `MEDIA_WARMUP=shelves` keeps only the shelf pass; without Jellyfin / Jellyseerr keys it skips. Cast portraits and posters are
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
links to the ceremony's latest synced year (the no-year URL) and is hidden when already there.

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
