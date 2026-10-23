# The MediaHub Workflow

> Source: Claude Doc shared by @Jack — https://claude.ai/code/artifact/00f8aead-1ca4-4644-aacb-9918ae262fa9 (dated Oct 23, 2026).
> Captured 2026-10-23 by copy-paste from Chrome; the "At a glance" diagram and the four template blocks were transcribed from screenshots.

One person decides and Claude agents build: a long-running orchestrator session writes the specs and the options, a builder agent builds each item in its own git worktree, a different agent reviews it, and nothing merges until the owner accepts it on a preview. Claude does all the git work, pushing to GitHub included; the owner only decides.

## At a glance

Diagram title: **The owner only decides; agents build, check and ship**

```
Idea ──► Spec ──► Options page ──► [Owner picks] ──► Build
(one line,  (what done   (2 to 4,        (spec is ready)    (own worktree)
 Inbox)      means)       drawn)                                 │  ▲
              ▲                                                  ▼  │ must-fix: back to the builder
              │ changes: round 2                              Review
              │                                             (another agent)
              │                                                  │
Merge, deploy ◄── [Owner accepts] ◄── Preview ◄── Full check ◄───┘
(Claude pushes)   (on TV, phone)     (on the server) (tests, budgets)
```

*one item's loop · 10 steps, 2 owner gates, 2 loops back* (caption from the PDF export)

Each item runs this loop once, or twice when the owner's notes change the design. Review findings go back to the same builder, and the owner's changes start a round 2 of the same spec.

## Who does what

The owner makes every decision; the agents do the rest, and no agent reviews its own work.

| Who | Does | Never does |
| --- | --- | --- |
| Owner (one person) | Adds ideas, marks specs ready, picks options, accepts builds on a preview, reorders the backlog | Writes code, commits, pushes, opens or merges PRs: Claude does all the git and GitHub work |
| Orchestrator (one long Claude Code session, Opus) | Writes specs and options pages, briefs builders, runs the full checks one at a time, opens PRs, merges on the owner's accept, deploys, keeps the backlog and notes current | Builds big items itself while builders sit idle |
| Builder (a subagent in its own git worktree, Opus or Sonnet) | Builds one item exactly to its spec, with tests, and reports what it built, tested, measured and skipped | Edits the backlog, the plan, the rules or the design tokens; touches files outside its item's area |
| Reviewer (a separate subagent, usually Sonnet, read only) | Reads the diff against the spec and reports must-fix and should-fix findings, each with a file, a line and a failure case | Reviews code it wrote; edits anything |

Review is sized to the item, to save credits:

| Item size | Builder | Review |
| --- | --- | --- |
| Chore or small | Sonnet | One Sonnet reviewer |
| Medium | Opus, or Sonnet when the spec is tight | One Sonnet reviewer |
| Large, or money, security or the live system | Opus | Two Sonnet reviewers, then one Opus verifier after the fixes |

## The ten rules

These sit at the top of `CLAUDE.md`, which every Claude session in the repo reads first. They are the reason the agents stay on track.

1. No code without a spec the owner has marked `ready`.
2. Anything with a screen gets 2 to 4 built-out options on an HTML page first. The owner picks, and the pick is written into the spec before building starts.
3. Performance budgets are acceptance criteria. Measure them and put the numbers in the PR. Over budget is not done.
4. Tests ship with the code: unit tests for logic, integration tests on a fresh database, and an end-to-end smoke test for every screen. CI must be green.
5. One item, one branch, one PR, one agent. Stay inside the item's area; if you must touch something outside it, stop and say so in the PR.
6. Builders don't edit the backlog, the plan, `CLAUDE.md` or the design tokens. They propose changes in the PR, and the orchestrator applies them.
7. The live system is read only during development. Nothing writes to the real media server, the downloaders or the media folders unless the spec says so, behind a flag, against a test target.
8. Secrets stay in `.env`, which git ignores. `.env.example` lists every key with a comment.
9. Screens come only from the design system package: no hand-rolled colours, radii or spacing. A lint rule enforces it.
10. Write plainly: short sentences, no filler, no claims you didn't check. A PR that says "tests pass" shows the output.

## The files that hold it together

Everything the agents need lives in the repo as plain Markdown, so a fresh session can pick up where the last one stopped.

| File | What it holds | Who edits it |
| --- | --- | --- |
| `CLAUDE.md` | The ten rules, the stack, the commands, where things are. Every session reads it first | Orchestrator, with the owner's OK |
| `HITLIST.md` | The backlog: an Inbox of one-line ideas at the top, then a table per phase (ID, title, area, size, status, why, spec link) | Orchestrator |
| `docs/PLAN.md` | Vision, scope, phases, open decisions, risks | Orchestrator |
| `docs/PROCESS.md` | The loop for every item, roles, git, performance budgets, testing, definition of done | Orchestrator, with the owner's OK |
| `docs/specs/MH-###-slug.md` | One spec per item, from a template (below) | Orchestrator; the owner marks it `ready` |
| `docs/decisions/` and `options/` | Architecture decision records, and the options pages the owner picks from | Orchestrator |
| `docs/reference/tech-notes.md` | Engineering follow-ups found in reviews and builds: flaky tests, risks, small debts. Builders read their area's notes before starting | Orchestrator |
| `packages/ui` | The design system: tokens, components, a README that is the style guide, a live gallery page | Builders, through the README's process; only the orchestrator adds tokens |
| Claude's memory | Short notes that carry state between sessions: the owner's preferences, the current queue, gotchas | Orchestrator |

## One item, start to finish

Every item goes through the same nine steps, and the owner has three gates: the spec, the pick, and the accept.

1. **Idea.** One line in the backlog's Inbox, from anyone, at any time.
2. **Spec.** The orchestrator writes `docs/specs/MH-###-slug.md`: the problem in the owner's words, acceptance criteria (each becomes a test), data, the budget rows that apply, what is out of scope, and an accept checklist. It ends with the questions the owner must answer, each with full options and a recommendation first.
3. **Options.** Anything new on screen gets an options page (next section). Tiny screen changes that follow an existing pattern skip it.
4. **Gate 1 and 2: the owner picks.** The pick and the owner's words go into the spec, and it is marked `ready`. When the owner picks and answers, the spec is ready without another round of asking.
5. **Build.** The orchestrator briefs a builder: the worktree and branch, the spec, the picks, its own database and ports, and the machine rule (below). The builder codes, writes tests, measures, commits, and hands back a short report.
6. **Review.** A different agent reads the diff against the spec. Must-fix findings go back to the builder; one fix round is the aim.
7. **Full check.** The orchestrator runs the complete check (all tests and the performance budgets) on a quiet machine and puts the report in the PR, with the commit it tested.
8. **Gate 3: the owner accepts** on a preview deploy, walking the spec's accept checklist. Feedback comes in one message where possible, so a build gets one fix round, not several.
9. **Merge and deploy.** Squash merge on the owner's accept plus green CI, deploy with a database backup first, then the spec gets its shipped notes and the backlog row says done.

When feedback changes the design ("History should be plays per person, not a list"), the item gets a round 2: new options, a new pick, new criteria in the same spec, and the same PR.

## Options pages

The owner picks from drawings, not descriptions: one HTML page per choice, published as a private Claude artifact so it opens on a phone too.

- **2 to 4 options,** each built out at real size: PC, phone and TV, in the app's own design tokens.
- **Real data,** read (never written) from a preview copy of the library, so the drawings show the owner's own films and numbers.
- **A recommendation first,** with plain pros and cons under each option.
- **The questions at the end,** each standing on its own: the full options spelled out, no shorthand, so the owner can answer "1A, 2B, all A" from a phone.
- **The pick goes into the spec** with the owner's words and the date, before any code.
- **A worker can draw the page** from a brief (the spec, the owner's words, the data to read). The orchestrator reads its text before publishing, and checks it holds no private names or emails.
- **Skip the page for tiny changes** that follow an existing pattern: a label, a link, a sort on an existing control. The spec says the change in a sentence, and the owner can still ask for options.

## Checks and budgets

Two checks guard `main`: a fast one on GitHub for every push, and a full one run locally before every merge, whose report goes in the PR.

| Check | Runs | What it covers | Time |
| --- | --- | --- | --- |
| GitHub CI (`pnpm check:ci`) | Every push and PR | Generated files match, lint and format, typecheck and build, unit, integration and script tests | About 11 to 16 min |
| Full local check (`pnpm check`) | Before every merge, by the orchestrator | All of the above, every browser test at PC, phone and TV size, and the performance budgets | About 20 to 30 min |

The budgets are acceptance criteria, measured by a script that fails when a number is over:

| What | Budget |
| --- | --- |
| An API list call, warm | p95 ≤ 50 ms |
| Search across the whole library | p95 ≤ 150 ms |
| First paint, desktop | ≤ 1.0 s cold, ≤ 300 ms warm |
| Route change to content | ≤ 150 ms |
| A grid of 5,000 posters | 60 fps scroll, no layout shift |
| Initial JavaScript | ≤ 250 KB gzipped |
| Server memory at idle | ≤ 500 MB |

Three habits keep the numbers honest:

- **Nothing else runs during a full check.** Builders may write code in parallel, but they hold every test, typecheck and build until the orchestrator says "machine free: tests allowed". A builder's typecheck once tripled a page's first-paint reading.
- **Run the check where it behaves like production.** On a Windows PC, run it in Linux (WSL). Windows crashed test workers and threw network-stack errors that weren't the code's. A small script starts the Linux run with one command and ends with a 20-line report.
- **A failure is a flake only once proven.** Run the failing test alone several times, at the same commit (8 of 8 passes, say), check main, then record it in the tech notes and fix it later. Date-dependent tests and tests that race the real clock are the usual culprits.

## Running several agents at once

Several builders can work at once because each has its own worktree, area, database and ports, and only one heavy run happens at a time.

- **One worktree per item:** `git worktree add ../app-MH-123 -b feat/MH-123-slug`. Its `.env` gets its own port and its own development database, so builders never collide. The orchestrator removes the worktree after the merge.
- **Areas don't overlap.** Each spec names the folders it may touch. Two items in flight never share one, and a PR that strays says so and why.
- **Contracts first.** When a feature has a server half and a client half, the shared types, API schema and migrations merge first.
- **The machine rule.** Builders write code freely, but a full check or a timing run owns the machine. The brief says "edit files and run git only until I send 'machine free: tests allowed'". The orchestrator frees builders one at a time.
- **Builders hand back a report, not a transcript:** the commits, what changed, what is outside the area, the test output lines, the measured numbers, and any question. The orchestrator checks the claims against the branch before telling the owner.
- **Stacked branches need care.** When item B is built on item A and A is squash-merged, B must be rebased onto main. The builder that wrote B does it, because it knows the code.
- **Long sessions get summarised.** The orchestrator's state lives in the backlog, the specs and Claude's memory, so a fresh session (or a summarised one) carries on without losing the thread.

## Git, previews and deploys

**Claude pushes to GitHub, not the owner. This is a requirement of the workflow.** Every commit, push, PR, merge, preview and deploy is done by Claude; the owner only looks, picks and accepts. That keeps the history, the PR reports and the backlog in step, and means nothing waits on the owner except decisions.

To make that possible, set up once:

- the GitHub CLI (`gh`) signed in on the development PC, so Claude can push branches and open, edit and merge PRs;
- an SSH key from the development PC to the server, so Claude can run the deploy and preview scripts there;
- a pre-commit hook (Prettier on staged files) that Claude must never skip.

The flow after a build:

1. **Push and PR.** The orchestrator pushes the branch and opens the PR, with the spec link, the pick, what changed, what is outside the area, the review's findings and fixes, and the full check's numbers.
2. **Preview.** A script on the server deploys any branch to a preview slot (a second copy of the app on another port, with a copy of the real library's data), so the owner can try it on the TV and phone. Two slots let one preview stay up while the next is prepared.
3. **Accept.** The owner walks the accept checklist and writes `accepted`, or what to change.
4. **Merge.** Squash merge on the owner's accept plus green CI. Never auto-merge.
5. **Deploy.** One script on the server: pull `main`, build the images, dump the database first, start the new version, wait for the health check to report the new commit, and roll back to the old images if it doesn't.
6. **Close out.** Shipped notes in the spec (the PR, the commit, the backup's name, the numbers), the backlog row marked done, the worktree removed.

**The overnight rule.** When the owner goes to bed, the orchestrator keeps working, but only merges and deploys what the owner has already accepted, or chores with no screen (tooling, speed, memory). Everything else goes to a preview with its PR open, plus a short checklist waiting for the morning.

## What we learned the hard way

| Lesson | What we do now |
| --- | --- |
| Agents report success they didn't check | Every claim in a PR shows its output. The orchestrator reads the branch and the logs before telling the owner, and re-verifies anything it wrote from memory |
| A reviewer handed your theory tends to confirm it | Reviewers get the spec and the code, a list of what to check, and an explicit ask to measure the risky part (for example "time the first request after the server goes idle") |
| Builders running tests during a timing run skew the numbers | The machine rule: one heavy run at a time |
| Windows test runs crashed for reasons that weren't the code | Full checks run in Linux (WSL), started from Windows with one command |
| Tests that depend on today's date failed one morning | Tests pin the date or read every case, not the one the day happens to draw |
| GitHub's check sat right at its 16-minute limit and failed by seconds | The limit went to 28 minutes; making the check faster is its own item |
| Squash-merging a branch another branch was stacked on caused 11 conflicts | The dependent branch is rebased onto main by its own builder |
| Feedback in many small messages meant many fix rounds | The owner walks the whole accept checklist, then answers once |
| Questions in shorthand got wrong answers | Every question stands on its own, with its options spelled out in full and the recommendation first |
| A long session re-reads its whole history every turn, which costs credits | State lives in files and memory, so a fresh session can take over |

## Templates to copy

Four starting points. Swap in your own app's name, stack and commands.

### `CLAUDE.md`, at the repo's root

```markdown
# <App>: rules for every agent

Read this first. Then HITLIST.md (what to do), docs/PROCESS.md (how), docs/PLAN.md (why).

## What this is
One paragraph: what the app does, for whom, what it replaces. Owner: <name>, who approves every spec, picks every option and accepts every build.

## Rules
1. No code without a spec marked `ready` (docs/specs/).
2. Anything with a screen gets 2 to 4 built-out options on an HTML page first. The owner picks; the pick goes into the spec.
3. Performance budgets (docs/PROCESS.md) are acceptance criteria. Measure; put the numbers in the PR.
4. Tests ship with the code. CI must be green.
5. One item, one branch (feat/<ID>-slug), one PR, one agent. Stay inside the item's area.
6. Builders don't edit HITLIST.md, PLAN.md, CLAUDE.md or the design tokens; propose changes in the PR.
7. The live system is read only during development.
8. Secrets stay in .env (git-ignored); .env.example lists every key.
9. UI comes only from the design system package.
10. Write plainly. A PR that says "tests pass" shows the output.
11. Claude does all git and GitHub work: commits, pushes, PRs, merges. Never skip hooks.

## Stack
<languages, frameworks, database, where it runs>

## Definition of done
Spec ready, option picked, code and tests, budgets met with numbers in the PR, reviewed by a different agent, accepted by the owner, merged, deployed, backlog and docs updated.

## Commands
<install, dev, test, lint, full check, generate, deploy, preview>
```

### A spec, `docs/specs/_template.md`

```markdown
# <ID> Title

Status: draft | ready | building | review | accept | shipped <date>
Size: · Area: <folders it may touch> · Needs: <other items>

## Problem
One paragraph, in the owner's words where possible.

## Acceptance criteria
Numbered. Each becomes a test or a line in the accept checklist.

## Data
Tables and fields touched or added. Migrations.

## Performance budget
Which budget rows apply, and how they will be measured.

## Options and the pick
The options page's link. The owner's pick, in their words, with the date.

## Out of scope

## Accept checklist
What the owner tries on the preview before writing "accepted".

## Questions for the owner
Each one stands alone: the options in full, the recommendation first.

## Shipped notes
PR, commit, measured numbers, anything left for a follow-up.
```

(The `Size:` value renders blank in the source doc — likely a placeholder lost in rendering.)

### A builder's brief, sent by the orchestrator

```markdown
Build <ID>: <one line>.

- Worktree: <path>, branch feat/<ID>-slug (from main <commit>). .env has its own PORT and DATABASE_URL.
- Spec: docs/specs/<ID>-slug.md (ready; the owner's picks: <…>). Read the tech notes for your area first.
- Area: <folders>. Anything outside it: stop and say so.
- Machine rule: a full check may be running. Until I send "machine free: tests allowed", edit files and run git only.
- Hand back: commits, what changed, what is outside the area, test output lines, measured budget numbers, open questions.
```

### A reviewer's brief

```markdown
Review <ID> on branch <branch> (tip <commit>) against docs/specs/<ID>-slug.md.
Read only: don't edit, commit or run the full suite.
Check, most important first: <privacy | the data rule | edge cases | the TV path | tests that could pass with wrong behaviour>.
Measure the main risk if you can: <what to time, and against what control>.
Report in under 400 words: must-fix and should-fix, each with a file, a line and a failure case; then what you checked and found fine. Don't claim anything you didn't read or run.
```
