# JY-134 P8 What changed since your last visit

Status: spec (built as the recommended option for B.'s morning review, 2026-10-26)
Size: S
Live risk: none
Area: `hub/server_visits.py` (new), `hub/main.py` (`_server_response`), `hub/templates/server.html` (one line under the head), `hub/README.md`, `tests/hub/`
Needs: none
Options page: none yet. The before / after screenshots at four sizes are in `JoeyTV\review\morning-2026-10-27\JY-134\`.

## Questions for B.
1. What shape?
   - **A: one sentence at the top of Server (built as).** Under the page head, before Attention: "Since your last visit 2d ago: Sonarr and Radarr were updated · wud failed 3 times, then recovered." or "Since your last visit 5h ago: nothing changed." Each viewer (you, Georgina) has their own last visit.
   - **B: a short list.** A "Since your last visit" fold with one row per change and its time. More detail, more room on a phone, less like the sentence Georgina would want.
   - **C: on the Hub's Server card instead.** The sentence on the card she already sees. Reaches her without opening Server, but it costs the Hub render (the tighter page) and the card is shared by both viewers' layouts.
2. What counts as a new visit? **30 minutes without opening Server (built as)**; every page view (a reload would wipe the sentence); or once a day.
3. What it reports. **Built: updates Joey applied (Update now / Update all) and feeds that failed and then recovered.** Not built, ask if wanted: disk change ("120 GB free, was 135 GB"), and services that went down and came back (needs JY-133's Kuma samples first). Not possible from stored data today: container restarts outside Joey, and NAS restarts (the NAS powers off every night, so it would say "restarted" every morning).

Data / privacy / budget notes:
- Data: one new media.db table, `server_last_visit(owner TEXT PRIMARY KEY, since TEXT, last_seen TEXT)`: one row per viewer ("you", "her"). Written after the page (a response background task), never during the render.
- Reads stored data only: `server_update_runs` (already read by the page as `last_requested`) and the connectors' runner history (already in memory, JY-226). No live call.
- Privacy: keyed by the Access identity's owner word, never an email. No identity (local dev, an unconfigured OWNER_EMAIL_YOU) means no sentence and no row. The Server page is private-only, so friends never see it.
- Budget: hub page render p95 ≤ 50 ms. The render adds one primary-key SELECT, and a scan of the runner-history lines after the visit's start, kept per viewer and visit so a reload does not scan again.

## Problem
P8 from the 2026-10-19 Server review: "updates applied, containers restarted, sweeps that failed and recovered, since the owner's last Server visit (per-owner timestamp in media.db)". Why: "Georgina never reads logs; this is the sentence she would want."

## Acceptance criteria
For option A:
1. A visit starts when the viewer opens Server more than 30 minutes after their last view. The sentence compares against the end of their previous visit and stays the same for the whole visit.
2. First visit ever (no row): no sentence. No identity: no sentence, and nothing is written.
3. Updates: each container with an Update now / Update all request after the visit's start is named, in request order: "Sonarr was updated", "Sonarr and Radarr were updated", "Sonarr, Radarr and 2 more were updated".
4. Feeds: a connector with at least one failed sweep after the visit's start whose latest sweep is OK: "wud failed 3 times, then recovered" ("once" for one). Still failing: not in the sentence (Attention already says it). Not-configured connectors are left out.
5. Nothing to say: "Since your last visit 5h ago: nothing changed." The time uses the hub's "ago" words.
6. Rendered as `<p class="metaline sincevisit">` above Attention, on the Server page only.
7. The visit row is written after the page, never during the render: a test renders with media.db writes forbidden.
8. Per viewer: "you" and "her" each see their own last visit.
9. The suite only grows.

## Data
New table `server_last_visit` (above). No snapshot change.

## Performance budget
Hub page render, warm p95 ≤ 50 ms (row 1). Measured on the NAS by `scripts/budgets.py` at the full check (it renders without an identity, so it also needs one signed-in run to see the sentence's cost).

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
