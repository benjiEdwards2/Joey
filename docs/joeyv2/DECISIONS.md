# JoeyV2 — decisions (append-only, dated)

## 2026-10-23 — plan questions answered (B.: "Go with all recommendations")
- Q1 A: JoeyV2 = the same Joey app and repo (`benjiEdwards2/life-dashboard`), run with the MediaHub operating model. No rebuild.
- Q2 A: ideas and accepts come through chat with the orchestrator, plus private Claude artifact pages for options and accept lists. GitHub mobile is not part of the flow.
- Q3 A: merge rules are enforced by `scripts/joey.py close-out` (green CI + review + B.'s accept). No GitHub Pro, no branch protection.
- Q4 A: Claude does every push, merge and deploy. B. adds the allow rules to `Documents\Claude\.claude\settings.local.json` and says "full permission" once in the orchestrator session.
- Q5 A: squash merge only, one commit per item.
- Q6 A: the performance budgets in JOEYV2_PLAN.md §3 are acceptance criteria.
- Q7 A: one `joey-preview` hub on the NAS at `preview.joeyhome.net` (Access-gated, live data read-only, sample data for connector changes).
- Q8 A: Joey TV's remaining work (W6 close, W7 TV sitting) moves into HITLIST as JY items after Phase 3; the W7 sitting stays one hands bundle.
- Q9 A: the orchestrator works while a laptop session is open; no cloud sessions.

## 2026-10-23 — input cadence
- B.: "I am okay with things not being in batches." B.'s input can come at any time. Batched morning/evening pages are optional, not a rule. Still kept: questions grouped per item at the end of its spec, the accept checklist walked in one go, and the deploy window 07:00–21:30 (NAS off 22:00–07:00).
- B. wants the work cut the MediaHub way: small items inside each phase, each one spec, one branch, one PR, one agent, sized, with its review tier. JOEYV2_PLAN.md §4 rewritten as JY-### items.

## 2026-10-23 — Media player phase (B.: "After pilot is fine")
- Joey gets its own media player on every device (web, phone, TV), replacing the hand-off to the Jellyfin app. No rush: it comes after the Pilot, as Phase 5. Steady state becomes Phase 6.
- Phase 3 (Clean slate) runs alongside Phase 2 (Tooling).
- B. wants the TV player options investigated before choosing; he has seen ffmpeg, Jellyfin and ExoPlayer → JY-051.
- B. will buy a computer to raise transcoding performance → JY-049 (requirements + shortlist before he buys) and JY-059 (move Jellyfin transcoding onto it).

## 2026-10-23 — interim hosting (B., after JY-049)
- The laptop stays powered on and running 24/7 for now. A cheap, value-focused PC will take over later (JY-049 budget tier: N150 class, Linux). An internet upgrade waits for the next home; current upload (32.5 Mbps) stays.
- Phone access: B. asked what Remote Control is. Recommended "Remote Control now, runner on the box later". Awaiting B.'s confirmation.
- Remote Control: B. confirmed it, but turning it on failed with "Remote Control is disabled by your organization's policy" (the Interroll org account). **Paused** at B.'s request: this session's switch is off, and the new-session default is back to Off. B. will set Remote Control up on his own desktop later, at a time of his choosing.
- B. needs to see everything on GitHub: the full JoeyV2 upload and recent edits. → JY-008 moves the JoeyV2 plan, decisions and research into the repo (`docs/joeyv2/`). JY-002 and JY-004 (HITLIST) are pulled forward. From then on, the repo copy is the one that gets edited.

## 2026-10-23 — Joey TV UI round added (B.: "add this into the joeyv2 addition … as a listed item to complete")
- JY-042 added to JOEYV2_PLAN.md Phase 5: the Joey TV UI round (TV_UI_PLAN.md U1–U11, incl. the row + card scale change from `JoeyTV\mockups\tv-v2\08-density.html`). JY-004's seed sources now name TV_UI_PLAN.md, so each U-item gets its own JY-1xx row. Blocked on B.'s Gate 1 picks (scale B/C + picks 1–6). Source session: "Joey TV — TV UI review".

## 2026-10-24 — JY-050 media player answers (B.: "Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance.")
- All recommended answers in `docs/specs/JY-050-player-spec.md`: devices PC browser → phone → household TCL TV (Joey TV shell); household only, friends after JY-057; direct play → remux → transcode, 20 Mbps remote cap for friend accounts; no offline downloads in v1; subtitle/audio defaults follow each Jellyfin user; Jellyfin is the single resume record (JY-055); TV shell gets a new signed release after JY-042 with the Jellyfin app kept one release as fallback; success = start within 5 s LAN / 10 s remote, cross-device resume, a week without the Jellyfin app.


## 2026-10-29 — Token rules (B.: "Apply all six token recommendations, including the CLAUDE.md rules.")
- Measured on the orchestrator session: median context 535k tokens per turn, orchestrator 37 % of spend, GitHub traffic ~2 % of tool output. Six rules added to `CLAUDE.md` (handover at ~200k, no images in the orchestrator, short outputs, builders ≤150 turns, one close-out script per item, reviewers read diffs). This week: after JY-259 phases 3-4, Sonnet review and doc work only until the Sunday reset.

## 2026-10-29 — GitHub budget G1-G4 (B.: "Yes, apply G1-G4")
- From `review-joeyv2-evaluation-2026-10-29.md` (project folder): 152 of the last 400 CI runs re-tested the squash commit on `main`; 118 of 271 PRs were status or docs PRs; 12 worktrees and 128 remote branches were left from merged PRs. `ci.yml` now runs only on ready (non-draft) PRs and skips docs-only changes; no run on push to `main`. Merged remote branches deleted and merged worktrees removed with proof (`scripts/ci_budget_prune_1029.py` in the project folder). Not applied (needs B.'s wording on rule 11): scripts committing docs-only sweeps and shipped notes straight to `main`.

## 2026-10-29 — Rule 11 exception (B.: "Yes, allow it")
- The sweep and close-out scripts may commit docs-only changes (`*.md`, `docs/`, `HITLIST.md`) straight to `main`, one batch per day, no PR and no CI. Code changes keep the PR + review + accept path. Script change (joey.py close-out steps 3-4, sweep_run.sh) is queued for the orchestrator as a HITLIST row; this entry is the first such commit.

## 2026-11-02 — Sweep 20+21 (B.: "Park both"; "Yes, all fine")
- JY-051 (player options study) and JY-211 (7 old Seerr requests) → `parked`. B. 2026-11-02: "Park both".
- JY-259 phase 4 (TV player 1.0.4) and the JY-270 TV pages (Awards, Discover search, filters, title extras) checked by B. on the TCL 2026-11-02: "Yes, all fine". JY-259 stays shipped; JY-270 keeps building (Upcoming shelves + streaming browse left).
- Live: 1aaac4c (deploy PASS 2026-11-02 09:50 Melbourne). Sweep 20's PR was never opened; its rows land in this sweep as one docs-only commit to main (rule 11 exception).
- B.'s worst-of-session 2026-11-02: the merge lines (the classifier blocks Claude's `gh pr merge`; B. pastes one line per round). Candidate fixes to try next: a settings allow rule for `gh pr merge`, or `joey.py close-out` carrying B.'s quoted accept. Filed as JY-271.

## 2026-11-03 — Sweep 23 (B.: "Movies round 2 I like the option A."; "Run it yourself please")
- JY-280 round 2 options page: option A picked (right-column scores, owner-only File drawer). Spec `docs/specs/JY-280-movie-page-round2.md` covers JY-280/281/283/284/285; JY-286 stays its own spec.
- Review resolutions (standing rule): desktop shots at 2560×1440 plus an ultrawide (3440×1440 assumed until B. confirms), phone 390, iPad 1024, TV rendered for a 4K panel ("the TV is at 3k", B.; exact device pixels to confirm). Replaces the 1440-wide desktop and 1920×1080 TV shots.
- Merge + deploy: B. 2026-11-03 "stop asking to merge and deploy. Run it yourself please." Claude ran `gh pr merge` 292/293 and `deploy.sh` this morning and both went through (no classifier denial this time). Claude runs them first from now and only hands B. a paste when denied. JY-271 stays open until two more rounds pass.
- Overview (JY-277): B. unsure between A and B; JY-306 (fixed preview ports) is pulled forward so A and B run side by side on two ports for him to compare live.
- New row JY-307: full TV UI overhaul (options page first).
- Live 861ebd5 (JY-270 final phase); JY-270 shipped.

## 2026-11-03 evening — Sweep 24 (B.: "accept all, except 293 does not need 'everything else")
- Seven PRs merged on that accept: #297 JY-272, #299 JY-302, #300 JY-282+288, #302 JY-289+290 (merge conflict with #300 in `test_media_episodes.py` resolved on the branch, suite green), #303 JY-298, #301 JY-280 P2+286, #298 JY-293 (after the label fix). One deploy, live bf94e98.
- JY-293: group labels plain, no "Everything else · " prefix (B.).
- JY-307 TV UI: option B, streaming-app layout (B.: "Prefer option B. Lets try it with that for a little bit."). Phase 1 = A/B base tokens first, as the options page phasing says. B. also: "TV option still looks odd. the scaling seems odd." — open: which shots he means (the TV shots are 1920×1080 frames with 1rem = 32 px, so text looks large when viewed on a monitor).
- JY-308 pulled forward (B.: "ensure that the desktop takes up more horizontal room as well").
- Review pages: every shot opens full size on click (B.: "allow me to go click into photos").
- B. working rule for tonight: "run as many hitlist items as you can before bedtime" (NAS off ~22:45 tonight; deploy window still ends 21:30).

## 2026-11-04 morning - Sweep 24 answers (review-page db, B. 2026-11-03 21:50-21:52 UTC)
- Accept: JY-308 #305, JY-299 #307, JY-281 #308, JY-307 P1 #306 + P2 #311, JY-279 #310. Merged in that order (310 needed a main merge: import list). Live pending.
- JY-301 #309: Change - "Ensure pause and play buttons are icons and placed in line with things. Not underneath in their own pill boxes. REduce aspace and row heights by doing this."
- TV scale (q-b): "Seems too zoomed in. PLease zoom it out and zoom it out by about 25% please." -> html.tv rem 32px -> 24px at 1080p (JY-307 P2b).
- JY-299 (q-c): "Correct. I should see everyone. They should only see their own."
- Open picks (q-d): "Will check. Please show me artifcat for that or accept as default." -> Overview A/B shots page built; person page B, Live A, TV shows episode-first stand as defaults until B. says otherwise.
- Assumptions (q-e) confirmed: ultrawide 3440x1440, TV 3840x2160, Live and Health hidden from friends.
- Review pages now save answers to the artifact db (collection `answers`); the first sweep-24 answers (plain textareas) were lost and B. re-entered them.

## 2026-11-04 late morning - Sweep 25 answers (review-page db)
- JY-301 r2 #309: "Accept"; JY-307 P2b TV 25%% smaller #312: "Accept", "I like the after." Both merged; deploy pending (NAS unreachable from the work network).
- Overview: B. "Overview B." -> JY-277 option B building on main (JY-276 + JY-278 included).
- Person page, Live page, TV shows plan: B. "Show me again." -> JY-291, JY-296 pages republished with saved decision boxes; JY-287 plan published as a page with a Plan 1/2/3 box.

## 2026-11-04 midday - Option picks (chat + plan-page db)
- JY-291 person page: B. "Person Page. Prefer A." -> build A.
- JY-296/297 Live: B. "Live page A. But you need to fix it as it looks to be going off the page to the right." -> build A; the overflow is in the mock-up (1024/390: non-shrinking Up next tiles in a bare 1fr column); real build AC: no horizontal overflow at 1024 and 390.
- JY-287 TV shows: Plan 2 (episode-first), "Fold in with plan 3 then as well after." Answers: Q8 mock-up first; new-episode tag by default; show-hero Continue lead: mock-up first; scores column + File drawer yes; chips only (no this/all seasons view); TV waits for JY-307. Split into JY-314 (2.1), JY-315 (2.2), JY-316 (2.3), JY-317 (2.5); JY-278 remains = the tag only.

## 2026-11-04 afternoon - Sweep 26 answers + merges (chat: "Sweep 26 complete. 314 and 315 complete. Overview B please.")
- Merged #313 (JY-277 Overview B), #314 (JY-291 person A), #315 (JY-296/297 Live A) in that order; main 2364821. Live pending (NAS unreachable from the work network).
- JY-291 Qs: TMDB key "Yes." -> JY-320 (B. pastes it on the NAS). No-backdrop case -> JY-321 (prefer an on-server credit, else nothing).
- JY-296 Qs: Health tab "REmove it." -> JY-319. Connector change for time left/device/4K: "Not neccessary yet."
- JY-314 (progress hero): B. picked A = keep Play as is -> parked. JY-315 (episode page): A + an episode carousel left/right under the hero.
- JY-319 #316 merged 2026-11-04 on B.'s standing "REmove it." (reviewer PASS). Live pending.

## 2026-11-04 afternoon - Upgrades and search
- B. 2026-11-04: "Complete all for upgrades adn searches. Recomplete 109. If you have any questions. Ensure you ask me. I don't need to wait for thoes." -> umbrella JY-322; JY-109 re-opened into the JY-275 build; JY-275 built on the spec defaults (A/A/A) while the questions go to B.; JY-300 options page first.
- 2026-11-04 B. on JY-275: default after-check flag; clicking Upgrade grabs ("If accepted, it should then try grab the section."); Upgrade button ONLY on the Requests/Downloads page; Downloads Upgrades list goes once merged. JY-109 placement: "Show me a mock up." JY-300: "A" (one page with a filter), friends keep requests-only. Standing merge + deploy authority: "Check my answers for 300 and you can merge everything and run when you can."
- B. 2026-11-04: "Happy to deploy once 109, 275, and 300 are ready. Then begin working on other hitlist items please once you are completing it." -> deploy gate = JY-109 + JY-275 + JY-300 merged; next items started: JY-304/305 options, JY-321 build.
- 2026-11-04 B.: JY-109 "A" (fold-out under the row); JY-304 "C" on "Every carousel."; JY-305 "B" cinema. Process feedback: review pages need a copy-answers-to-chat button and real zoom (memory feedback_artifact_copy_and_zoom).
- JY-321 #318 merged 2026-11-04 on B.'s standing merge authority (reviewer PASS). Live pending.
- JY-275 + JY-109 #317 merged 2026-11-04 on B.'s standing merge authority (reviewer PASS + two hardening fixes). Live pending. JY-300 A build starts on top.
- JY-304 + JY-305 #319 merged 2026-11-04 on B.'s standing authority (reviewer PASS round 2). Live pending.
- JY-300 #320 merged 2026-11-04 on B.'s standing authority (reviewer PASS). Deploy gate (109/275/300) met; one deploy pending.

## 2026-11-04 18:40 AEDT - Deploy
- deploy.sh bf94e98 -> 91c73ab (log deploy-20261104T073145Z-23559.log), hub/media/connectors healthy, 1832 MB available. Every "live pending" above is now LIVE: #305 #307 #308 #306 #311 #310 #309 #312 #313 #314 #315 #316 #317 #318 #319 #320.
- JY-322 umbrella closed (275/109/300 live). JY-307 stays building for phase 3.

## 2026-11-04 evening - Sweep 27 answers (page db, pasted to chat)
- B.: JY-275 "Accept", JY-300 "Accept", JY-304 "Accept", JY-321 "Accept". Qs a/b/c unanswered -> defaults stand (25-title cap kept, title-page Search for upgrade kept, Declined/Failed stay under Requested).
- q-d (JY-320): B. "can you please either use tmdb key or show me how to again and I will create a key.txt file with it. Should I move back to private github for this again." -> nas_scripts/set_tmdb_key.py (project folder, not the repo) reads key.txt or hidden input, sets TMDB_API_KEY on the NAS deploy/.env, recreates hub, checks the key. Repo stays public: the key only ever lives in the NAS .env (gitignored), never in the repo.
- 2026-11-04 20:19 AEDT: B. "key.txt is there" -> set_tmdb_key.py run: key saved to NAS .env, hub recreated (healthy in 9 s), TMDB HTTP 200, key.txt and the .env backup deleted. JY-320 shipped.

## 2026-11-04 late - Next items (B.: "start next items")
- JY-307 P3 PR #321 (TV full-bleed hero + every row 16:9) reviewer PASS; JY-315 PR #322 (episode page A + carousel) reviewer PASS after a settled TV re-shoot proved AC6. Neither merged: the merge classifier refused tonight. Both on Sweep 28 https://claude.ai/artifact/4w7o4NKm7X4V99Nf9AiUT4 with Qs: Q3 rows 16:9 vs posters, Resume-first focus, season chips in place vs page, anything missed.
- "Hero circle in px" P2 leftover: void (no such element after P2b).
- 2026-11-04 21:35 B. (Sweep 28): JY-307 "Accept", JY-315 "Accept"; Qs a-d unanswered -> defaults stand (every row 16:9, Resume-first focus, season chips open the season page). #321 + #322 merged (main d24c4bb). Past the deploy window: deploy first thing 2026-11-05. B.: "merge both prs please. Do that yourself." -> merges stay with Claude; retry, never hand back.
- 2026-11-05 B.: "I am not at home currently. So we can deploy it later." then "Perfect, I will deploy later tonight. Can you continue running on the hitlist." -> main d24c4bb (#321, #322) stays undeployed until B. says deploy (window 07:00-21:30). Started JY-307 phase 4 (backdrop-led TV title pages + Discover search line, spec JY-307-tv-ui-phase4.md) and JY-278 (the "new episode" tag only, spec JY-278-new-episode-tag.md) as background builders.
- 2026-11-05: JY-307 P4 PR #324 (backdrop-led TV title pages + Discover search line) and JY-278 PR #323 (new-episode tag) both reviewer PASS with notes (closed). Neither merged: on Sweep 29 https://claude.ai/artifact/PWbD5u6kwZybwJnbyKb65U for B.'s Accept + Qs a-d (eyebrow vs facts line; Discover state-word contrast; pill wording; anything before phase 5).
- 2026-11-05 B. (Sweep 29): JY-307 "Accept" with "ensure the cast underneath the movie also have a similar 2:3 ratio poster instead of the circular option. It can be smaller"; JY-278 "Accept". Merged #324 (2b4b290) and #323 (d884f0b). Qs a-d blank -> facts line stays, Discover state-word contrast left, pill words as built. Cast tiles = new row JY-323 (S), building. Deploy of main (#321, #322, #323, #324) waits for B.'s "deploy" tonight.
- 2026-11-05 B. (JY-324): "NAS services too" -> shut down = the TV plus the Joey containers on the NAS, back by schedule in the morning. Options page next; button place, keep-running set, wake time and friends access still open.
- 2026-11-05 B. (JY-324): "I would be keen to set up a lot of them later on with home assistant where I can just tell my phone Goodnight and it will turn off the Nas system for now. That is an idea to look at post installation for the NAS system." -> JY-324 v1 = a Goodnight action that turns off the NAS system (one call Home Assistant can trigger later); the TV side is out of v1; HA voice integration is a later row.
- 2026-11-05: JY-324 folded into JY-274 (same "Power down NAS" button ask from 2026-11-02); JY-274 gains the Home Assistant hook requirement (one callable action) and the ADM-not-DSM note. Options page for JY-274 building.
- 2026-11-05: JY-323 PR #325 reviewer PASS after a fix round (5 rem tiles, two-line names). On Sweep 30 for B. Accept. JY-274 options page published; B. to answer or take defaults.
- 2026-11-05 B. (Sweep 30): JY-323 "Accept" (Qs a/b blank -> 5 rem, role one line). Merged #325 (03257d3). Main now carries #321 #322 #323 #324 #325, all undeployed until B. says deploy.
- 2026-11-05 B. (JY-274): "Take defaults" -> sidecar helper (B), B. only, no WoL assumed, allow after 21:30 with warning, no cancel, stop media stack first, header pill (A). Building; ships only after a supervised live power-down with B. present.
- 2026-11-05: JY-274 PR #326 reviewed (hub + helper reviewers PASS with notes, fixed e6490d7) and verified. On Sweep 31 for B. Accept. Merge/deploy does not power anything off: the helper is behind a compose profile until the NAS install + live test with B.
- 2026-11-05 B.: "Accept JY-274" -> #326 merged (ddfd75c). Not shipped yet: the powerctl helper stays off until the NAS install + a supervised live shutdown with B. in a day window (pill colour: red as shot, Qs b/c blank).
- 2026-11-05 B. (Sweep 31, after the merge): JY-274 "Change": corners ~12 px, plus a bottom-right "Power Off?" control with a confirm; "Show me that otherwise just run it and see how it goes" -> follow-up b built without a blocking gate, shots shown after. Assumed Server page only.
- 2026-11-05 16:55 AEDT B.: "I am home now. Can deploy" -> deploy.sh 91c73ab -> 6956375 OK (smoke ok, hub/connectors/media healthy, 1,687 MB free). LIVE: #321 JY-307 P3, #322 JY-315, #323 JY-278, #324 JY-307 P4, #325 JY-323, #326 JY-274 code (helper off). Owner-page content checks need B. on the TV; stylesheet checks below.
- 2026-11-05 B.: "Live test now" -> powerctl installed (deploy/powerctl_install.sh ALL PASS: host poweroff = BusyBox, 12 media containers, 401 without token), hub redeployed a09f7ce and reaches the helper; B. to press. JY-274b PR #327 reviewer PASS, Sweep 32 for a look; merge + deploy after the test.
- 2026-11-05 B. (Sweep 32): JY-274b "Change": no typed POWER DOWN; only the top pill; it opens a confirm like the sign-out dialog. Round 2 reworks PR #327 (corner control removed, typed check dropped, sign-out-style dialog).
- 2026-11-05 17:24-17:36 JY-274 live test with B.: press -> media stopped -> NAS off in under 2 min; on boot the hub/helper/Joey came back but 9 media containers stayed exited (compose stop + unless-stopped). Started by hand; boot-time start via a powerctl marker added to JY-274b round 2. JY-274 not shipped until that lands and a second test shows the stack back by itself.
- 2026-11-05: JY-274b round 2 (sign-out-style dialog, no typed text, boot restart marker) reviewer PASS with notes; Sweep 33 for B. Accept; merge + deploy + second live test on it.
