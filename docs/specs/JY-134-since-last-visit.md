# JY-134 P8 What changed since your last visit

Status: shipped 2026-10-27
Size: S
Live risk: none
Area: `hub/server_visits.py` (new), `hub/main.py` (`_server_response`), `hub/tasks.py` (one shutdown line: `server_visits.flush()`), `hub/templates/server.html` (one line under the head), `hub/README.md`, `tests/hub/`
Needs: none
Options page: none yet. The before / after screenshots at four sizes are in `JoeyTV\review\morning-2026-10-27\JY-134\`.

## Questions for B.
1. What shape?
   - **A: one sentence at the top of Server (built as).** Under the page head, before Attention: "Since your last visit 2d ago: Sonarr and Radarr were updated · wud failed 3 times, then recovered." or "Since your last visit 5h ago: nothing changed." Each viewer (you, Georgina) has their own last visit.
   - **B: a short list.** A "Since your last visit" fold with one row per change and its time. More detail, more room on a phone, less like the sentence Georgina would want.
   - **C: on the Hub's Server card instead.** The sentence on the card she already sees. Reaches her without opening Server, but it costs the Hub render (the tighter page) and the card is shared by both viewers' layouts.
2. What counts as a new visit? **30 minutes without opening Server (built as)**; every page view (a reload would wipe the sentence); or once a day.
3. What it reports. **Built: updates Joey applied (Update now / Update all) that have completed, and feeds that failed and then recovered.** Not built, ask if wanted: disk change ("120 GB free, was 135 GB"), and services that went down and came back (needs JY-133's Kuma samples first). Not possible from stored data today: container restarts outside Joey, and NAS restarts (the NAS powers off every night, so it would say "restarted" every morning).

Data / privacy / budget notes:
- Data: one new media.db table, `server_last_visit(owner TEXT PRIMARY KEY, since TEXT, last_seen TEXT)`: one row per viewer ("you", "her"). Written after the page (a response background task), never during the render.
- Reads stored data only: `server_update_runs` (already read by the page as `last_requested`) and the connectors' runner history (already in memory, JY-226). No live call.
- Privacy: keyed by the Access identity's owner word, never an email. No identity (local dev, an unconfigured OWNER_EMAIL_YOU) means no sentence and no row. The Server page is private-only, so friends never see it.
- Budget: hub page render p95 ≤ 50 ms. The visit rows are read once per media.db and kept in memory (`touch`, the one writer, updates the kept copy), so a render opens no connection. The runner-history scan is kept per viewer, visit start and newest history line (the tail is capped at 1,000 lines, so its length alone cannot say it changed). `touch` updates the kept row on every view and commits to media.db only on a new visit or once a minute; the hub's shutdown flushes the rest.

## Problem
P8 from the 2026-10-19 Server review: "updates applied, containers restarted, sweeps that failed and recovered, since the owner's last Server visit (per-owner timestamp in media.db)". Why: "Georgina never reads logs; this is the sentence she would want."

## Acceptance criteria
For option A:
1. A visit starts when the viewer opens Server more than 30 minutes after their last view. The sentence compares against the end of their previous visit and stays the same for the whole visit.
2. First visit ever (no row): no sentence. No identity: no sentence, and nothing is written.
3. Updates: each container with an Update now / Update all request after the visit's start that has completed is named, capitalised, in request order: "Sonarr was updated", "Sonarr and Radarr were updated", "Sonarr, Radarr and 2 more were updated". Completed = the cached WUD snapshot no longer lists an update for it (`outcome = 'requested'` only means WUD took the trigger). WUD unreadable: no update words (review should-fix, 2026-10-26).
4. Feeds: a connector with at least one failed sweep after the visit's start whose latest sweep is OK: "wud failed 3 times, then recovered" ("once" for one). Still failing: not in the sentence (Attention already says it). Not-configured connectors are left out.
5. Nothing to say: "Since your last visit 5h ago: nothing changed." The time uses the hub's "ago" words.
6. Rendered as `<p class="metaline sincevisit">` above Attention, on the Server page only.
7. The visit row is written after the page, never during the render, and committed at most once a minute within a visit. Once the rows are kept, a render opens no media.db connection (review should-fix, 2026-10-26).
   The kept `last_seen` moves on every view, so the next visit starts at the viewer's real last view, never at the last commit (re-review defect, 2026-10-26: two views 20 s apart, then a later view: its "since" is the second view). After a hub restart without the shutdown flush (a crash, the NAS powering off), the stored value is used: at most one minute behind, and only then.
8. Per viewer: "you" and "her" each see their own last visit.
9. The suite only grows.

## Data
New table `server_last_visit` (above). No snapshot change.

## Performance budget
Hub page render, warm p95 ≤ 50 ms (row 1). Also measured on the NAS at the full check (`scripts/budgets.py` renders without an identity, so it needs one signed-in run to see the sentence).

Local measurement, 2026-10-26 (laptop, demo data: the repo's sample snapshots + the JY-134 seed, signed in as "you"; `JoeyTV/scripts/morning_p95.py`, `/a/server` warm, n=50, client side over loopback, three runs):

| Build | p50 | p95 | max |
|---|---|---|---|
| before (branch base) | 30.7 / 31.2 / 30.8 ms | 34.2 / 32.7 / 33.3 ms | 35.5 / 34.2 / 33.5 ms |
| first build (a write after every view) | 46.5 / 45.2 / 46.3 ms | 49.4 / 50.3 / 52.3 ms | 51.3 / 54.9 / 55.1 ms |
| after the fixes (kept rows, write at most once a minute) | 31.4 / 30.9 / 31.0 ms | 33.4 / 32.8 / 33.1 ms | 36.6 / 34.0 / 33.7 ms |
| after the re-review fix (last_seen kept on every view, commit once a minute) | 30.6 / 30.8 / 30.8 ms | 34.0 / 33.2 / 39.0 ms | 35.1 / 33.5 / 76.4 ms |

The first build's per-view commit cost about 15 ms and pushed p95 over budget; with it rate-limited the page is back to the baseline. The one 76 ms max in the last run is a once-a-minute commit landing during a timed fetch.

## Options and the pick
See "Questions for B.". Pending B.'s pick; built as A.

## Out of scope
- The Hub card (option C); Discord.
- Disk and Kuma changes (question 3).

## Accept checklist
- Open Server, close it, wait 30 minutes, press Update now on something, open Server again: the sentence names it.
- Georgina's view shows her own last visit, not B.'s.
- A quiet day says "nothing changed".

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #197, squash-merged as `7a7d4de` (7a7d4de4b94e04850e4d9742d3d24518307de885).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
