# life-dashboard

Joey: a private Media · Calendar · Server · Weather dashboard for B. and Georgina, self-hosted on the NAS and
reachable from any device through Cloudflare Tunnel + Access. Five more areas (Food, Money, Desk, House, Car) are
parked: hidden from the navigation, still defined in `config/areas.yaml`. Connector feeds refresh hourly, except the
live Media and Server feeds, which refresh every 2 minutes.

**This repo is PRIVATE and stays private forever** (DECISIONS 2026-08-24).

| Layout | Owns |
|---|---|
| `hub/` | FastAPI + Jinja/HTMX shell |
| `connectors/` | Hourly connectors + the FROZEN envelope schema |
| `deploy/` | Compose, `.env.example`, `deploy.sh` (the only path to production); `deploy/README.md` is the deploy runbook |
| `config/` | Area registry, sample snapshots |
| `stackctl/` | NAS helper behind Server → "Restart + update media stack" (pull + recreate the media-server compose); runs in the media stack, not Joey's — `stackctl/NAS_INSTALL.md` |
| `scripts/` | Dev and maintenance tools: icons, awards sync CLI, profiling, the money pre-commit guard and hooks |
| `docs/` | Setup, connector contract, style guide, hub changelog, Server-updates live check; `docs/mockup/` = the historical Control Surface goldens (superseded 2026-10-06) |
| `tests/` | Cumulative pytest suite — append-only, grows with every WP; test-only deps in `requirements-dev.txt` |

**Look (2026-10-06, MediaHub style guide).** One dark theme, no rail and no theme toggle: a top bar (section pills + the
signed-in Cloudflare Access chip from `hub/identity.py`) with a phone tab bar below 768 px, a header band per page, Geist
type, and every page built from the same few recipes (rows, stats strips, panels, poster cards) in
`hub/static/control-surface.css`; spec in `docs/style-guide.md`, details in `docs/hub-changelog.md` ("Styling"). Areas with
`hidden: true` are parked (no pill, tab or hub tile; the page still serves). The hub is a row of summary tiles (one per
area + Weather), Next 7 days, a weather glimpse and Recently watched posters (Continue watching lives on Media home since 2026-10-08); area pages are a row of tiles per registry
tile (except the weather tile, which renders on the hub and /weather only — 2026-10-08).

**Media** (Jellyfin + the arr-stack) renders inside that shell with its own section nav — Home · Movies · TV Shows ·
Diary · Activity (Live, History, Library, Downloads live from qBittorrent, Requests, Health; renamed from "Server"
2026-10-09, decision 4) · Discover; Movies and TV Shows end with an Awards tab
(2026-10-08: ceremonies from Wikidata / Wikipedia, synced into media.db). See `hub/README.md`; feeds in
`docs/connector-contract.md`, env in `docs/setup.md`.

**Pin Media pages on your phone (2026-10-07).** Inside Media the phone's bottom bar is Media's own six sections
(Home · Movies · TV · Diary · Activity · Discover); tap the Joey logo at the top to go back to the overall hub. To keep a
Media-focused app on your home screen, open any Media page first, then: iOS Safari: Share → Add to Home Screen (it is
named "Joey Media"); Android Chrome: ⋮ menu → Install app / Add to Home screen (long-press the icon for Movies, TV,
Activity and Discover shortcuts). Pages pinned from outside Media install the normal "Joey" app.

**Server** (2026-10-06, the last section) replaces the NAS "Homepage" dashboard natively (Homepage retired 2026-10-09, decision 9): `/server` (and `/a/server`)
shows System (CPU, RAM, volumes, uptime), Last 24 h sparklines, Services (cards grouped Media / Downloads / System), Updates (What's Up Docker: Update now, Update all, and Restart + update media stack through `stackctl/`), Attention and Counts.
Feeds `media_status`, `system`, `uptime_kuma`, `wud` (+ `jellyseerr`/`qbittorrent`/`arr` counts); see `hub/README.md`.

Planning source of truth: `Desktop\Claude\LifeDashboard\{DECISIONS.md, MASTER_PLAN.md}` (not in this repo).
