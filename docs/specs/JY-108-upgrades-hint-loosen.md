# JY-108 Upgrades: loosen the profile-minimum hint

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/media_upgrade_why.py`, `hub/templates/_upgrade_why.html` (only if the wording changes), `tests/hub/test_media_upgrade_why.py`
Needs: none
Options page: none: one line of text on an existing card; the choice is words, below

Source: HITLIST JY-108 (seed: "Upgrades: profile-minimum hint only when every rejection").

## Problem
On Downloads > Upgrades, "Why?" asks Radarr/Sonarr what it would grab. When the profile's minimum custom-format score is what blocks the title, the card shows a hint ("The 1080p profile's minimum custom-format score (1000) rejects every release for this title - lower it in Sonarr > Settings > Profiles, or grab one anyway."). The hint may be missing when only some releases fail for that reason.

## What the code does today (evidence)
`summarize()` in `hub/media_upgrade_why.py` sets `cf_every` true only when all three hold: at least one release is rejected, none is accepted, and every rejected release carries a `cf:<minimum>` reason. One release rejected for anything else (for example "Unknown Series") clears it, and the hint is None.
The tests pin this on purpose: `test_summarize_hint_only_when_the_minimum_rejects_everything` (a 30-release answer where one release lacks the minimum reason gives `hint is None`) and the exact sentence in the test above it. The hint sentence says "rejects every release", so it is only true under today's rule.

## Why the sentence changes
Any looser rule makes "rejects every release for this title" untrue (some releases fail for other reasons), so the sentence now carries counts. The rule choice also changes an existing test's intent.

## Acceptance criteria
1. With nothing accepted, and the profile minimum a reason on the first rejected release or on at least half of the rejected releases, `summarize()["hint"]` is: "The 1080p profile's minimum custom-format score (1000) rejects N of M releases for this title — lower it in Sonarr › Settings › Profiles, or grab one anyway." N is the rejected releases that carry the minimum, M all releases. "every release" is used only when N = M.
2. Where the condition is not met, `hint is None` (three cases: something accepted; the minimum on fewer than half and not on the first rejected release; the minimum not involved).
3. The existing 30-release fixture with `unknown_has_cf=False` flips from `hint is None` to the hint ("29 of 30"). The old test `test_summarize_hint_only_when_the_minimum_rejects_everything` is rewritten for the new rule (dated in the Shipped notes).
4. The rendered card shows the hint with its state words (no colour alone); no other card line changes.
5. Red tests first: the half rule, the first-release rule, the "N of M" wording and the flipped fixture fail on the old code; the below-half case pins no hint.

## Data
None. Reads the kept interactive-search answer only; no new call on page render (rule 7).

## Performance budget
None apply (no new reads).

## Options and the pick
Options page: none (a line of text on an existing card). B. answered the two questions in chat on 2026-10-24: "JY-108: 1A 2A".
- **1A (rule):** show it when nothing is accepted and the profile minimum is a reason on the first rejected release (the app lists its best first) or on at least half of the rejected releases.
- **2A (sentence):** "The 1080p profile's minimum custom-format score (1000) rejects N of M releases for this title — lower it in Sonarr › Settings › Profiles, or grab one anyway." "every release" stays only when N = M.

## Out of scope
Grouped reasons, the top-5 list, Grab anyway, and the reason regexes.

## Accept checklist
Ask Why? on a title whose search answer has mixed rejections: the hint shows, reads plainly, and names the minimum.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #128, squash-merged as `ede027a` (ede027aa5834a00765ab9001c90dba77f1523236).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
