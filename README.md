# life-dashboard

Private, self-hosted life OS for B. and Georgina. One dashboard surface over notes, files,
apps, tasks and budget, refreshing itself hourly, reachable from any device through
Cloudflare Tunnel + Access.

**This repo is PRIVATE and stays private forever** (DECISIONS 2026-08-24).

| Layout | Owns |
|---|---|
| `hub/` | FastAPI + Jinja/HTMX shell |
| `connectors/` | Hourly connectors + the FROZEN envelope schema |
| `deploy/` | Compose, `.env.example`, `deploy.sh` (the only path to production) |
| `config/` | Area registry, sample snapshots |
| `docs/` | Contracts, runbook; `docs/mockup/` = the historical Control Surface goldens (superseded 2026-10-06) |
| `tests/` | Cumulative pytest suite — append-only, grows with every WP |

**Look (2026-10-06, MediaHub style guide).** One dark theme, no rail and no theme toggle: a top bar (section pills + the
signed-in Cloudflare Access chip from `hub/identity.py`) with a phone tab bar below 768 px, a header band per page, Geist
type, and every page built from the same few recipes (rows, stats strips, panels, poster cards) in
`hub/static/control-surface.css`; spec in `docs/style-guide.md`, details in `hub/README.md` ("Styling"). Areas with
`hidden: true` are parked (no pill, tab or hub tile; the page still serves). The hub is a row of summary tiles (one per
area + Weather), Next 7 days, a weather glimpse and Continue watching posters; area pages are a row of tiles per registry
tile (except the weather tile, which renders on the hub and /weather only — 2026-10-08).

**Media** (Jellyfin + the arr-stack) renders inside that shell with its own section nav — Home · Movies · TV Shows ·
Diary · Server (incl. Downloads, live from qBittorrent) · Discover. See `hub/README.md`; feeds in
`docs/connector-contract.md`, env in `docs/setup.md`.

**Pin Media pages on your phone (2026-10-07).** Inside Media the phone's bottom bar is Media's own six sections
(Home · Movies · TV · Diary · Server · Discover); tap the Joey logo at the top to go back to the overall hub. To keep a
Media-focused app on your home screen, open any Media page first, then: iOS Safari: Share → Add to Home Screen (it is
named "Joey Media"); Android Chrome: ⋮ menu → Install app / Add to Home screen (long-press the icon for Movies, TV,
Server and Discover shortcuts). Pages pinned from outside Media install the normal "Joey" app.

**Server** (2026-10-06, the last section) replaces the NAS "Homepage" dashboard natively: `/server` (and `/a/server`)
shows System (CPU, RAM, volumes, uptime), Last 24 h sparklines, Services (grouped Up/Down), Updates (What's Up Docker), Attention and Counts.
Feeds `media_status`, `system`, `uptime_kuma`, `wud` (+ `jellyseerr`/`qbittorrent`/`arr` counts); see `hub/README.md`.

Planning source of truth: `Desktop\Claude\LifeDashboard\{DECISIONS.md, MASTER_PLAN.md}` (not in this repo).
