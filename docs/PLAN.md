# Joey: the plan (why)

Read order: `CLAUDE.md` (rules), `HITLIST.md` (what), `docs/PROCESS.md` (how), this file (why).
The orchestrator edits this file. Builders propose changes in the PR.
Sources: `docs/joeyv2/JOEYV2_PLAN.md`, `docs/joeyv2/DECISIONS.md`, `config/areas.yaml`, and the archived Life Dashboard plan and decisions (local, not in this repo).

## Vision

Joey is a private dashboard for two people, B. and Georgina. It shows Media, Calendar, Weather and Server in one place.
It replaces the NAS Homepage dashboard (retired 2026-10-09) and the habit of opening each media app by hand.
It runs on their own NAS, behind Cloudflare Tunnel + Access, with a two-email allowlist.
The repo is private and stays private (decided 2026-08-24).
No personal data leaves the NAS, with these named exceptions (the numbered exceptions in `docs/connector-contract.md` are the source):
- Cloudflare carries the traffic and the sign-in for Joey itself.
- `media.db` has one encrypted off-site copy: `deploy/media_offsite.sh` sends an age-encrypted dump to a private GitHub repo (since 2026-10-20).
  The volume itself has no off-box copy (see Risks).
- Outbound reads: Open-Meteo (weather), Wikidata and Wikipedia (awards), OMDb (ratings), a Google ICS feed (Calendar), and TMDB metadata through Seerr.
- TMDB poster images are fetched server-side from `image.tmdb.org` (no key, `hub/images.py`).
- The Windy radar embed on `/weather`: the browser loads `embed.windy.com`.
- The YouTube trailer iframe (`youtube-nocookie.com`): the browser loads it only after the user presses Trailer.
- The Discord webhook posts Follow adds, Server alerts and the Server digest.
- The Jellyfin public edge serves video to friends' TVs, only for people B. invites.

Joey TV (`tv/`) is its Android TV shell. B. approves every spec, picks every option and accepts every build.

## Areas

Source: `config/areas.yaml`. Eight areas, hard cap nine. `hidden: true` means no tab or hub card, but the page still serves.
Weather is a tile in Calendar that renders on the hub and `/weather` only. It is not its own area.

| Area | State | Feeds |
|---|---|---|
| Media | live | `jellyfin`, `media_status`, `arr`, `qbittorrent`, `jellyseerr` |
| Calendar | live | `gcal`, `open_meteo` (weather tile) |
| Server | live | `media_status`, `system`, `uptime_kuma`, `wud` |
| Food (id `kitchen`) | hidden | `macromates` (not connected) |
| Money | hidden | `money` (not connected; JY-220) |
| Desk | hidden | `nas_stats` (not connected) |
| House | hidden | `home_assistant` (not connected) |
| Car | hidden | `home_assistant` (not connected) |

Awards, Diary, Watchlist and Follow are parts of Media, not areas. Re-enabling a hidden area is JY-221.

## Architecture in brief

- **Host.** One Asustor NAS runs everything as Docker Compose (`deploy/`): the hub, the connectors, the tunnel, the edge and the media stack.
- **Connectors to hub.** Connectors (`connectors/`) write JSON snapshots in a frozen envelope. The hub (FastAPI, Jinja, HTMX) only reads them.
  Live feeds refresh every 2 minutes, the rest hourly. Feeds are listed in `docs/connector-contract.md`.
- **State.** Everything the hub writes goes to one SQLite file, `media.db`: ratings, diary, watchlist, follows, awards. The hub backs it up daily and monthly.
- **Areas are config.** `config/areas.yaml` defines them. No area names appear in hub code.
- **Access.** Cloudflare Tunnel to the hub, and one Cloudflare Access app with a two-email allowlist. The signed-in user comes from the Access header.
- **Joey TV edge.** Friends' TVs reach Jellyfin through a separate nginx (SWAG) on router port 8443, not through the tunnel and not through the hub.
  The edge is live: the Joey TV security gate passed on 2026-10-22 and the production gate on 2026-10-23.
  Video never goes through the Cloudflare tunnel (terms grey area). Details: `docs/public-edge.md`.
- **Deploy.** Only `deploy/deploy.sh`, between 07:00 and 21:30. It runs the full suite in a test image and rolls back a failed deploy.
- **Joey TV app.** A Kotlin WebView shell, built only in GitHub Actions (`tv/README.md`).
- Module map: `hub/README.md`. Deploy runbook: `deploy/README.md`.

## Phases

JoeyV2 keeps the app and changes how work gets done: one item, one spec, one branch, one PR, one agent.
Full item tables are in `docs/joeyv2/JOEYV2_PLAN.md` section 4. Status is in `HITLIST.md`.

0. **Decide.** Done 2026-10-23. All nine plan questions answered.
1. **Repo scaffold.** `CLAUDE.md`, `PROCESS.md`, this plan, `HITLIST.md`, tech notes, CI, repo settings (JY-001 to JY-009).
2. **Tooling.** `joey.py` worktree and close-out, a preview slot on the NAS, performance budgets, the hands bundle (JY-010 to JY-014).
3. **Clean slate.** Archive the old decision and handover files, remove old worktrees, cut memory to pointers (JY-020 to JY-022).
4. **Pilot.** Two real items through the whole loop: a chore and a screen item (JY-030, JY-031).
5. **Media player.** Joey plays the film itself on web, phone and TV, plus the transcoding box (JY-049 to JY-059).
6. **Steady state.** Joey TV close and sitting, a one-week check of the new way, and the TV UI round (JY-040 to JY-042).

The imported backlog (JY-100 to JY-223) sits in `HITLIST.md` under its own headings.

## Open decisions

Every HITLIST row marked "(decision)". B. chooses; each is `parked` until then.

- JY-103 Georgina's scores in the "both" view
- JY-105 "Because you rated X 9" shelf
- JY-106 Read-only "leaving soon" list
- JY-107 Favourites synced to Jellyfin
- JY-111 Old arr profile id shows no Quality line
- JY-112 Quality chips hide when profile list unreadable
- JY-118 Guest / crew names linked
- JY-120 Her view with no list: wording
- JY-123 Naming: Movies / My films / TV show; "Not on server" vs "Not on your server"
- JY-130 P3 One-tap fixes on Attention
- JY-131 P5 Internet health card
- JY-132 P6 Backups card
- JY-133 P7 Service history on the card
- JY-134 P8 What changed since your last visit
- JY-135 P9 Per-person notifications
- JY-136 P10 Weekly summary card
- JY-137 Per-container RAM on Server
- JY-138 S.M.A.R.T. into Attention
- JY-139 Gated hostnames per app
- JY-141 Quiet-mode cap vs the live qBittorrent cap
- JY-150 Ballot page height at 375 px
- JY-151 Long TV pill names
- JY-160 Forecast beside timed events
- JY-220 Money / Track E (Westpac import, rules, budget)
- JY-221 Re-enable home_assistant / macromates / nas_stats
- JY-222 Posters: TMDB + fanart.tv best-rated pick
- JY-223 Georgina's account / her Media view

## Risks

| Risk | What it means | What we do |
|---|---|---|
| NAS RAM | The NAS has 3,694 MB (`free -m`, 2026-10-23). A preview plus a deploy is close to the line. | Available RAM stays at or above 1,200 MB during any deploy or preview. One preview slot only. |
| NAS off 22:00 to 07:00 | B. chose this for noise. Nothing runs overnight, and friends cannot watch after 22:00. | Deploy only 07:00 to 21:30. Schedule nothing in the window. JY-170 covers removing it. |
| RAID0, no off-box copy of the volume | A disk failure loses the volume. B. accepts re-downloading media. | `media.db` is backed up inside the hub, and an encrypted copy goes off site (`deploy/media_offsite.sh`, 2026-10-20). Nothing else has an off-box copy. |
| One NAS | Joey, the media stack, the tunnel and the edge share one host. One failure takes all of it down. | Auto-rollback on deploy. JY-175 adds an outside monitor. |
| Work laptop as host | Claude sessions run on an org-managed laptop that stays on 24/7 for now. Org policy blocks Remote Control, so phone control is paused. | A cheap dedicated PC takes over later (JY-049, JY-059). No cloud sessions (Q9). |
| GitHub free plan | A private repo gets no branch protection and no auto-merge. Actions has 2,000 free minutes a month. | `joey.py close-out` refuses a merge without green CI, a review and B.'s accept (JY-011). CI runs on PR and `main` only. |
