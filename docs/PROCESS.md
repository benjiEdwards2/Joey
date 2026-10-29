# Joey: how an item gets done

How every change moves from idea to shipped. The rules are in `CLAUDE.md`; this file does not repeat them.
Based on the MediaHub workflow (`docs/joeyv2/MEDIAHUB_WORKFLOW.md`), plan in `docs/joeyv2/JOEYV2_PLAN.md`.
Some pieces are not built yet. They are marked TODO(JY-0xx).
Repo: `benjiEdwards2/Joey` (private). TODO(JY-003): `docs/PLAN.md` (the why) does not exist yet.

## The item loop

One item = one spec, one branch, one PR, one builder. Each step has an owner.

1. **Idea.** One line in the HITLIST Inbox. Anyone, any time. TODO(JY-004): `HITLIST.md` does not exist yet.
2. **Spec.** The orchestrator writes `docs/specs/JY-###-slug.md` from `docs/specs/_template.md`. B.'s questions come last in the spec, before its Shipped notes.
3. **Options.** Anything new on a screen gets 2 to 4 built-out options on a private artifact page. Each option is shown at four sizes, built from the real hub markup and CSS: desktop (1440 px), iPad (1024 px), phone (390 px) and TV (1920 × 1080, TV mode). Tiny changes that follow an existing pattern skip this.
4. **B. marks it ready and picks.** The pick and B.'s words go into the spec, with the date. Status becomes `ready`.
5. **Build.** The orchestrator briefs a builder in its own worktree and opens a draft PR when the builder starts, so the labels have a home. The builder codes, writes tests, and hands back a report.
6. **Review.** A different agent reads the diff against the spec. Must-fix findings go back to the same builder. Aim for one fix round. The orchestrator also posts the review as a PR comment.
7. **Full check.** The orchestrator runs the whole suite and the budgets on a quiet machine. The output goes in the PR, with the commit tested. TODO(JY-006): the fast CI check on GitHub does not exist yet. Until it merges, "green CI" means this local run.
8. **Preview.** B. can try the branch before it merges. TODO(JY-012): the preview slot. Until it merges there is no slot, and the PR says how B. can see the change.
9. **B. accepts.** B. walks the spec's accept checklist and says `accepted`, or what to change, in one message. Anything with a screen is shown at the same four sizes (desktop, iPad, phone, TV), and the file to review is attached to the message that asks.
10. **Merge and deploy.** Only on green CI, a review by a different agent, and B.'s accept (`CLAUDE.md` rule 11). Squash merge, then `deploy/deploy.sh`. Claude does both.
11. **Close-out.** See "Close-out" below.

B. has three gates: **mark ready**, **pick**, **accept**. Nothing else waits on B., except hands items (router, Cloudflare, secrets, the TV).

## Round 2

If B.'s feedback changes the design, the item gets a round 2 in the same spec and the same PR:

- status goes back to `spec`;
- new options page, new pick, new acceptance criteria (dated, in the spec's "Round 2" spot);
- B. picks again, and the status goes to `ready`, then `building`;
- review and full check run again on the new tip.

If feedback only fixes bugs against the existing criteria, it is a fix round, not a round 2.

## Roles

| Who | Does | Never does |
|---|---|---|
| B. | Adds ideas, marks specs ready, picks options, accepts builds, reorders the backlog, does the hands items | Writes code, commits, pushes, opens or merges PRs |
| Orchestrator (one long session) | Specs, options pages, builder briefs, full checks, pushes, PRs, merges, deploys, keeps HITLIST and notes current. Keeps every item that does not wait on B. moving in parallel, and stops only when all remaining work waits on him. Edits `CLAUDE.md` and this file only with B.'s OK | Builds large items itself while builders sit idle; reports finished work unasked (B. asks for a summary when he wants one) |
| Builder (subagent, own worktree) | Builds one item to its spec, with tests; reports what it built, tested, measured and skipped | Edits HITLIST, PLAN, PROCESS, `CLAUDE.md` or the tokens; touches files outside the area; runs tests before "machine free" |
| Reviewer (separate subagent, read only) | Reads the diff against the spec; reports must-fix and should-fix, each with file, line and failure case | Reviews its own code; edits anything |

## Size sets the builder and the review

| Size | Builder | Review |
|---|---|---|
| S (chore or small) | Sonnet | One Sonnet reviewer |
| M | Opus, or Sonnet when the spec is tight | One Sonnet reviewer |
| L, or live system / secrets / deploy | Opus | Two Sonnet reviewers, then one Opus verifier after the fixes |

A spec's `Live risk:` line (anything but `none`) puts it in the L row, whatever its size.

An L item is briefed as S/M phases so no builder runs past ~150 turns (token rule 4, 2026-10-29).

## Status words

HITLIST rows use one of these words (TODO(JY-004): `HITLIST.md`). GitHub labels mirror them on the PR, which is opened as a draft when the builder starts. `size/*` and `live-risk` come from the spec.

| Status | Meaning | GitHub label |
|---|---|---|
| `idea` | One line in the Inbox. No spec yet | none |
| `spec` | Spec drafted. Options or B.'s answers pending | none |
| `ready` | B. marked it ready and picked. Builder can start | `spec-ready` |
| `building` | A builder is on it | `building` |
| `review` | Build done. Reviewer and full check running | `review` |
| `accept` | Waiting for B. on the preview or the PR | `accept` |
| `shipped` | B. accepted, merged, deployed, closed out | `accepted`, then `shipped` |
| `parked` | Not now. The row says why | none |

Other labels: `size/S`, `size/M`, `size/L` (from the spec's `Size:`); `live-risk` (from `Live risk:`).
Keep one status label at a time: remove the old one when you add the next.

## How B. accepts

Any one of these counts:

- reply `accepted` in chat, naming the item;
- comment `accepted` on the PR;
- add the `accepted` label to the PR.

Anything else is feedback. Never merge on a guess.

## Machine rule

Builders edit files and run git only. They hold every test, typecheck, build and timing run until the orchestrator sends "machine free: tests allowed". The orchestrator frees one builder at a time. One heavy run (full suite, budgets, deploy gate) happens at a time, so the numbers stay honest.
A failing test is a flake only once proven: run it alone several times at the same commit, check `main`, then record it in the tech notes. TODO(JY-005): `docs/reference/tech-notes.md` does not exist yet.

## Deploy window

The NAS is off 22:00 to 07:00 (Melbourne time). Deploy only between 07:00 and 21:30 Melbourne time, through `deploy/deploy.sh`. Anything that runs on the NAS is limited to the same window: the preview, the budget measurements and the deploy gate. When B. is away, the orchestrator merges and deploys only what B. has already accepted, plus chores with no screen. Everything else waits as a PR with a short accept checklist.
Builds, reviews and local checks can run any time a laptop session is open.

## Branches and worktrees

- Branch: `feat/JY-###-slug`, from `origin/main`.
- Worktree: `../wt-JY-###`, one per item. Its `.env` gets its own port and data dir.
- Command today: `git worktree add ../wt-JY-### -b feat/JY-###-slug origin/main`. TODO(JY-010): `scripts/joey.py worktree new`.
- Never merge or push `main` from the shared clone. It may sit on another session's branch.
- Remove the worktree at close-out. First confirm with `gh pr view` that the PR state is MERGED and that the PR head SHA equals the local branch tip. Then `git worktree remove ../wt-JY-###` and `git branch -D feat/JY-###-slug`.
  TODO(JY-010): check merged via gh, not ancestry (squash merges break --is-ancestor).
- Stacked branches: if B is built on A and A is squash-merged, B's builder rebases B with `git rebase --onto origin/main <A's old tip>`.
- Areas do not overlap. Contracts (shared types, schemas, migrations) merge first.

## What a PR body must hold

The PR template (`.github/pull_request_template.md`) asks for these. Show output, not claims.

- spec link and the pick;
- what changed;
- anything outside the item's area, and why;
- review findings and what fixed them;
- the check output lines and the budget numbers, with the commit tested;
- the accept checklist;
- the attribution footer.

## The builder's hand-back report

A short report, not a transcript. Under 250 words, with:

- commits (hashes and subjects);
- what changed, file by file;
- anything outside the area;
- test output lines (once the machine is free) and measured budget numbers;
- what was skipped or is unsure;
- open questions for B.

The orchestrator checks every claim against the branch before telling B. It never opens the screenshots itself: a reviewer or verifier looks, and the orchestrator reads their verdict (token rule 2, 2026-10-29).

## Close-out

After B.'s accept, with CI green and a review comment on the PR:

1. Squash merge. Verify with `gh pr view` and `git fetch`.
2. Deploy with `deploy/deploy.sh`, inside the deploy window. On the NAS, check `deploy/history.log` for PASS. Also check the health check and the live commit.
3. Fill the spec's Shipped notes: PR, commit, backup name, measured numbers, follow-ups.
4. Set the HITLIST row to `shipped`. Update `hub/README.md`, `docs/` or `deploy/README.md` if the change touches them.
   Steps 3 and 4 are docs-only: commit them straight to `main`, batched with the day's HITLIST sweep, no PR and no CI (rule 11 exception, B. 2026-10-29). Verify with `git fetch` + `git log origin/main -1`.
5. Swap the label to `shipped`. Remove the worktree and the branch.

TODO(JY-011): `scripts/joey.py close-out JY-###` will do steps 1 to 5 and refuse without green CI, a review comment and B.'s accept. Until then the orchestrator does them by hand, in this order.

## The phone, today

Chat with the orchestrator is the main route: ideas, picks and `accepted` all go there. Options pages are private artifacts that open on a phone.
B. can also read PRs and spec files on GitHub, and comment or add labels there. That is optional.
Remote Control is paused: the org policy disables it on the work account. B. will set it up on his own desktop later. Nothing here needs it.

## Changelog

- 2026-10-29: B.: "Yes, apply G1-G4" then "Yes, allow it" (docs-only sweeps and shipped notes straight to `main`); CI runs on ready PRs only and skips docs-only paths (`review-joeyv2-evaluation-2026-10-29.md`, project folder).

- 2026-10-24: B.: "I need the desktop, ipad, phone and tv looks for all of them" (options and accept pages at four sizes); "run as many things as you can until you physically cannot run anymore and are awaiting my confirmation" (orchestrator keeps work parallel); "I need less messages about what you have completed" (summaries on request).
- 2026-10-23: first version (JY-002). Review fixes: round 2 status path, draft PR at build start, merged-check wording, TODO markers, deploy window wording.
