# Joey orchestrator — Phase 2 status (2026-10-23, ~17:10 Melbourne)

Phase 2 build items all SHIPPED (merged, deployed, shipped notes, HITLIST [x], worktrees removed). main = f98db4d, NAS live = 7383455 (later commits are docs-only).

| Item | PR | Squash | Deploy (history) | Reviews |
|---|---|---|---|---|
| JY-013 budgets.py | #48 | 4b1499b | with JY-010, new=387511d PASS dur 899 s | Sonnet PASS + fix round |
| JY-010 worktree tool | #47 | 387511d | new=387511d PASS | Sonnet PASS + fix round |
| JY-012 preview slot | #51 | d6fb047 | new=d6fb047 PASS | Sonnet A FAIL→fixed, Sonnet B PASS, Opus verify PASS; live up/status/down PASS |
| JY-011 close-out | #50 | 7383455 | new=7383455 PASS dur 907 s (by the script itself) | Sonnet A+B FAIL→fixed, Opus verify FAIL→fixed, CI hook-bit fix; self close-out PASS=42 |

Docs/HITLIST PRs merged: #46, #49, #52, #53, #54 (by close-out), #55.
New HITLIST rows: JY-226 (/a/server p95 52-56 ms > 50), JY-227 (gate 15 min > 10), JY-228 (preview hardening), JY-229 (close-out polish).
NAS clone remote repointed to benjiEdwards2/Joey (ls-remote over deploy key OK).

Open: JY-014 = B.'s hands (bundle in JY-014_HANDS_BUNDLE.md: allow rules, Cloudflare preview hostname on the existing Joey Access app, lid action, "full permission"). After B.: `curl -I https://preview.joeyhome.net` → Access redirect; status `ready` until then.
Doc TODO lines for B. (classifier blocks Claude editing CLAUDE.md/PROCESS.md): TODO(JY-010/011/013) in CLAUDE.md Commands; TODO(JY-010/011/012) in PROCESS.md. Replacement text in each spec's Shipped notes.

## Merge authority
B., in the orchestrator session, 2026-10-23: "Yes: merge Phase 2 PRs on green CI plus a clean separate-agent review, without asking me for accepted each time. Record my accept as this message." Quoted on each PR (#47, #50, #51) before merge. Never apply the `accepted` label as Claude (classifier flagged it as self-approval once; corrected on #48).

## Close-out from now on
`python <clone-or-worktree>/scripts/joey.py close-out JY-### --accepted-in-chat "<B.'s words, dated>"` from the shared clone; needs a PR comment whose first line is `Review: PASS ...` (no word FAIL on that line) posted after the last push. `--resume` finishes a close-out that stopped after the merge.

## Phase 3 (2026-10-23, ~17:40 Melbourne) — PR #56, main 3595e42
- JY-020 shipped: LifeDashboard DECISIONS/HANDOVER/BACKLOG + JoeyTV DECISIONS/HANDOVER/MASTER_PLAN/TEST_WINDOWS/DEFERRED moved to each folder's `archive/` as `<NAME>_to_2026-10-23.md` with a banner; both folder CLAUDE.md files are pointers (old copies `archive/CLAUDE_to_2026-10-23.md`). Fresh-agent test PASS.
- JY-022 shipped: memory notes lifedashboard / joeytv / joeyv2 + index lines are pointers.
- JY-021 ready: 43 of 49 worktrees removable with proof; waits for B.'s "go". Kept: wt-b4-tvdocs (tip differs from PR head, though an ancestor of main), wt-rq1/2/3, wt-hitlist, the clone. Clone on fix-upgrade-title (tip in origin/main; only untracked `.joey/`): switching it to main is part of JY-021's go.
- Found: RQ1-3 request features (built 2026-10-22, never pushed/reviewed) → JY-230/231/232. Claude pushed the three branches to origin as a backup (37032e8, 2428063, dbc18b1); the classifier then flagged "Modify Shared Resources". Do not push other sessions' branches without B.'s OK.
- Slip: PR #56 merged before CI registered (`gh pr checks --watch` returned "no checks"); CI then passed on PR and main. Wait for checks to register before merging.

## JY-021 shipped (B.'s go, 2026-10-23) — PR #57, main 059b528
43 merged worktrees removed with `joey.py worktree remove --path` (each re-proved, 0 refused). Left: clone (now on `main`, fast-forwarded, clean), wt-hitlist (orchestrator, detached), wt-b4-tvdocs, wt-rq1-3. Phases 1–3 shipped. Open: JY-014 (B.'s hands); next phase = Phase 4 Pilot (JY-030, JY-031) + JY-230-232 specs.

## Phase 4 started (B.: "Go phase 4", 2026-10-23) — HITLIST PR #59 (7749b3e)
- JY-030 (tv.css comment): PR #58, d062fe1, CI green, Review PASS (Sonnet). Waits for B.'s "accepted JY-030" (the Phase 2 standing accept does not cover Phase 4; the pilot tests B.'s accept). Then `joey.py close-out JY-030 --accepted-in-chat "<B.'s words>"`.
- JY-031 (disk forecast): spec on PR #60 (draft), options page https://claude.ai/artifact/GD2DE6D3PiPkxd1UC8eiBN; waits for B.'s pick + "ready" (e.g. "1A 2a 3a 4a, ready"). L/live: Opus build + 2 Sonnet reviews + Opus verifier.
- B. 2026-10-23: do NOT act on the RQ feature branches (JY-230-232) yet; remind at the end of each reply.
- JY-030 SHIPPED (B.: "accepted JY-030"): close-out PASS=42; PR #58 → d5c9530, deploy PASS dur 919 s, joey-media healthy "after 20 s" (the JY-011 wait-and-retry, proven live); docs PR #61. Pilot item 1 done with one message from B.
- JY-031 (2026-10-23 23:50 Melbourne): PR #60 head 44be543, CI green, ready. Reviews: Sonnet A PASS, Sonnet B PASS, fix round; Opus verify FAIL (one rounding) → fixed; "Review: PASS" posted after the last push. B.'s pick: "go with all recommended please" (1A 2a 3a 4a, ready). Morning (after 07:00): `budgets.py` on prod (before), `preview up feat/JY-031-disk-forecast` (B. sees it only after JY-014 hostname), B.'s accept, then `joey.py close-out JY-031 --accepted-in-chat "<B.'s words>"`, then `budgets.py` (after). HITLIST row still says `spec` on main: the close-out docs PR sets it shipped.
