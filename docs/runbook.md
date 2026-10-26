# Joey runbook

The day-to-day operations for Joey, in one place. Each section says what to run, what you should see, and where the long version lives. It repeats nothing it can point to; the deep detail stays in `deploy/README.md`, `deploy/preview/README.md`, `docs/tv-release.md`, `docs/public-edge.md` and `docs/reference/tech-notes.md`.

Written 2026-10-26 (JY-210). `<nas>` is the NAS LAN address. NAS lines are `ssh root@<nas> "..."` (key `~/.ssh/joey_nas`); the NAS shell is BusyBox sh, with no bash, python3 or git. Run Joey tools from the main clone's repo root; build only in your own worktree. No secret ever goes in a command, a log or a chat.

| I want to | Go to |
|---|---|
| ship a merged change | [Deploy](#deploy) |
| undo a bad deploy | [Rollback](#rollback) |
| let B. try a branch before merge | [Preview slot](#preview-slot) |
| finish an accepted item | [Close-out](#close-out) |
| release the Joey TV app | [TV app release](#tv-app-release) |
| know when the NAS is up | [NAS power schedule and the deploy window](#nas-power-schedule-and-the-deploy-window) |
| check the connectors held up over a day | [Soak check](#soak-check) |
| something broke | [Common failures](#common-failures-and-fixes) |

## Deploy

`deploy/deploy.sh` is the only path to production (`CLAUDE.md`, standing rules). It runs on the NAS as root. Claude runs it; B. only if a run is blocked.

```
ssh root@<nas> /volume1/Docker/joey/life-dashboard/deploy/deploy.sh          # --force redeploys an unchanged SHA
JOEY_NAS=root@<nas> deploy/push.sh                                           # from the laptop: lists pending updates, asks, deploys
```

**Before:** inside the window (07:00 to 21:30 Melbourne, [below](#nas-power-schedule-and-the-deploy-window)); not in the 15 minutes before 00:00 UTC (10:00 AEST, 11:00 AEDT: tests that read the real date can fail across midnight); `git fetch` and confirm `origin/main` is the SHA you mean (a rejected push once went unnoticed and the NAS shipped another session's main).

**What it does, in order:** detach into its own session and log to `deploy/logs/deploy-<UTC>-<pid>.log` (closing the laptop or dropping ssh only stops the watching) -> take the lock (`/tmp/joey-deploy.lock`; a second deploy exits 2 and names the running one) -> `git pull --ff-only` (3 tries, 20 s apart, each logged; JY-206, once PR #183 is merged: until then 3 tries, 5 s apart) -> `compose config` -> **memory check** -> build `life-test` and run the full suite offline -> `compose build` + `up -d` -> smoke -> prune -> publish the TV release if one is waiting.

**The memory gate (JY-240).** Just before the suite, deploy.sh reads `/proc/meminfo`:

| Available memory | Result |
|---|---|
| 1,720 MB or more | suite with `-n 2` |
| 1,460 to 1,719 MB | suite with `-n 1` (about 342 s) |
| under 1,460 MB, or swap used over 1,273 MB, or unreadable | **skipped**: `SKIPPED-LOW-MEMORY`, tree reset to the previous SHA, live stack untouched, exit 1 |

The mode shows in the output and in `history.log` as `gate=-n1 avail=1588`. Free memory (stop the preview with `preview down`, pause qBittorrent), then rerun. The NAS floor is 1,200 MB available during any deploy.

**Read the result.** The last lines of the log end `DEPLOY OK: <prev> -> <new>, tv=<token>`. The truth is `history.log`:

```
ssh root@<nas> "tail -3 /volume1/Docker/joey/life-dashboard/deploy/history.log"
```

| Word | Meaning | What you do |
|---|---|---|
| `PASS` | suite green, smoke ok | nothing; close-out reads this |
| `NOTHING-TO-DEPLOY` | already at that SHA (the TV step still ran) | nothing |
| `GATE-FAIL` | the suite was red; tree reset, live stack untouched | read the log, fix, redeploy. Prove a flake before calling it one ([failures](#common-failures-and-fixes)) |
| `SKIPPED-LOW-MEMORY` | not enough memory for the gate; same handling | free memory, rerun. Not green: close-out refuses until a green run or `--after-fail` |
| `ROLLED-BACK` | build, up or smoke failed; the previous SHA is healthy again | read the log; fix forward |
| `ROLLBACK-FAILED` | both SHAs unhealthy | **act now**: [rollback by hand](#rollback), check `docker ps` |
| `ABORTED` | died before an outcome (for example the pull failed 3 times). The tree is reset to the previous SHA only if the pull had already moved it; a failed pull never moved it, so nothing needs undoing | just rerun |

Each line also carries `prev=`, `new=` and `dur=` (budget: the full gate at most 10 min). Re-attach to a running deploy with `tail -f` on `ls -t deploy/logs | head -1`. Stop one only with `kill <pid>` (never mid `compose up`). A stale lock (holder gone) clears itself; by hand, only when nothing runs: `rm -rf /tmp/joey-deploy.lock`.

**A `deploy.sh` change takes effect from the second deploy after it merges:** a running deploy.sh finishes the copy it read before its own pull. Plan memory and timing for the old behaviour once.

## Rollback

Automatic: a failed build, `up` or smoke resets the tree to `prev=` and rebuilds it (`ROLLED-BACK`). A red or skipped gate never touched the live stack.

By hand (after `ROLLBACK-FAILED`, or to go back past a bad but healthy deploy), with a `prev=` SHA from `history.log`:

```
ssh root@<nas> "docker run --rm -v /volume1/Docker/joey/life-dashboard:/work -w /work alpine/git reset --hard <sha>"
ssh root@<nas> "cd /volume1/Docker/joey/life-dashboard/deploy && docker compose build && docker compose up -d --remove-orphans"
```

Then check `docker ps` (hub, media, swag all healthy). The next `deploy.sh` pulls forward again, so a revert PR is the lasting fix. Two traps: a rollback to a pre-edge SHA removes `joey-swag` (`COMPOSE_PROFILES` in the NAS `.env` survives, so rolling forward brings it back); and never take `edge` or `media` out of `COMPOSE_PROFILES` without the kill-switch runbook R3 in `docs/public-edge.md`. The Joey TV app is never rolled back: roll forward with a higher `versionCode` ([TV app release](#tv-app-release)). `media.db` restore: "Restore media.db" (R5) in `docs/public-edge.md`.

## Preview slot

Lets B. try a branch on his phone or TV before it merges. One slot, `joey-preview`, beside the stack; live data is read only. Spec `docs/specs/JY-012-preview.md`, detail `deploy/preview/README.md`.

```
python scripts/joey.py preview up <branch | PR number>     # build, restore a media.db copy, start, poll /healthz
python scripts/joey.py preview status                      # running or not, commit, memory
python scripts/joey.py preview down                        # tear down; removes image, db copy and env file
```

Needs `JOEY_NAS=root@<nas>`. Refused outside 07:00 to 21:30, while a deploy holds the lock, or under 1,400 MB available; it takes the same lock itself, so a deploy started meanwhile exits 2. Any failure after the db restore tears the slot down. **Run `preview down` before a `docker compose down` of the stack and when you are done:** the preview costs NAS memory, which the deploy gate needs. Every command takes `--dry-run`.

## Close-out

After B.'s accept, green CI and a different agent's `Review: PASS` comment. One command, from the **main clone** (it removes the item's worktree last):

```
python scripts/joey.py close-out JY-### --accepted-in-chat "<B.'s words>, 2026-10-26"     # --dry-run first if unsure
```

It checks the gates (open, not a draft, mergeable; `ci` green on the head SHA; `Review: PASS` after the last push and no later `FAIL`; B.'s accept), runs the read-only NAS preflight (window, no running deploy, 1,200 MB free, last `history.log` line green) **before** it merges, then squash-merges, deploys, verifies (tree on the merge SHA, hub / media / swag healthy, smoke, `/healthz`), writes the shipped notes PR, swaps labels and removes the worktree. Changes that are all Markdown or all under `.github/` skip the deploy (`--deploy auto`).

- Stopped part-way after the merge: `--resume` finishes it. Last deploy not green: `--after-fail` is the one retry.
- Never apply the `accepted` label yourself: the classifier flagged that as self-approval. Use B.'s words in chat, or B. adds the label.
- Squash merges break `git merge-base --is-ancestor`: "merged" means `gh pr view` says MERGED and the PR head SHA equals the local tip. Then `git branch -D`.
- Never merge or push `main` from the shared clone; it may sit on another session's branch (`git branch --show-current` first).
- Worktrees: `python scripts/joey.py worktree new JY-### slug` / `list` / `remove` (removal only with proof of merge).

## TV app release

The Joey TV Android app (`tv/`) is built only in GitHub Actions. **Merging a `tv/` change to `main` is the release:** `.github/workflows/tv.yml` fires on the push to `main` (it also fires on a change to the workflow file itself or to `deploy/tv_version.py`); its `release` job, which runs only when the signing-key secrets exist (`signed=true`), cuts the GitHub Release `tv-<versionCode>`; the next `deploy.sh` publishes it to `https://media.joeyhome.net/app/`; each TV offers it on its next launch.

1. Bump `tv/VERSION` (`versionName`, `versionCode`, `minVersionCode`) and edit `tv/NOTES.txt` (500 characters at most). `versionCode` is the Australia/Sydney date as `YYYYMMDD` plus `nn`, and must be higher than every earlier release. **Every `tv/` change that reaches `main` needs a higher `versionCode`, docs-only edits included; so do changes to `.github/workflows/tv.yml` and `deploy/tv_version.py`, which trigger the same workflow**, or the `release` job fails by design and `main` shows a red run. Check: `python deploy/tv_version.py check`.
2. Merge only in a TV session with B. (it ships to friends' TVs). Watch the run on `main` until `release` is green: `gh run watch ...` (`docs/tv-release.md`, step 5); `gh release view tv-<versionCode>` lists the APK and `version.json`.
3. Then deploy. A deploy before the release finished ends `tv=pending:<code>`; just deploy again later. The history line ends `tv=published:<code>` when it worked (`current`, `pending`, `skipped:no-token`, `FAIL:<reason>` are the others; the TV step never fails a deploy).
4. Verify: `curl -s https://media.joeyhome.net/app/version.json` shows the same `versionCode`.

Roll forward, never back: Android refuses a lower `versionCode`, and `tv_publish.py` refuses a downgrade (`tv=FAIL:downgrade`). A deploy's swag recreate happens only when it changed `deploy/swag/**`; a TV release alone does not blip the edge. Signing key, token renewal, first install over ADB: `docs/tv-release.md`.

## NAS power schedule and the deploy window

- The NAS powers off about 22:00 and on about 07:00 by its ADM schedule. Joey TV decision F7 turns that into 24/7 once friends are live, on the invite day, by removing the schedule in ADM (Settings, Hardware, Power); the steps and the "prove it" checks are in `docs/public-edge.md` (F7). Until the schedule is removed, treat the NAS as off overnight. Check, do not assume: `ssh root@<nas> uptime` (a short uptime means it was off) and the ADM Power page.
- **Deploy window: 07:00 to 21:30 Melbourne time.** The rule stays even if the NAS is up later (`CLAUDE.md`). Anything that runs on the NAS follows it: deploys, the preview, the budget measurements, the gate. `close-out` and `preview up` refuse outside it; a bare `deploy.sh` does not, so the discipline is yours.
- An ssh failure at night usually means the NAS is off, not that something broke (`NAS off 22:00-07:00, or off the home LAN?`). Wait for 07:00.
- Overnight jobs never ran while the NAS was off (Seerr's 03:00 and 05:00 jobs); the hub's Awards sync skips 22:00 to 07:00 by design.
- Builds, reviews and local checks run any time a laptop session is open. When B. is away, merge and deploy only what he already accepted, plus chores with no screen; everything else waits as a PR with a short accept checklist.

## Soak check

WP38 asked for a 24 h soak: every connector beating hourly, none stuck on error. The check is `scripts/check_soak.py` (JY-210), **read only** and run on the laptop against a copy of the runner's history; it never touches the NAS itself.

```
ssh root@<nas> "cat /volume1/Docker/joey/data/snapshots/_runner_history.jsonl" > soak_history.jsonl     # one read, then offline
python scripts/check_soak.py soak_history.jsonl [--expect <ids>] [--exempt money] [--snapshots <copy of the snapshots dir>]
```

The file is the one `joey-connectors` writes into the snapshots mount (`connectors/run_all.py`); the hub only reads it. The check counts, over the last 24 h of the file: at least 22 hourly-loop sweeps (lines without an `only` tag, 2 missed beats allowed), and for **each** connector at least 22 `ok` results and not `error` in every result. `money` is exempt from the ok count (an empty inbox is normal) and must only never report error. Exit 0 = PASS, 1 = a check failed, 2 = could not run. A failure means stop and find the root cause, then re-soak (failure circuit-breaker).

The other WP38 parts are drills, not scripts: the stale-badge drill (point one connector's credential at an invalid value, run 3 manual sweeps, check the last good data plus a "stale" badge, then restore the `.env` backup) and the Notion check (`git grep -il notion connectors/` returns nothing). Run them in one state window with B. watching the tile; they change a live `.env`, so they are not part of the read-only check.

## Common failures and fixes

| Symptom | Cause | Fix |
|---|---|---|
| An after-hours deploy or close-out is refused ("[Production Deploy]" from the auto-mode classifier, 2026-10-24 22:10), or `close-out` says the time is outside the window | The window rule (07:00 to 21:30) plus the classifier's guard on production changes | Wait for the window. If B. wants it tonight he says so in chat ("Run it tonight") and Claude then deploys that one thing; the 2026-10-24 deploy at 22:33 was done that way. Check NAS memory first: the first deploy after a `deploy.sh` change still runs the old copy |
| The classifier refuses Claude editing `CLAUDE.md`, `docs/PROCESS.md`, DECISIONS, or applying the `accepted` label, or pushing another session's branch ("Modify Shared Resources") | Those are rule files and shared state | B. edits the rule files (the replacement text goes in the PR); B. accepts in chat or adds the label himself; push only your own item's branch |
| A test fails once on a PR and passes on rerun, or only under load | A flake (races, shared real files, the real clock) | Do not rerun until green. Run it alone several times at the same commit and on `main`; only then call it a flake and fix the cause in a separate item. Recent ones: preview-lock tests (JY-239), `-n` load flakes (JY-224, JY-225), a trailer race (JY-236), JY-119's background-read race (JY-243), JY-244, JY-249. Rules: `docs/reference/tech-notes.md`, "Tests" |
| A gate `GATE-FAIL` that passed on the laptop | The gate runs on UTC with no `.env`, and `.dockerignore` decides what it sees; the real clock; a new `docs/` file a test reads | Reproduce in the `life-test` image if you can; freeze the clock; whitelist a docs file in `.dockerignore` (`!docs/<file>`). Never weaken the test |
| Rebase or merge conflict in `hub/static/tv.css` (or the hub changelog, a README, the CSS tail) when several items land together | Every item appends at the end of the same file | Resolve by **keeping both** sides. Each item writes its own dated block between markers (`/* ==== JY-### ==== */ ... /* ==== end JY-### ==== */`), so the two never overlap. Then re-run the tests that read `tv.css` (grep `tv.css` in `tests/`) |
| `git push` of the Joey repo falls back to a terminal prompt and fails | The Windows credential helper timed out under heavy CPU load | Retry with `GIT_TERMINAL_PROMPT=0` once load drops; keep one heavy run at a time |
| The daily backup of `Desktop\Claude` (the `claude-workspace` repo) stops pushing | A commit holds a file over GitHub's 100 MB limit: 2026-10-25, a 872 MB AutoCAD temp file under `DrawingMultiToolV2/.../iso_profile/Temp/` | Find it (`git rev-list --objects --all` sorted by size, or the push error), add it to `.gitignore` (`*.ac$`, `**/iso_profile/Temp/` now are) and drop it from the **unpushed** commits only (filter-branch over `origin/main..main`; B.'s OK first). Never rewrite pushed history |
| `deploy.sh` aborts on `Could not resolve hostname github.com` | Container DNS loss while qBittorrent saturates the line | The pull already retries 3 times, 20 s apart. If it still aborts, cap qBittorrent's download at about 70 % of the plan and rerun. The ADM IPv6 DNS entry is B.'s hands (JY-206) |
| Hub answers 502 after a deploy | The hub is not running (a killed deploy once left it `Created`) | `docker ps`; `cd deploy && docker compose up -d`; read `history.log`. Since 2026-10-20 deploy.sh survives a dropped ssh |
| `ssh` to the NAS fails | NAS off 22:00 to 07:00, or the laptop is off the home LAN | Wait, or get on the LAN. Never "fix" it from Joey |
| `curl <nas>:8800` returns 000 | The hub port is not published | Read the hub from inside: `ssh root@<nas> "docker exec -i joey-hub python -" < script.py` |
| After a NAS reboot the box is swapping hard | Swappiness resets on every reboot | Re-run `nas_scripts/swappiness_boot.sh` (project folder, not this repo) |
| `main` shows a red `tv` run after a merge | A `tv/` change without a higher `versionCode` | Bump `tv/VERSION` in a new PR ([TV app release](#tv-app-release)) |

Where the long answers live: `docs/reference/tech-notes.md` (every trap by area), `deploy/README.md` (the deploy script and compose), `docs/public-edge.md` (the public edge, kill switch R3, runbooks R0 to R5, F7), `docs/tv-release.md`, `docs/PROCESS.md` (how an item moves).
