# Joey HITLIST

The one backlog for Joey. Add an idea as a line in **Inbox**; Claude turns it into a row. Status words: `idea`, `spec`, `ready`, `building`, `review`, `accept`, `shipped`, `parked`.

## Inbox

- (empty — add ideas here, one line each)

## JoeyV2 set-up (Phases 1–6)

Source: `docs/joeyv2/JOEYV2_PLAN.md` §4. Phase 0 (Decide) is done.

### Phase 1 — Repo scaffold

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-001 | Repo `CLAUDE.md` (rules, stack, definition of done) | Docs | S | [x] shipped | Rules live in the repo · PR #38 | — |
| JY-002 | `docs/PROCESS.md`, spec template, PR template | Docs | S | [x] shipped | One loop everyone follows · PR #41 | — |
| JY-003 | `docs/PLAN.md` (vision, areas, open decisions) | Docs | M | [x] shipped | One page for where Joey is going | — |
| JY-004 | `HITLIST.md` seeded + check script | Docs | M | [x] shipped | One backlog for every open item | — |
| JY-005 | `docs/reference/tech-notes.md` (gotchas by area) | Docs | M | [x] shipped | Stop re-learning old traps | — |
| JY-006 | CI fast check on PR and `main` | CI | M | [x] shipped | Catch breakage before merge · PR #37; also fixed a film-page shelves race | — |
| JY-007 | Repo settings + labels | GitHub | S | [x] shipped | Squash only, labels set | — |
| JY-008 | JoeyV2 docs into the repo (`docs/joeyv2/`) | Docs | S | [x] shipped | B. reads the plan on GitHub · PR #39 | — |
| JY-009 | Repo renamed to Joey (`benjiEdwards2/Joey`); update repo-name references | docs/deploy/tv | S | [x] shipped | B. asked; PR #40 | — |

### Phase 2 — Tooling

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-010 | `joey.py worktree new/remove` | Tooling | M | [x] shipped | One worktree per item, safe removal · PR #47 | [spec](docs/specs/JY-010-worktree.md) |
| JY-011 | `joey.py close-out` (merge, deploy, verify) | Tooling | L | [x] shipped | Claude merges and deploys with checks · PR #50 | [spec](docs/specs/JY-011-close-out.md) |
| JY-012 | Preview slot `joey-preview` on the NAS | NAS/deploy | L | [x] shipped | B. accepts on a preview before merge · PR #51; live up/down PASS | [spec](docs/specs/JY-012-preview.md) |
| JY-013 | `scripts/budgets.py` (perf budgets) | Tooling | M | [x] shipped | Speed limits become a check · PR #48; found JY-226, JY-227 | [spec](docs/specs/JY-013-budgets.md) |
| JY-014 | Hands bundle: allow rules, preview hostname, "full permission" | B.'s hands | S | ready | Unblocks push, merge, deploy by Claude · bundle sent to B. 2026-10-23 | — |

### Phase 3 — Clean slate

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-020 | Archive old DECISIONS / HANDOVER / BACKLOG / PLAN files | Housekeeping | S | [x] shipped | 8 files to `archive/` with a banner; both folder CLAUDE.md files are pointers; fresh-agent test answered from HITLIST alone | — |
| JY-021 | Remove merged worktrees (incl. 5 old other-session ones) | Housekeeping | S | ready | 43 of 49 removable with proof (`joey.py worktree list`); waits for B.'s "go" | — |
| JY-022 | Memory notes cut to pointers; add `project_joeyv2` | Housekeeping | S | [x] shipped | lifedashboard, joeytv, joeyv2 notes + index lines point at the repo | — |

### Phase 4 — Pilot

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-030 | Stale "Grouped" toolbar comment in `tv.css` | Joey TV | S | idea | Small chore to prove the loop | — |
| JY-031 | P1b disk forecast on hub card + Discord | Server | L | idea | Forecast reaches the hub and Discord · live | — |

### Phase 5 — Media player

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-049 | Transcoding box: requirements + shortlist | Media player | M | [x] shipped | Research done (`docs/joeyv2/research/JY-049_TRANSCODE_BOX.md`) | — |
| JY-050 | Player spec + questions | Media player | S | idea | Devices, friends or not, what done means | — |
| JY-051 | Player options study (per-device matrix) | Media player | M | idea | Measure what each device plays | — |
| JY-052 | Options page: player screen (PC, phone, TV) | Media player | S | idea | B. picks the look first | — |
| JY-053 | Playback-session endpoints (contract first) | Media player | M | idea | Contract before the players | — |
| JY-054 | Web/phone player | Media player | L | idea | Joey plays the film itself · live | — |
| JY-055 | Progress, resume, watched synced to Jellyfin | Media player | M | idea | Stop on one device, resume on another | — |
| JY-056 | Audio + subtitle track picker | Media player | M | idea | Pick tracks in the player | — |
| JY-057 | TV shell player (new signed release) | Media player | L | idea | Replaces the Jellyfin-app hand-off · live | — |
| JY-058 | Friends' path + security gate | Media player | L | idea | Only if the spec says friends · live | — |
| JY-059 | Move Jellyfin transcoding onto the new box | Media player | L | idea | Needs the box bought · B.'s hands · live | — |

### Phase 6 — Steady state

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-040 | Joey TV W6 close + W7 TV sitting | Joey TV | S | idea | Soak, test-account revoke drill, TV sitting; rename coordinator | — |
| JY-041 | One-week check of the new way of working | Process | S | idea | Messages per item, items shipped, budgets | — |
| JY-042 | Joey TV UI round (umbrella) | Joey TV | L | idea | "Rows and cards way too large"; see JY-186 to JY-197 | — |

## Imported backlog

From the old BACKLOG, handover lists, Joey TV deferred list and TV UI plan, and the server review. "(decision)" means B. must choose first.

### Media

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-100 | Episode pages: "N to watch" → "N left" | Media | S | idea | Wording matches show pages | — |
| JY-101 | "N h this month" uses the old duration format | Media | S | idea | `media_pages.py:175` | — |
| JY-102 | Service page H1 = service name | Media | S | idea | Discover service page says "Discover" | — |
| JY-103 | Georgina's scores in the "both" view | Media | M | parked | Needs her account (decision) | — |
| JY-104 | Episode runtimes from Jellyfin item data | Media | S | idea | Today from recorded plays only | — |
| JY-105 | "Because you rated X 9" shelf | Media | M | parked | Idea from the 10-12 evaluation (decision) | — |
| JY-106 | Read-only "leaving soon" list | Media | M | parked | Idea from the 10-12 evaluation (decision) | — |
| JY-107 | Favourites synced to Jellyfin | Media | M | parked | Idea from the 10-12 evaluation (decision) | — |
| JY-108 | Upgrades: loosen the profile-minimum hint | Media | S | idea | Hint may not show when only some releases fail | — |
| JY-109 | Per-episode Why? on Upgrades | Media | S | idea | Only if ever needed; Why? checks one episode | — |
| JY-110 | Requests page 4K badge lags | Media | S | idea | Shows lag 10 min; films fill on second view | — |
| JY-111 | Old arr profile id shows no Quality line | Media | S | parked | One-off re-save or a fallback (decision) | — |
| JY-112 | Quality chips hide when profile list unreadable | Media | S | parked | Also Seerr's folder/tags options (decision) | — |
| JY-113 | Sonarr-only seasons get no Seasons row | Media | S | idea | Only a "Season N announced" word | — |
| JY-114 | Season state on Recently added + hub progress words | Media | S | idea | Rows have no episode count | — |
| JY-115 | Connector: flag series with 0 Jellyfin episodes at source | Media | S | idea | Hub already treats them as waiting | — |
| JY-116 | Season page head: "Season N" eyebrow + S-switch check | Media | S | idea | Switch did not show in the preview | — |
| JY-117 | Previous / Next cards: verify on a real episode | Media | S | idea | Not seen in the preview | — |
| JY-118 | Guest / crew names linked | Media | M | parked | Plain text now; costs extra reads (decision) | — |
| JY-119 | Off-server shows get episode ratings | Media | S | idea | Warm-up does not prefetch them | — |
| JY-120 | Her view with no list: wording | Media | S | parked | "Nothing left to watch" / "Nothing in progress" (decision) | — |
| JY-121 | Merge play stats into History | Media | S | idea | Nav-tidy leftover | — |
| JY-122 | Manifest shortcut "TV Shows" | Media | S | idea | Nav-tidy leftover | — |
| JY-123 | Naming: Movies / My films / TV show; "Not on server" vs "Not on your server" | Media | S | parked | Left open in the 2026-10-09 tidy review (decision) | — |
| JY-230 | RQ1 Approve / Decline pending Seerr requests on Activity (edit quality + seasons first) | Media | L | spec | Built 2026-10-22 on `joey-rq1-approve` (37032e8, never reviewed); B.'s asks in archived LD DECISIONS; Seerr write · live | — |
| JY-231 | RQ2 Friends pick quality and seasons when requesting (incl. TV mode) | Media | L | spec | Built 2026-10-22 on `joey-rq2-friendpick` (2428063, never reviewed); Seerr write · live | — |
| JY-232 | RQ3 Everyone's watchlist + Request all (sent as B.) | Media | L | spec | Built 2026-10-22 on `joey-rq3-everyone-wl` (dbc18b1, never reviewed); Seerr write · live | — |

### Server

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-130 | P3 One-tap fixes on Attention | Server | M | parked | Restart, re-run, resume, search missing (decision) | — |
| JY-131 | P5 Internet health card | Server | M | parked | Tells slow Joey from a busy internet (decision) | — |
| JY-132 | P6 Backups card | Server | M | parked | No page shows backup age today (decision) | — |
| JY-133 | P7 Service history on the card | Server | S | parked | Kuma 7-day uptime per service (decision) | — |
| JY-134 | P8 What changed since your last visit | Server | S | parked | A sentence Georgina would want (decision) | — |
| JY-135 | P9 Per-person notifications | Server | S | parked | Fewer Discord alerts for Georgina (decision) | — |
| JY-136 | P10 Weekly summary card | Server | M | parked | "Joey this week" (decision) | — |
| JY-137 | Per-container RAM on Server | Server | M | parked | Evaluation feature #9 (decision) | — |
| JY-138 | S.M.A.R.T. into Attention | Server | M | parked | Evaluation feature #10 (decision) | — |
| JY-139 | Gated hostnames per app | Server | S | parked | App links are LAN-only; needs B.'s Cloudflare (decision) | — |
| JY-140 | Health rows say "LAN" | Server | S | idea | Server cards already do | — |
| JY-141 | Quiet-mode cap vs the live qBittorrent cap | Server | S | parked | Quiet 5 Mbps is ~8x tighter than 41 (decision) | — |
| JY-142 | WUD real check interval vs 180-min Stale rule | Server | S | idea | Verify live, then adjust | — |
| JY-143 | Prowlarr indexerstats window | Server | S | idea | If cumulative, amber never clears; verify live | — |
| JY-144 | "Uptime Kuma metrics failed" on Joey /server | Server | S | idea | Pre-existing payload error | — |
| JY-226 | Server page render over budget (p95 52-56 ms, budget 50) | Server | S | idea | `scripts/budgets.py` 2026-10-23: `/a/server` warm p95 52 ms then 56 ms, max ~125 ms; profile it | — |

### Awards

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-150 | Ballot page height at 375 px | Awards | S | parked | 3,166 px vs 2,500 target (decision) | — |
| JY-151 | Long TV pill names | Awards | S | parked | Add a strip rule in `short_name` (decision) | — |
| JY-152 | Awards parser leftovers (5 small) | Awards | M | idea | Song people, table headers, honorary, re-queue, fixture | — |
| JY-153 | Watchlist count line refreshes only on reload | Awards | S | idea | Button swaps itself only | — |
| JY-154 | Awards backlog fill: kick sync, watch posters + coverage | Awards | S | idea | B. runs the sync; dim years may be real gaps | — |

### Weather / Calendar

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-160 | Forecast beside timed events | Calendar | S | parked | Idea from the 10-12 evaluation (decision) | — |

### Joey TV

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-170 | NAS 24/7 (remove power schedule) | Joey TV | S | idea | B. keeps power-off for now; friends cannot watch after 22:00 | — |
| JY-171 | 4K bitrate-cap read | Joey TV | S | idea | W7 step 1: 20 Mbps cap really transcodes | — |
| JY-172 | Georgina's Access token audit, half 2 | Joey TV | S | idea | Needs her to open Joey once; 0 FAIL | — |
| JY-173 | Transcoded stream during a deploy | Joey TV | S | idea | W7 step 2: stream survives swag recreate | — |
| JY-174 | Fire TV paths | Joey TV | S | idea | No device yet; first Fire TV friend | — |
| JY-175 | External uptime monitor | Joey TV | S | idea | Alerts B. on a whole-NAS outage | — |
| JY-176 | 7-day owner follow-up (due 2026-10-26) | Joey TV | S | idea | No phantom household owner since the fix | — |
| JY-177 | Clean-TV "Jellyfin missing" store path | Joey TV | S | idea | W7 step 3: uninstall, reinstall, one sign-in | — |
| JY-178 | Forced update with no "Later" button | Joey TV | S | idea | Needs the next real TV release | — |
| JY-179 | Update tamper test + Settings Back | Joey TV | S | idea | W7 step 4 | — |
| JY-180 | `cache/updates` empty after self-update | Joey TV | S | idea | Optional; debug-to-debug check | — |
| JY-181 | Docs PR: Downloader first-install wording | Joey TV | S | [x] shipped | PR #36 in main (`tv-release.md` + runbook R1-B) | — |
| JY-182 | First friend's TV invite | Joey TV | S | idea | B. said "go friends"; needs B.'s hands | — |
| JY-183 | Revisit the 20 Mbps cap for 2 friend streams | Joey TV | S | idea | Upload is 32.5 Mbps; 1 stream today | — |
| JY-184 | Friend session visible in B.'s live now-playing view | Joey TV | S | idea | Follow-on from the edge work | — |
| JY-185 | Delete old key files left on the Desktop | Joey TV | S | idea | After the password manager holds the key; B.'s hands | — |
| JY-186 | TV UI Gate 1 picks (scale + picks 1–6) | Joey TV | S | idea | B.'s picks block U2 and U6–U10 | — |
| JY-187 | U1 Back memory (focus + scroll) | Joey TV | M | idea | Back never restores focus or scroll | — |
| JY-188 | U2 Hero scrim, 18 px type floor, card scale | Joey TV | M | idea | Rows and cards too large; needs the scale pick | — |
| JY-189 | U3 Posters at 400 px + Tonight layout | Joey TV | M | idea | Blurry posters; Tonight unstyled | — |
| JY-190 | U4 Server fixes (sign-out device, 404, Diary scope) | Joey TV | M | idea | Stale device blocks sign-in · live | — |
| JY-191 | U5 Shell Back + Offline wording (release 1.0.2) | Joey TV | M | idea | Back on sign-in should exit · live | — |
| JY-192 | U6 Series + episodes layout | Joey TV | L | idea | Episode lists unstyled; needs picks | — |
| JY-193 | U7 Shelves + TMDB title page + person page | Joey TV | M | idea | Off-server shelves; needs picks | — |
| JY-194 | U8 Discover search on TV | Joey TV | M | idea | No search on TV today | — |
| JY-195 | U9 Overview + empty states | Joey TV | M | idea | Grey empty boxes; needs picks | — |
| JY-196 | U10 Diary + Awards on TV | Joey TV | M | idea | Diary shows household stats; needs picks | — |
| JY-197 | U11 TV docs sweep | Joey TV | S | idea | Release, README, mockups, handover | — |

### NAS / stack

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-200 | Uptime Kuma 1 → 2 upgrade | NAS | S | idea | Pending since 2026-10-05; B. runs it | — |
| JY-201 | Jellyseerr image frozen → Seerr | NAS | S | idea | Verify the move; Seerr 3.5.0 may mean done | — |
| JY-202 | Other NAS tidy items (WUD, ADM cron, docker.sock, ports) | NAS | M | idea | N-34, N-35, N-43, N-52, N-53; deploy.sh pull retry is JY-206 | — |
| JY-203 | qBittorrent queue limits | NAS | S | idea | Raise to 8 / 12, skip slow torrents | — |
| JY-204 | qBittorrent bound to tun0; gluetun DNS blocklist off | NAS | S | idea | 0 seeds + tracker errors; check against the Proton switch | — |
| JY-205 | Pin gluetun to v3 | NAS | S | idea | Runs the `latest` dev build | — |
| JY-206 | ADM IPv6 DNS entry + deploy.sh pull retry (E0) | NAS | S | idea | `tidyup_t0.sh` already run 2026-10-18; ADM part is B.'s hands | — |
| JY-207 | Cloudflare edge-cache rule (optional) | NAS | S | idea | Cache /static and /img; see `docs/setup.md` | — |
| JY-208 | TailScale container running on the NAS | NAS | S | idea | Flagged only; keep or remove | — |
| JY-209 | Retire Homepage: run `tidyup_t9_network.sh` + Cloudflare hostname cleanup | NAS | M | idea | Unpublish LAN ports 9000/7878/8989/3001/3030/3000; drop the Homepage hostname; B. or Claude in a NAS window | — |
| JY-227 | Full deploy gate over its 10 min budget (15.3 min) | NAS/deploy | M | idea | `scripts/budgets.py` 2026-10-23: last PASS took 918 s; find where the time goes (image build, suite `-n 2`, smoke) | — |
| JY-228 | Preview slot hardening: take the deploy lock during the build, pin `JOEY_FRONT`, reason wording | NAS/deploy | S | idea | JY-012 verifier should-fixes | — |

### Housekeeping

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-210 | WP38 soak test + a real runbook | Housekeeping | M | idea | Docs name a runbook that does not exist | — |
| JY-211 | 7 old Seerr requests still unsent | Housekeeping | S | idea | Remove + re-request, or run the retry script | — |
| JY-212 | Phone checks only B. can do | Housekeeping | S | idea | Back scroll, swipe-back, iOS keyboard, ballot, Follow, Update now, manifest colour | — |
| JY-213 | Live checks: Media rounds | Housekeeping | S | idea | Library grid, 4K request, Why? on Brothers, WAR, Caught up, logos | — |
| JY-214 | Live checks: Server rounds | Housekeeping | S | idea | Quiet tap, first digest, Free space, Updates age, Prowlarr count | — |
| JY-215 | Stale preview entries in `launch.json` | Housekeeping | S | idea | Three point at purged scratch scripts | — |
| JY-216 | Archive the three awards review mockups | Housekeeping | S | idea | Reference only now | — |
| JY-217 | Remove unused `tab_counts()` read in `media_frame()` | Housekeeping | S | idea | Nav-tidy leftover | — |
| JY-224 | Flaky test: `test_media_speed::test_metadata_long_request_state_short` | Tests | S | idea | Fails 3 in 8 under load; doesn't drain the first visit's background read | — |
| JY-225 | Flaky test: `test_runner_history_tail` 2 ms wall-clock limit | Tests | S | idea | Fails 2 in 8 under load; timing assert too tight | — |
| JY-229 | close-out polish: dry run shows docs.1 as DRY before the merge; `tests/scripts/` takes ~7 min serial on Windows (git subprocesses) | Tooling | S | idea | JY-011 first live use, 2026-10-23 | — |

### Parked features

| ID | Title | Area | Size | Status | Why | Spec |
| --- | --- | --- | --- | --- | --- | --- |
| JY-220 | Money / Track E (Westpac import, rules, budget) | Money | L | parked | Hidden since 2026-10-06; resume or drop (decision) | — |
| JY-221 | Re-enable home_assistant / macromates / nas_stats | Connectors | M | parked | Areas hidden; wrong env names in example (decision) | — |
| JY-222 | Posters: TMDB + fanart.tv best-rated pick | Media | M | parked | ThePosterDB has no API; B. said stay as is (decision) | — |
| JY-223 | Georgina's account / her Media view | Media | S | parked | Wiring done; B. creates the account (decision) | — |
