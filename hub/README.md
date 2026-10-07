# hub

FastAPI + Jinja/HTMX dashboard shell. Areas are config, not code — see `config/areas.yaml` (WP16).

**Shell (MediaHub guide, Phase 2 of 4, 2026-10-06).** `templates/base.html` is the one frame (guide §5). Sections =
Hub, any area with `rail_section: home`, Weather, then the other visible areas, in `areas.yaml` order (today: Hub ·
Media · Weather · Calendar · Server). Top bar `.topbar` (sticky from 768 px, 56 px row, 72rem wide): the kangaroo mark
`static/brand-joey.jpg` + "Joey" linking to `/`, one pill per section (`.toplinks`, shown from 768 px), and at the right
the user chip from `identity.py` (the Access header decides the owner view, `?owner_view=` only works locally). Phone
tab bar `.tabbar` (< 768 px): five slots, icon over label; with more than five sections the fifth slot becomes "More", a
`<details class="more">` sheet listing the rest. Areas with `hidden: true` are parked: no pill, phone tab or hub card,
page still serves. Page frame `main.page`: centred, 72rem, bottom padding clears the tab bar. Page header: the
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
glyph + condition word); `_shelf.html` Continue watching on Media's `.carousel` of `.card-poster`s. *Area pages*
(`area.html`, also hidden areas): tiles, the Calendar upcoming rows + weather glimpse, and for areas reading the
jellyfin/media_status snapshots Media-style sections (`.row`s, `.row-score`, `.gold-glow-sm`). *Server* (`server.html`,
`server_update.html`): System = `.stats` strip (volumes carry a `.bar`), Last 24 h = `.spark-band` panel (`.spark-*`,
stroke `--primary`), Services = `.sec` groups of `.row` links with `.st-up/.st-down` words, `.row.is-down` and the 20 px
`.appicon` slot, Monitors/Updates/Attention rows (Update now `.btn-primary .btn-sm`, Ignore `.btn-ghost .btn-sm`, the
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
`.facts-line`, credits with IMDb/TMDB/Letterboxd `.linkchip`s, emerald status line, one `.btn-white` primary plus 36 px
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

**Media library pages (F3, 2026-10-06).** `/media/movies`, `/media/movies/tonight`, `/media/tv`, `/media/tv/tonight` and `/media/years?kind=movie|tv`, built from the jellyfin `movies`/`shows` arrays by `media_library.py` (`film_rows`, `show_rows`, `deal_tonight`); "New this week" uses the arr `at` field. Absent arrays render "Library list not available yet".

**Downloads (2026-10-06).** `/media/downloads` (Server sub-tab after Library) lists the live qBittorrent torrents. `media_downloads.py` joins the arr queue to qBittorrent (`download_id` == torrent hash) for live progress on the Home Downloading shelf, Library "This week" badges and title-page badges; a Sonarr season pack (one queue row per episode, one `download_id`) collapses to one row, e.g. "Show · S01 · 13 episodes".

**Server area (WP-S1, 2026-10-06).** Registry area `server` (`layout: server`, last section in the top bar and tab bar,
icon `server`) renders `server.html` at `/server` and `/a/server` — not to be confused with the Media "Server" sub-section.
`server.py` (pure) builds, top to bottom: KPI row per tile (Services = `media_status`, System = `system`, Monitors = `uptime_kuma`,
Updates = `wud`, Homepage + Portainer links), System band (CPU, RAM free/total, uptime, "Last sweep N min ago" from
`_runner.json` `ran_at` with "stale" past 90 min, each volume with a hairline bar and % used),
Services grouped Media / Downloads / System by app id (unknown ids → System; Up/Down word beside the dot), Monitors
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

Poster sizes: list rows use `.poster.sm` (56 px tall); shelf cards are 144 px wide (`.shelf-item`, `.shelf-cell`), both in
`static/control-surface.css`.
