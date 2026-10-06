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

**Shell (2026-10-06, Apex-style).** One admin-dashboard shell for every page: 260 px labelled rail (Home group: Hub ·
Media · Weather; Areas group: the rest — order and grouping come from `config/areas.yaml`, `rail_section`), sticky top bar
with a light/dark theme toggle and the You/Her switcher, Geist type, hairline cards. The hub is a KPI row (one card per
area + Weather), a Next 7 days table, a Weather card and Continue watching shelves; area pages are a KPI row per tile.

**Media** (Jellyfin + the arr-stack) renders inside that shell with its own section nav — Home · Movies · TV Shows ·
Diary · Server (incl. Downloads, live from qBittorrent) · Discover. See `hub/README.md`; feeds in
`docs/connector-contract.md`, env in `docs/setup.md`.

**Server** (2026-10-06, last in the Areas rail) replaces the NAS "Homepage" dashboard natively: `/server` (and `/a/server`)
shows System (CPU, RAM, volumes, uptime), Services (grouped Up/Down), Updates (What's Up Docker), Attention and Counts.
Feeds `media_status`, `system`, `wud` (+ `jellyseerr`/`qbittorrent`/`arr` counts); see `hub/README.md`.

Planning source of truth: `Desktop\Claude\LifeDashboard\{DECISIONS.md, MASTER_PLAN.md}` (not in this repo).
