# JoeyV2 — running Joey the MediaHub way

2026-10-23 · status: **Phases 1–2 shipped; Phase 3 shipped except JY-021 (waits for B.'s go); live status is `HITLIST.md`** · source workflow: `Desktop\Claude\MediaHubWorkflow.md` (Jack's doc)

**Goal.** Keep the Joey app as it is (FastAPI hub, connectors, NAS, 3,000+ tests). Change how work gets done. B. only decides: he marks specs ready, picks options, and accepts on a preview, whenever suits him. Claude runs everything else: specs, builds, reviews, checks, PRs, merges, deploys. Work is cut into small JY items (§4), each one spec, one branch, one PR, one agent. "V2" means the operating model, not a rewrite (Q1 A).

---

## 1. How Joey runs today (review)

What works and stays:

| Practice | Evidence |
| --- | --- |
| Subagents with explicit models in worktrees, coordinator merges | Every round since 2026-10-06 (Opus logic, Sonnet templates/CSS) |
| Options pages before screens | Layout Lab, Film Page Lab, Awards A/B/C, Episodes shell |
| Interface contracts for parallel builds | `BALLOT_CONTRACT.md`, `EPISODES_CONTRACT.md` |
| One deploy path with gate + rollback | `deploy/deploy.sh`, life-test image, history.log |
| Batched state windows, script-first, skip = defer | Joey TV `TEST_WINDOWS.md`, `DEFERRED.md`, `pr_close_out.py` |
| Large cumulative suite | 3,171 tests at the 2026-10-22 gate |

What breaks the "owner only decides" model:

| # | Problem | Evidence | MediaHub answer |
| --- | --- | --- | --- |
| 1 | **State lives outside the repo, and it is huge.** A fresh session cannot pick up cheaply. | LifeDashboard `DECISIONS.md` 305 KB, Joey TV `DECISIONS.md` 300 KB, `MASTER_PLAN.md` 324 KB, HANDOVERs 27–33 KB that stack rounds instead of replacing them (target was < 60 lines) | `CLAUDE.md`, `HITLIST.md`, specs and PLAN all in the repo, each small |
| 2 | **No item record.** Work arrives as rounds from screenshots. Its "spec" is spread over DECISIONS, HANDOVER and BACKLOG. There are no IDs and no `ready` status. | BACKLOG.md is prose grouped by date; "Decision needed" items wait for weeks | One spec per item (`MH-###`) with status, criteria, accept checklist, questions |
| 3 | **Hub work skips PRs and CI.** Branches go `git push origin <branch>:main`. CI covers only `tv/**`. | `.github/workflows/tv.yml` is the only workflow; PRs #1–#36 are almost all Joey TV | Every item = one PR; fast CI on every push |
| 4 | **Work gets lost between "built" and "shipped".** | `library-grid` sat unpushed 2026-10-13 → 10-22 while every HANDOVER assumed it had landed | Backlog row status + close-out notes in the spec |
| 5 | **Who pushes, merges and deploys keeps changing.** | B. pushes (10-06) → coordinator pushes (10-22) → Claude merges via script (Joey TV, 10-22); deploy.sh refused as "Production Deploy" in some sessions | Claude does all git and deploys, always (a hard requirement) |
| 6 | **B.'s inputs are scattered.** Each round ends with its own "B.'s hands" list. Older lists are still open further down HANDOVER. | 2026-10-22 HANDOVER has open hand lists from 10-13, 10-16, 10-19, 10-21, 10-22 | Questions at the end of the spec; accept on a preview, in one message |
| 7 | **No preview.** B. accepts on production, after the deploy. | Eyes-on runs on local preview scripts with fakes in the scratchpad (stale once purged) | A preview slot on the server, accepted before merge |
| 8 | **Review = the coordinator re-running the suite.** No separate reviewer reads the diff against a spec. | Round sections say "eyes-on PASS", with no review findings | A different agent reviews against the spec; size decides the review tier |
| 9 | **Workspace drift.** | 48 worktrees; the shared clone sits on `fix-upgrade-title`; parallel sessions park it on their own branches | One worktree per item, removed at close-out |
| 10 | **Performance is measured ad hoc.** | EVALUATION 2026-10-12 measured 10–30 ms renders; there are no standing budgets | Budgets are acceptance criteria; the full check fails over budget |

## 2. JoeyV2 in one picture

```
 B. DECIDES (any time, chat or phone)                     B. ACCEPTS (any time, on the preview)
 mark a spec ready · pick an option ·                     walk the item's accept checklist →
 answer its questions "1A 2B all A"                       "accepted", or what to change, in one message
            │                                                         ▲
            ▼                                                         │
 ┌───────────────────────── Claude, in between ────────────────────────────────────┐
 │ Orchestrator: spec → options page → brief builders → review → full check → PR  │
 │ → preview slot → (wait for accept) → merge → deploy → shipped notes → close-out│
 │ Builders: one per item, own worktree, own port. Reviewer: a different agent.   │
 └─────────────────────────────────────────────────────────────────────────────────┘
 HANDS (B., only when needed): router / Cloudflare / secrets / TV, as one bundle per state window
```

Input does not have to come in batches (B., 2026-10-23). What stays: each item's questions are grouped at the end of its spec, and the accept checklist is walked in one go, so each item gets one fix round.

**Deploy window:** the NAS is off 22:00–07:00 (Joey TV D1, kept on 2026-10-23). So the "overnight rule" becomes a **daytime rule**: when B. is away, the orchestrator merges and deploys only accepted items and chores with no screen, between 07:00 and 21:30. Builds, reviews and checks run whenever the laptop session is up.

## 3. What changes, mapped to Joey

| MediaHub piece | JoeyV2 version |
| --- | --- |
| `CLAUDE.md` in the repo, 10 rules | New repo-root `CLAUDE.md`: MediaHub's 10 rules + Joey's standing rules (no area names in hub code, state is a word, never log URLs/keys, `.env` newline guard, NAS RAM ceiling, NAS off 22:00–07:00). The LifeDashboard `CLAUDE.md` shrinks to a pointer. |
| `HITLIST.md` | New `HITLIST.md` in the repo: Inbox + one table per phase (ID `JY-###`, title, area, size, status, why, spec). Seeded from BACKLOG.md, Joey TV DEFERRED.md and every open "B.'s hands" item. BACKLOG.md is archived. |
| `docs/specs/MH-###` | `docs/specs/JY-###-slug.md` from MediaHub's template, plus a `Live risk:` line (NAS write, Seerr/arr write, secrets) that sets the review tier |
| `docs/PLAN.md`, `docs/PROCESS.md` | New; PLAN = the 8 areas (5 hidden), phases, open decisions; PROCESS = the loop below |
| `docs/reference/tech-notes.md` | New; seeded from the "Lessons"/"gotchas" spread through DECISIONS and memory (BusyBox shell, PowerShell→ssh BOM, Jellyfin 12.2 auth header, `git branch -d` trap, etc.) |
| Decisions log | DECISIONS.md is **frozen and archived** (both projects). New decisions go in the spec ("pick + owner's words + date") or in `docs/decisions/ADR-###` for architecture. |
| Handover | Not needed: state = HITLIST + specs + memory. Memory notes shrink to pointers. |
| Options pages | Same as today (private Claude artifacts), now required for anything with a screen and linked from the spec. **No GitHub Pages**: the repo is private (decided 2026-08-24), and Pages on a private repo needs a paid plan and publishes publicly. |
| GitHub CI fast check | New `.github/workflows/ci.yml`: on PR and on `main` only (not every branch push, to save the 2,000 free minutes a month). Covers lint, connector contract, `pytest -n auto` without the slow/live markers. |
| Full local check | Existing gate: `python -m pytest -n 4 tests/` locally + the deploy.sh life-test gate. Plus a new `scripts/budgets.py` run in-container. |
| Preview slot | New: a second compose project `joey-preview` on the NAS (one hub, no connectors, reads live snapshots **read-only** + a copy of media.db) at `preview.joeyhome.net` behind the same Access policy. One slot, because NAS RAM rules out two. |
| Close-out script | Generalise Joey TV's `pr_close_out.py` → `scripts/joey.py close-out JY-###`: refuses unless CI is green + a review comment exists + B.'s `accepted` is on the PR (or in chat) → merge → deploy.sh (detached, nohup) → health + commit check → shipped notes in the spec → HITLIST row done → worktree removed. This replaces branch protection, which needs a paid plan on a private repo (HTTP 403 today). |
| Machine rule | Same text ("edit files and run git only until 'machine free: tests allowed'"). The laptop is the test machine; the NAS gate is the second heavy run, also one at a time. |
| Overnight rule | Daytime rule (above). |

Proposed budgets (to confirm, Q6). Each is measured inside joey-hub on the NAS:

| What | Budget |
| --- | --- |
| Hub page render, warm | p95 ≤ 50 ms (measured 10–30 ms on 2026-10-12) |
| Media list / item page, warm | p95 ≤ 150 ms |
| Discover page | ≤ 3 s, never blocks (E1 cap) |
| joey-hub memory | ≤ 200 MiB (cap 384; measured 79 MiB) |
| NAS available memory during any deploy or preview | ≥ 1,200 MB (Joey TV rule) |
| Full gate (deploy.sh) | ≤ 10 min |

## 4. Rollout — phases with stopping points

Each phase is cut into small items the MediaHub way: **one item, one spec, one branch, one PR, one agent, one area**. The size sets the builder and the review tier (MediaHub's table):

| Size | Builder | Review |
| --- | --- | --- |
| S (chore or small) | Sonnet | one Sonnet reviewer |
| M | Opus, or Sonnet when the spec is tight | one Sonnet reviewer |
| L, or live system / secrets / deploy | Opus | two Sonnet reviewers, then one Opus verifier after the fixes |

The JoeyV2 set-up items use IDs JY-001 to JY-099. Items imported from today's backlogs start at JY-100. "Needs" = items that must merge first (MediaHub's "contracts first"). Items with no shared "Needs" and different areas run in parallel. **Gate** = what B. does for that item; "—" means nothing.

### Phase 0 — Decide · DONE 2026-10-23
All nine questions answered (DECISIONS.md).

### Phase 1 — Repo scaffold (the files that hold it together)

| ID | Item | Area (files it may touch) | Size · builder | Needs | Done when | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| JY-001 | Repo `CLAUDE.md`: MediaHub's 10 rules + Claude-does-all-git + Joey standing rules + stack + commands + definition of done | `CLAUDE.md` | S · Sonnet | — | Every rule in today's LifeDashboard + Joey TV `CLAUDE.md` is either in it or listed as dropped in the PR | accept PR |
| JY-002 | `docs/PROCESS.md` (the loop, roles, size table, machine rule, deploy window, close-out), `docs/specs/_template.md`, `.github/pull_request_template.md` | `docs/PROCESS.md`, `docs/specs/`, `.github/pull_request_template.md` | S · Sonnet | JY-001 | The template has every MediaHub section + `Live risk:`; the PR template asks for spec link, pick, outside-area, review findings, check numbers | accept PR |
| JY-003 | `docs/PLAN.md`: vision, the 8 areas (5 hidden), phases, open decisions, risks, from archive MASTER_PLAN + DECISIONS current state | `docs/PLAN.md` | M · Sonnet | JY-001 | ≤ 150 lines; every open "Decision needed" is listed once | accept PR |
| JY-004 | `HITLIST.md` seeded: Inbox + one table per phase; every open item from BACKLOG.md, Joey TV DEFERRED.md, Joey TV `TV_UI_PLAN.md` U1–U11 (JY-042), the open "B.'s hands" lists in both HANDOVERs, SERVER_REVIEW P3/P5–P10 → one JY-1xx row | `HITLIST.md`, `scripts/hitlist_seed_check.py` | M · Sonnet (check script Opus) | JY-002 | The check script lists every source item and its row; 0 unmatched | accept PR |
| JY-005 | `docs/reference/tech-notes.md`: the gotchas now spread over DECISIONS and memory (BusyBox shell, PowerShell→ssh BOM, Jellyfin 12.2 auth, `git branch -d` trap, UTC gate image, `.env` newline guard, …), grouped by area | `docs/reference/` | M · Sonnet | JY-001 | Each note: one line + where it bit; builders can find their area in one scroll | accept PR |
| JY-006 | `.github/workflows/ci.yml`: fast check on PR and `main` only; runs the suite with `-n auto`; adds a `live` pytest marker if any test needs the NAS (none exist today); Actions pinned by SHA like `tv.yml` | `.github/workflows/ci.yml`, `pytest.ini` | M · Opus | — | CI green on its own PR; runtime written in the PR (target ≤ 12 min, under the 2,000 free min/month at ~100 PRs) | accept PR |
| JY-008 | This plan, its DECISIONS log, the JY-049 research and a copy of Jack's MediaHub workflow move into the repo as `docs/joeyv2/` (B., 2026-10-23: needs to see the full upload and recent edits on GitHub). From the merge on, these repo copies are the ones edited; the laptop folder `Desktop\Claude\JoeyV2\` keeps a pointer | `docs/joeyv2/`, `docs/README.md` | S · orchestrator | — | Files visible on GitHub `main` | accept PR |
| JY-007 | Repo settings + labels with `gh`: squash only, delete branch on merge, labels `spec-ready building review accept accepted shipped size/S size/M size/L live-risk` | GitHub settings (no PR) | S · orchestrator | — | `gh repo view` + `gh label list` read-back | — |

Order: JY-001 + JY-006 + JY-007 first (parallel), then JY-002, then JY-003 ‖ JY-004 ‖ JY-005. Changed 2026-10-23: JY-008 added; JY-002 ‖ JY-004 pulled forward so HITLIST reaches GitHub early.

Status 2026-10-23: JY-007 done (merge commits stay allowed until JY-040, because Joey TV's close-out script uses `--merge`). JY-001 = PR #38, JY-006 = PR #37 (CI found 6 Linux-only test bugs; fix in progress).

### Phase 2 — Tooling

| ID | Item | Area | Size · builder | Needs | Done when | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| JY-010 | `scripts/joey.py worktree new JY-### slug` / `remove`: worktree + branch `feat/JY-###-slug` + its own `.env` (port, data dir); remove only after an `--is-ancestor origin/main` check | `scripts/joey.py`, `tests/scripts/` | M · Opus | JY-002 | Tests create and remove a worktree in a temp repo; refuses to remove an unmerged branch | accept PR |
| JY-011 | `joey.py close-out JY-###`: refuses unless CI green + a review comment + B.'s accept → squash merge → deploy.sh detached (nohup) → `/healthz` + live commit check → shipped notes in the spec → HITLIST row done → worktree removed. Generalises Joey TV's `pr_close_out.py` | `scripts/joey.py`, `tests/scripts/` | L · Opus (live) | JY-010 | Dry-run on a doc-only PR prints every step PASS; refusal paths each tested | accept PR |
| JY-012 | `deploy/preview/` compose project `joey-preview` (one hub, no connectors, live snapshots mounted `:ro`, a media.db copy) + `joey.py preview <branch>` + teardown | `deploy/preview/`, `scripts/joey.py` | L · Opus (live) | JY-010 | Preview of `main` serves `/healthz` on the NAS; NAS available memory stays ≥ 1,200 MB; teardown leaves nothing running | accept PR + hands (JY-014) |
| JY-013 | `scripts/budgets.py`: measures the §3 budgets inside joey-hub (read-only), prints a 20-line report, exits non-zero over budget | `scripts/budgets.py`, `tests/scripts/` | M · Opus | JY-001 | One live run against production, numbers in the PR | accept PR |
| JY-014 | Hands bundle for B. (one message, exact click-paths): (1) allow rules in `Documents\Claude\.claude\settings.local.json` for `git push`, `gh pr merge`, the ssh-wrapped `deploy.sh` and preview script; (2) Cloudflare: tunnel `joey-nas` → public hostname `preview.joeyhome.net` → `http://joey-preview:8000`, added to the `Joey` Access app; (3) say "full permission" once in the orchestrator session | B.'s settings + Cloudflare | S · B. | JY-012 open as PR | `curl -I https://preview.joeyhome.net` → Access redirect; one test push/merge from Claude succeeds | B. does it |

Order: JY-010 ‖ JY-013, then JY-011 ‖ JY-012, with JY-014 prepared while JY-012 builds.

### Phase 3 — Clean slate (local files, no PRs) · runs alongside Phase 2

| ID | Item | Size · who | Needs | Done when | Gate |
| --- | --- | --- | --- | --- | --- |
| JY-020 | Archive LifeDashboard + Joey TV `DECISIONS.md`, `HANDOVER.md`, `BACKLOG.md`, `MASTER_PLAN.md`, `TEST_WINDOWS.md`, `DEFERRED.md` into `archive/` with a status banner; both project `CLAUDE.md` files become pointers to the repo `CLAUDE.md` | S · Sonnet | JY-004 merged | A fresh session answers "what's next?" from HITLIST alone (tested by a fresh subagent) | — |
| JY-021 | Remove merged worktrees with `joey.py worktree remove` (ancestor-checked); clone back on `main` | S · orchestrator | JY-010 merged | `git worktree list` = main + live items only | say "go" (it deletes worktrees) |
| JY-022 | Memory: `project_lifedashboard` + `project_joeytv` cut to pointers (repo, HITLIST, tech-notes); new `project_joeyv2` | S · orchestrator | JY-020 | Index lines updated | — |

### Phase 4 — Pilot (two real items through the whole loop) · the player spec + options study (JY-050, JY-051) run alongside

| ID | Item | Size | Needs | Done when | Gate |
| --- | --- | --- | --- | --- | --- |
| JY-030 | Chore: stale "Grouped" toolbar comment at `hub/static/tv.css:99` (BACKLOG, 2026-10-22) | S | Phases 1–3 | `shipped` with notes; B. spent ≤ 1 message | accept on preview |
| JY-031 | Screen item: P1b disk forecast on the hub card + Discord (BACKLOG, 2026-10-22) — options page first | L (Discord = live) | Phases 1–3 | `shipped`; B. spent ≤ 2 messages (pick + accept) | spec ready, pick, accept |

### Phase 5 — Media player (Joey plays the film itself on every device, replacing the hand-off to the Jellyfin app)

Added 2026-10-23 (DECISIONS.md). Video never goes through the Cloudflare tunnel (Joey TV ARCHITECTURE: terms grey area). Streams come from the `jellyfin.joeyhome.net:8443` edge, and pages stay behind Access.

| ID | Item | Size · builder | Needs | Done when | Gate |
| --- | --- | --- | --- | --- | --- |
| JY-049 | **Transcoding box: requirements + shortlist** (read-only research, can run now): what Jellyfin hardware acceleration needs (Intel Quick Sync: HEVC 10-bit + AV1 decode/encode, tone mapping), RAM, idle power, price; 2–3 machines; how many 4K→1080p streams each; where it sits (whole Jellyfin moves, or the NAS keeps storage and the box serves) | M · Opus | — | One page, a recommendation first; sources cited | B. buys |
| JY-050 | Player spec + questions: devices (web, phone, TCL TV, the pilot friend's Google TV), household only or friends too, direct play vs transcode rules, what "done" means per device | S · Sonnet (orchestrator writes) | JY-002 | Spec marked `ready` | answer the spec questions |
| JY-051 | **Player options study** (read-only spike): per device, the candidates and what each plays. Browser/phone: `<video>` + hls.js (Jellyfin's own web client approach). TV shell: Media3 ExoPlayer (Jellyfin's official Android TV app), with or without the ffmpeg decoder extension (DTS / TrueHD audio), vs libVLC vs mpv. Server side: jellyfin-ffmpeg transcodes whatever a device cannot play. Test with 3–5 real files (H.264, HEVC 10-bit HDR, AV1; DTS/TrueHD; PGS/ASS subtitles) on the TCL, phone and PC; NAS CPU/RAM during one transcode | M · Opus | JY-050 draft | Matrix device × file → direct play / remux / transcode, measured; recommendation per device | read the result |
| JY-052 | Options page: player screen at PC, phone and TV size (controls, tracks, up next, resume) | S · Sonnet | JY-051 | Published as a private artifact | pick |
| JY-053 | Contract first: hub playback-session endpoints (Jellyfin PlaybackInfo → stream URL on the edge, token handling) + progress reporting shape | M · Opus | JY-052 pick | Contract doc + tests merged | — |
| JY-054 | Web/phone player | L · Opus (live) | JY-053 | Plays the JY-051 test files on PC + phone from outside the LAN; budgets held | accept on preview |
| JY-055 | Progress, resume and "watched" synced back to Jellyfin (and Joey's play recorder) | M · Opus | JY-053 | Stop on one device, resume on another | accept |
| JY-056 | Audio + subtitle track picker | M · Opus | JY-054 | Every JY-051 test file's tracks selectable | accept |
| JY-057 | TV shell player: replaces the Jellyfin-app hand-off; new signed release | L · Opus (live) | JY-054, JY-055; the TV UI round's shell items (JY-042) shipped first so the shell isn't changed twice | D-pad playback, Back returns to Joey, update drill on the TCL | accept at the TV |
| JY-058 | Friends' path + security gate (only if JY-050 says friends) | L · Opus (live) | JY-057 | Gate script PASS like Joey TV W4 | accept |
| JY-059 | Move Jellyfin transcoding onto the new box | L · Opus (live) + B.'s hands | B. has bought it (JY-049) | One 4K→1080p transcode at full speed; NAS CPU idle during it | hands bundle at the box |

Order: JY-049 any time. JY-050 → JY-051 during the Pilot. Then JY-052 → JY-053 → JY-054 ‖ JY-055 → JY-056 → JY-057 → JY-058. JY-059 whenever the box arrives; the player works on direct play without it.

### Phase 6 — Steady state

| ID | Item | Size | Needs | Done when | Gate |
| --- | --- | --- | --- | --- | --- |
| JY-040 | Joey TV W6 close + W7 TV sitting as JY items (W7 stays one hands bundle at the TV); rename the coordinator session "Joey — Orchestrator" | S | JY-020 | Joey TV coordinator closed; its items in HITLIST | the W7 sitting |
| JY-041 | One-week check: messages per item, items shipped, budgets held, anything that fell through | S | JY-031 shipped | A short note in `docs/PROCESS.md` changelog | read it |
| JY-042 | **Joey TV UI round** (B., 2026-10-23: "looks wrong / doesn't work well on the TV"; "rows and cards way too large"): the 11 fix WPs U1–U11 in `JoeyTV\TV_UI_PLAN.md` become JY-1xx items (one spec each, built from `JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md` + the `JoeyTV\mockups\tv-v2\` shells), including the **row + card scale change** from shell `08-density.html` (today 6 across, 1.4 rows → B compact 8 across ~2 rows, or C dense 10 across ~2.6–3.4 rows; compact top bar 64 + 40 px) | L (split into the JY-1xx items; U4 server + U5 shell app = live) | JY-004 seeded (rows exist); B.'s Gate 1 picks (scale + picks 1–6 in TV_UI_PLAN.md) | Every U-item `shipped`; one grouped TCL run `tv_ui_capture.py all` shows Back restores focus/scroll, ≥ 2 rows visible on Overview and the grid, 0 text < 18 px, `lowContrast`/`outsideSafe` no higher than the 2026-10-23 baseline | scale pick + picks 1–6, then accept on preview |

## 5. GitHub requests

Claude does these with `gh` (signed in as benjiEdwards2):

- JY-007: labels `spec-ready`, `building`, `review`, `accept`, `accepted`, `shipped`, `size/S`, `size/M`, `size/L`, `live-risk`; `deleteBranchOnMerge=true`; **squash merge only** (Q5 A).
- JY-006 and JY-002: `ci.yml` and the PR template, in their own PRs.

Not needed, per the answers: GitHub Pro (Q3 A), the GitHub mobile app (Q2 A), GitHub Pages (the repo stays private), new secrets. B.'s hands items: JY-014 (permissions + preview hostname), the box purchase (JY-049) and its install (JY-059), plus the TV sittings (JY-040, JY-057).

## 6. Questions for B. — ANSWERED 2026-10-23: all A (recommended); see DECISIONS.md

1. **What does "JoeyV2" mean?**
   A. The same Joey app and repo, run with the new operating model (this plan). **Recommended**: the app is live, tested and fast; the pain is in the process.
   B. A rebuild of the app as well (new repo, new stack), run the new way from day one. That is weeks of work and re-does the 3,000-test suite.
2. **Where do ideas and accepts come from?**
   A. Chat with the orchestrator for everything, plus the morning/evening batch pages as private Claude artifacts. **Recommended**: no new app, works from your phone today.
   B. GitHub mobile: ideas as issues labelled `inbox`, accepts as an `accepted` comment on the PR. The orchestrator sweeps both. More auditable; one more app.
3. **How are merge rules enforced?**
   A. By `scripts/joey.py close-out`: it refuses to merge without green CI + a review + your accept. **Recommended**: free, and already proven by `pr_close_out.py`.
   B. Buy GitHub Pro (US$4/month) and also turn on branch protection with required checks.
4. **Standing permission for Claude to push, merge and deploy.** Some sessions are still refused ("Production Deploy").
   A. Add allow rules for `git push`, `gh pr merge`, and the ssh-wrapped `deploy.sh` / preview script to `Documents\Claude\.claude\settings.local.json`, and say "full permission" once in the orchestrator session. **Recommended**: the workflow requires Claude to do all git and deploys.
   B. Keep today's split: Claude merges, you run deploy.sh from a one-line paste.
5. **Merge style.**
   A. Squash merge, one commit per item. **Recommended**: matches MediaHub; history reads as a list of items.
   B. Merge commits, as Joey TV uses now.
6. **Performance budgets.**
   A. Adopt the table in §3 as acceptance criteria. **Recommended**: built from your own measured numbers, with headroom.
   B. Start with memory and render time only; add the rest later.
7. **Preview slot.**
   A. One `joey-preview` hub on the NAS at `preview.joeyhome.net`, using live data read-only, with connector changes previewed on sample data only. **Recommended**: you accept on your real phone/TV before merge, at ~100 MB of NAS RAM.
   B. No preview slot: accept after deploy on production, as today, with rollback as the safety net.
8. **What happens to Joey TV's remaining work (W6 close, W7 TV sitting ~2026-11-05)?**
   A. It moves into HITLIST as `JY-` items after Phase 3; the W7 sitting stays one hands batch. **Recommended**: one backlog, one orchestrator.
   B. Joey TV finishes under its own coordinator first, and JoeyV2 starts after W7.
9. **When the laptop is shut, the orchestrator stops.**
   A. Accept that: Claude works while a session is open, and the batches set the rhythm. **Recommended**: deploys need the LAN anyway.
   B. Also try cloud sessions for builds and reviews (no NAS access; they push branches only).
