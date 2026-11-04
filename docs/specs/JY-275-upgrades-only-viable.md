# JY-275 Upgrades: flag only a viable upgrade, with an Upgrade button

Status: building (2026-11-04, folds in JY-109 re-opened)
Size: M (the data cannot say "a better release exists" today; see Data)
Live risk: none
Area: `hub/templates/_upgrade_note.html`, `_library_row.html`, `media_requests.html`, `media_downloads.html`, `media_film.html`, `_arr_search.html`, `hub/media_upgrades.py`, `hub/media_upgrade_why.py`, `hub/static/control-surface.css` (`.upnote`), `tests/hub/`
Needs: none. Related: JY-302 (the "search missing / upgrades" bug) and JY-300 (merged Upgrades + Requests page, builds on this item). Neither is changed here.
Options page: yes, 2-3 options at desktop / iPad / phone / TV (see Options)

## Problem
B., 2026-11-02: "Blue below cutoff upgrade font and text is annoying."
"I only want it to show with w button to upgrade if there is an upgrade available."
"If there is one. Flag it blue and provide an upgrade button. If there is not, then there is no need to have it there."
Same ask under General and Activity. (Read here as: General = the library rows and the title page; Activity = Requests and Downloads > Upgrades. Question 3.)

## What the code does today
- `_upgrade_note.html` draws `.upnote` ("Below cutoff · have -> wants want") in `--upgrade` blue on library rows, Requests rows, the title page and the Downloads > Upgrades list.
- The note comes from the arr snapshot's cutoff-unmet list. `media_upgrades.py` says this does NOT mean a better release exists (WP-U1, 2026-10-21: every release for one show was rejected).
- The only check for a real candidate is "Why?" (`media_upgrade_why.py`): an interactive indexer search, 10-60 s, grabs nothing, answer kept 1 h per row.
- The title page already has a "Search for upgrade" button (`_arr_search.html`) shown for any below-cutoff title.

## Acceptance criteria
1. A below-cutoff title with no known viable release shows no blue text and no upgrade button on library rows, Requests rows, the title page and Downloads > Upgrades.
2. A title with a known viable release shows one blue flag (a short word, no "Below cutoff · have -> wants" sentence) and an Upgrade button, on desktop and phone. On TV the flag shows and the button is reachable by D-pad.
3. The Upgrade button reuses the existing confirmed POST (`/media/title/{kind}/{tmdb}/upgrade`); no new write route.
4. "Viable" is decided as the pick says (Options). Whatever the rule, a page render never calls Radarr or Sonarr (the existing rule in `media_upgrade_why.py`).
5. Downloads > Upgrades lists only viable titles; with none it says "Nothing to upgrade." as it does now.
6. Words, not colour alone: the flag has text and is not blue-only (existing `.upnote` rule).
7. Tests: flag absent for a below-cutoff row with no viable answer; present with one; library, Requests, title page and Downloads each covered; JY-108 and WP-U1 tests updated, each change dated in this spec.

## Options (page to build)
- A. Flag only after a check. Rows show nothing until a "Why?"-style search finds an acceptable release; the result is kept and then flags the row. Slow to appear, but accurate and uses code that exists.
- B. Background check. A small job checks cutoff-unmet titles one at a time, kept 24 h, flags viable ones. Needs a new job and indexer traffic (live risk goes up, so the item becomes L).
- C. Quiet cutoff flag. Keep the cutoff list as the signal but drop the sentence: a small blue "Upgrade" chip plus the button on every below-cutoff title. Cheap, but it still shows titles where no release exists, which is B.'s complaint.

## Data
Snapshot `upgrades` (radarr / sonarr lists, `have`, `want`, `arr_id`, `sample` episode). No viable-release field today. A and B add a kept per-row result (A reuses `_memo` in `media_upgrade_why.py`, in memory 1 h; B needs a store).

## Performance budget
Media list / item page warm p95 <= 150 ms (library, Requests, title page); Hub page p95 <= 50 ms; joey-hub memory <= 200 MiB. Measured by the existing render timing on the preview.

## Out of scope
JY-302 (search missing / upgrades adding off-server titles). JY-300 (merging Upgrades and Requests). "Grab anyway" behaviour. The Search upgrades sweep on Requests / Downloads.

## Accept checklist
- [ ] Library, Requests, title page, Downloads: no blue text on a title with nothing to upgrade to.
- [ ] A viable title shows the blue flag and the Upgrade button; the button asks first.
- [ ] Phone and TV: same, with usable tap / D-pad targets.

## Questions for B.
1. How should "an upgrade is available" be decided?
   A. After a check ("Why?" style), kept and then flagged (recommended: no new job).
   B. A background job checks them all and flags viable ones (automatic, more indexer traffic, bigger item).
   C. Treat every below-cutoff title as upgradeable but drop the wording (does not meet "only if there is one").
2. Where does the button sit? A. on the row and the title page (recommended), B. title page only.
3. "General and Activity": A. library rows, title page, Requests and Downloads (recommended), B. other pages? Name them.

## Decisions in force (2026-11-04, B.: "Complete all for upgrades and searches. Recomplete 109.")
The spec's recommended answers; B. may still change them, so the rule lives in one place (`media_upgrades.is_viable`).
- Q1 = A. "Viable" = the row's kept Why? answer (`media_upgrade_why._memo`) holds at least one accepted release. The memo
  now lives 24 h (was 1 h), in memory: a hub restart forgets every check, so flags disappear until the next Why? or sweep.
- The "Search upgrades" sweep on Requests / Downloads (until now out of scope) also records results: after a started
  sweep the hub runs the Why? search for up to 25 cutoff-unmet rows, one at a time, in a background thread.
- Q2 (B., 2026-11-04): "Upgrade button should only sit in the requests/downloads page." The flag still shows on library
  rows and the title page; the title page keeps its existing "Search for upgrade" button unchanged.
- B., 2026-11-04: "If accepted, it should then try grab" - Upgrade opens the existing confirmed Grab of the kept answer's
  first accepted release (`/media/upgrades/why/{app}/{id}/grab`). Q3 = A: library rows, title page, Requests, Downloads.
- A page render never calls Radarr / Sonarr.

## JY-109 scope (re-opened, folded in)
For a show, the Why? answer folds out "Episodes below cutoff (N)": each episode code, its held quality and the result -
the sampled episode (the one searched) reads "viable · <quality>" or "rejected · <top reason>", the others "not checked".
The episode list comes from the arr snapshot: the feed now adds `below` (first 12 episodes, code + held quality) to each
Sonarr row (schema updated, sample snapshot regenerated). No new upstream call on render; still one search per row.

## Build notes (2026-11-04)
- Library rows and the title page: the flag only ("Upgrade available"; the list-view column reads "Upgrade").
- Requests and Downloads rows: an Upgrade button linking to Downloads' Grab confirm for the accepted release
  (`?why=<app>:<id>&why_step=grab&pick=<n>`); confirming sends the existing grab POST.
- Downloads > Upgrades lists viable rows; the others sit in a fold "Below cutoff, nothing better found yet (N)" with Why?.
- The lazy Search-now fragment's "Search for upgrade" is unchanged (it still shows for any below-cutoff title, with the
  "Below cutoff · …" sentence in its confirm).

## Test changes (dated 2026-11-04)
- test_media_upgrades.py (F4b/WP-U1): `note` is now FLAG-or-''; the sentence moved to `detail`; block splits rows / unchecked.
- test_media_upgrades_pages.py, test_media_upgrades_film.py: an autouse fixture marks the old noted rows viable; the
  fragment "Search for upgrade" tests keep their sentence (FILM_DETAIL); new unchecked / rejected / button tests.
- test_media_upgrade_why.py (WP-U1/JY-108): the Downloads row no longer shows the sentence; TTL test renamed; new
  viable-flag and JY-109 per-episode tests. test_arr_upgrades.py: Sonarr rows carry `below`.
- test_media_arr_sweep.py: an upgrades sweep starts the background check, a missing sweep does not.

## Shipped notes
