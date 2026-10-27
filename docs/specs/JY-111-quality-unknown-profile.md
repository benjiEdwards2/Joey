# JY-111 Old arr profile id: fallback Quality line

Status: building (built ahead on the recommended option, option B, before B. picks; 2026-10-27)
Size: S
Live risk: none on render. The switch is the existing live arr write, only on B.'s confirm tap (never on render)
Area: `hub/media_quality.py`, `hub/templates/_quality_block.html`, one call in `hub/media_film.py`, tests
Needs: none (JY-118 touches other lines of `hub/media_film.py`; expect a trivial rebase if it merges first)
Options page: `JoeyTV/review/decisions-2026-10-27/options.md` (JY-111: B recommended)

## Problem
Titles still on a Radarr / Sonarr quality profile id from before the 2026-10-06 profile mirror show no Quality line, because `describe()` finds no matching profile and `block()` returns None. They cannot be switched to 1080p or 4K from Joey.

## Acceptance criteria
1. A title that is in the app, whose profile id is not in the app's current profile list, shows "Quality · unknown profile" with one switch button per target: the default profile (1080p) and the first 4K profile, each "Switch to <name>".
2. A tap on a button opens the existing inline confirm panel for that profile ("Switch <title> to <name>?", Radarr / Sonarr "will look for ... and keep what it has until it arrives"). Only the confirm tap writes (the existing POST). Render, the idle line and the confirm panel never write.
3. After the switch the line heals to the ordinary "Quality · <name>" with its usual Switch button.
4. Without JS: the buttons are links to `?quality_ask=1&quality_profile=<id>`, and the page draws the same panel. A profile id that is not one of the two targets is ignored (the idle line, no form).
5. Shows work the same as films.
6. Still hidden: the title is not in the app, or the profile list is unreadable (nothing to offer).
7. A title on a known profile is unchanged. The old test that pinned "unknown id → hidden" is replaced (dated in the test: 2026-10-27).

## Data
No tables. No new calls: the page's lazy-loaded quality line already reads the arr entry and the profile list.

## Performance budget
No new reads. The quality line stays lazy-loaded.

## Options and the pick
Option B (recommended). A (B. re-saves the titles in the Mass Editor) and C (leave it) were not built. B.'s pick: pending.

## Out of scope
Counting the affected titles (needs a live read). Changing the 4K-chip on the Requests page. An entry with no profile id at all also shows the fallback line (same code path).

## Accept checklist
Open a title that was on an old profile: "Quality · unknown profile  Switch to 1080p  Switch to 4K". Tap one, confirm: the line becomes "Quality · 1080p" or "Quality · 4K".

## Questions for B.
None (B. picks A / B / C on the options page).

## Shipped notes
