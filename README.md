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
| `docs/` | Mockup (golden visual reference), contracts, runbook |
| `tests/` | Cumulative pytest suite — append-only, grows with every WP |

Planning source of truth: `Desktop\Claude\LifeDashboard\{DECISIONS.md, MASTER_PLAN.md}` (not in this repo).
