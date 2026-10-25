# Joey — session summary, Sat 24 Oct 2026 (orchestrator)

## Shipped today (merged, reviewed, HITLIST `[x] shipped`, shipped notes in each spec)
| Item | What | Deployed |
|---|---|---|
| JY-031 | Disk forecast on the hub Server card + one Discord post per episode (your pick 1A 2a 3a 4a) | 3a7270b |
| JY-233 | Hub card titles: solid area-colour chip (your round-2 pick B) | 651ccd6 |
| JY-226 | Server page within budget: cached samples (A+C). `/a/server` p95 52–56 → 27–37 ms | 8ffae27 |
| JY-144 | Uptime Kuma 2.x metrics parsed again (Server page "failed 397/397" gone) | 3b20517 |
| JY-153 | Awards watchlist count refreshes on add/remove | 5ba6859 |
| JY-100, 101, 102, 122 | Media wording: "N left", "18h 42m this month", service-page H1, "TV shows" shortcut | 5ba6859 |
| JY-104 | Episode runtimes from Jellyfin item data | d0a8cad |
| JY-140 | Health rows say "LAN" | d0a8cad |
| JY-113 | Sonarr-only seasons get a Seasons row | 4d54c68 |
| JY-217 | Removed an unused watchlist read on every Media page | 4d54c68 |
| JY-228 | Preview slot holds the deploy lock during its build (live check PASS) | tooling |
| JY-229 | Close-out: dry run DRY not FAIL; review gate dates pushes from GitHub's check-suite and fails closed | tooling |
| JY-227 | Tooling tests faster (tests/scripts 136 → 95 s; full suite 289 → 222 s on the laptop) | tooling |
| JY-239 | Flaky preview-lock tests fixed + fail-safe process check in the preview lock | tooling |
| JY-224, JY-225 | Two flaky tests fixed (0/20 failures under load) | tests |
| JY-050 | Media player spec answered (all recommended) | docs |
| JY-200, JY-201 | Verified already done on the NAS (Kuma 2.5.6; Seerr v3.5.1) | — |
| JY-235 | **Deploy gate 15–26 min → 4.7 min**: the gate's test container runs /tmp in memory (SQLite tests were 5× slower on the NAS disk). Proven by three deploys: 299, 279, 281 s | d94660a / ab71bf7 / 89b4620 / c7c5eed |
| JY-110 | Requests page 4K chip no longer lags after a request | 01028e5 |
| JY-238 | One source for the "LAN" word | tooling |
| JY-236 | Flaky trailer test fixed (a race) | tests |
| JY-241 | joey.py no longer crashes on "≤" in a PR title (this silently stopped one close-out) | c7c5eed |
| JY-234 | Preview lock edge cases (PID reuse guard, atomic pid handover, hold time inside close-out's wait) | tooling |
| JY-152 | Awards parser: song writers, unlinked table headers, winner-less re-pulls, BAFTA fixture | d9284ec (gate 300 s) |
| JY-114 | Season words ("3 to come · next airs 2 Nov") on Continue watching + Recently added cards | d65ad7f (dur 305 s) |
| JY-143 | Prowlarr failed-grab amber now covers the last 7 days (was all-time, so it never cleared) | 2db664b (dur 301 s) |
| JY-115 | A series with no Jellyfin episode count is unknown, not "waiting" (flag half was already done 2026-10-10) | 26b38cb (dur 296 s) |
| JY-117 | Previous / Next episode cards verified live (6 real episodes); no change | docs |
| JY-104 | Shipped notes + HITLIST row (its close-out docs step had been missed) | docs |
| JY-215 | launch.json: every entry points at a path that exists; nothing to remove | — |

Budgets at the end of the day (NAS, n=20): **7 of 7 PASS** — hub page p95 25 ms, item pages 29 ms, Discover 0.99 s cold, joey-hub 97.5 MiB, NAS available 1,673 MB, full gate 4.7 min.

## Still open
- JY-051 (player study): built — inventory (536 items), PC playback table (12 files), study page + test TV app. Needs the sitting.
- JY-187 (Joey TV: Back restores focus + scroll): built (PR #125), in review; needs a TV device run (J3/J4/J5/J8/J9). J8: the sign-out pill is 6 presses from Overview (was 7, target ≤4); recommend accepting 6.
- Parked: JY-237 (flaky test not reproducible in 50+ tries).

## B.'s picks (2026-10-24, 21:28): building now
"JY-108: 1A 2A · JY-116: A · JY-142: 1A, keep 180 · JY-119: A · JY-240: adapt · JY-242: A A · JY-187: accept 6". Then: "Start them now. You will have at least another 2 hours…": deploy tonight after 21:30 (one deploy of main via `pr_close_out.py deploy`; close-out itself refuses outside the window).

**Deployed 22:33 on B.'s "Run it tonight": dfaf871 PASS (dur 438 s), hub/media/swag healthy, smoke ok.** JY-243 (flaky JY-119 tests, a background-read race) is fixed in the tests only, as draft PR #145.
Status 22:10: all six merged (JY-108 ede027a, JY-240 9586cde, JY-116 d3ed5a5, JY-242 f988007, JY-119 3ff5f63, JY-142 6a0ca25). NOT deployed: the classifier blocked the after-window deploy ([Production Deploy]); NAS has 1,574 MB available and the first deploy after JY-240 runs the old deploy.sh copy (2 workers, ~410–520 MB), so the minimum would dip to ~1,050–1,160 MB, below the 1,200 floor. JY-142's docs PR (#144) failed CI on two JY-119 tests that look flaky (main passed on 3ff5f63); JY-243 builder investigating.

Sun 25 Oct morning: JY-243 merging; JY-244 (partof race), JY-189 (TV posters 400 px + Tonight), JY-190 (TV server fixes: sign-out deletes the device, 404 identity, Diary scoped to the friend) building. Sweep 5 PR #146 (rows JY-243..246).

Shipped Sun: JY-243 (tests), JY-189 deployed 81524f3 (gate=-n2 avail=1944, JY-240 live). JY-190 (sign-out deletes the friend's device, 404 identity, friend Diary no longer shows household rows) deploying. JY-191 (TV app 1.0.2: Back on sign-in exits, Offline wording) built + reviewed, HELD: merging to main auto-publishes 1.0.2 (tv.yml release job), so merge in a TV session.

Also shipped Sun: JY-190 deployed 7a4e1da (friend Diary no longer shows household rows; sign-out deletes the friend's device; 404 identity), JY-244 (flaky tests), JY-187 deployed 35c5217 (TV Back memory), JY-247 deployed 5a0c746 (friend summary: own earliest date), JY-194 deployed 62e533d (Discover search on TV). Budgets after the deploys: 5/7 PASS; /a/server p95 66 ms and Discover cold 3.72 s FAIL right after a deploy, re-measured an hour later: worse (server p95 842 ms) with NAS load 7 and IO-bound (qBittorrent busy, Joey containers <1% CPU). A local check shows no code regression (/a/server ~5 ms on 8ffae27 and on main). Re-measure when downloads are quiet. Gate now ~435-480 s (was ~300 s) since the six-pick batch; tmpfs still in place, still within 10 min.

TV UI round DONE (Sun 25 Oct, all live): JY-188 density B + compact chrome (37bac74), JY-248 Joey Media = Home, no Overview pill (42f9dd8), JY-192 series/episodes + Rate button (49096ca), JY-195 Home shelves + empty states (ac96013), JY-196 Awards TV view + slim Diary (b0cec29), JY-193 on-server shelves + TMDB request page + person page (417ef98), JY-197 docs (afef649). Grouped TV checklist (40 checks) at the top of JoeyTV\TV_UI_PLAN.md.

TV session ran Sun 25 Oct (B.'s go): JY-191 merged 18c0d86, Joey Media 1.0.2 published (tv-2026102501). 40 checks: 27 PASS, 7 FAIL, 3 DEFERRED (log JoeyTV\scripts\logs\tv_session_1025.log, shots review\tv-ui-2026-10-25\). Fails being fixed in JY-250 (404 centring, Tonight safe area, season eyebrow 12 px, Back from episode, Diary month row) + JY-249 flake; JY-251 investigates a friend seeing household "Following George Kay".

After fixes (JY-251 e3f5cc3: friends no longer see household "Following"; JY-250 d0c790e: 404 centred, Tonight in safe area, season eyebrow 18 px, Diary row, JY-249 flake) the re-check passed 7/9/13/28/36 + no "Following". #15 passes with real remote keys (Home → episode → Back → series → Back → Home); the earlier fails came from the test script's own navigation. TV testing PAUSED at B.'s request; app left on Home. Still open from the session: #14 (needs a friend Jellyfin login on the TV), #16 "Rated 8" and #18 "Requested" (would write real data), release app update to 1.0.2 (B. accepts the update prompt), back (e) screenshots for B.

## Needs you (B.)
**One TV session** (when the TV is free, ~20 min): merge + release JY-191 (1.0.2), then the grouped TV checks: JY-187 J3/J4/J5/J8/J9, JY-189 poster probe, JY-190 signin --allow-write, JY-191 back (a)–(f).
**TV Gate 1 (JY-186), seven picks on the real TV mockups: https://claude.ai/artifact/MDfJtRJHKzKbANySVkP5xE**. Unblocks U2 and U6–U10.
**All seven picks on one page (four device views, reply line builds itself): https://claude.ai/artifact/4nBx4CNMeJuykFqRJGQrCL** — JY-108, JY-116, JY-142, JY-119, JY-240, JY-242, JY-187 (J8).
0b. **JY-242** (awards): honorary awards (A recommended: winners-only under "More", counted on person pages) and re-pulling ~300 old years with the fixed parser (A recommended) — spec `docs/specs/JY-242-awards-honorary-and-repull.md`.
0. **JY-240** (pre-gate memory check, built + 2 reviews PASS): when memory is low, **adapt** (recommended: `-n 1` between ~1,460 and ~1,720 MB available — measured 243 MB drop, 5.8 min; skip only below ~1,460) or **skip** below 1,650 MB (would have skipped several of today's deploys).
0c. **JY-119** (episode ratings for off-server shows): the warm-up prefetches no episode ratings today, so pick **A** (recommended: off-server pages fill ratings like on-server ones, after the first view), B (A + a capped warm-up prefetch, M) or C (warm-up for on-server shows only). Spec `docs/specs/JY-119-offserver-episode-ratings.md` (PR #124).
0d. **JY-108** (Upgrades hint): today it shows only when the profile minimum rejects *every* release. Pick 1A (recommended: also when it rejects the first rejected release or at least half of them) / 1B (any) / 1C (leave it), and 2A (recommended wording "rejects N of M releases"). Spec `docs/specs/JY-108-upgrades-hint-loosen.md` (PR #128).
0e. **JY-142** (Updates tile wording): WUD checks once a day at 08:00; the hub's "checked 2h ago" is really its own hourly poll, and the 180-min Stale rule is right. Pick 1A (recommended: say "refreshed 2h ago") / 1B keep "checked" / 1C show WUD's check time. Spec `docs/specs/JY-142-*.md` (PR #132).
0f. **JY-116** (season page head): the S-switch works live; the season page has no "Season N" line at all. Pick A (recommended: "Season 2 of 4") / B ("Season 2 · 12 episodes") / C nothing. Spec on PR #134.
1. **JY-014**: Cloudflare `preview` hostname on your existing Joey Access app (+ allow rules, lid action). Blocks the JY-051 sitting and the public preview.
2. **JY-051**: your phone (Android or iPhone); then one 30-minute sitting.
3. Optional cleanup: old `uptime-kuma:1` and `fallenbagel/jellyseerr` images still on the NAS disk.
4. Reminder: request-feature branches JY-230–232 parked until you say.

## Notes
- Two slips, both caught: one shipped-notes step needed a HITLIST row I had missed (JY-233); one deadlock in my close-out queue, fixed by merging the queues.
- The laptop's git credential helper times out when several builders run tests at once; recorded in the tech notes.
