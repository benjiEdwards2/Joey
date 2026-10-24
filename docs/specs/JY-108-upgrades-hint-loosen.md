# JY-108 Upgrades: loosen the profile-minimum hint

Status: spec
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

## Why this stops at the spec
Any looser rule makes the sentence "rejects every release for this title" untrue (some releases fail for other reasons). The loosened hint therefore needs a new sentence, which is new wording and B.'s call. The rule choice also changes an existing test's intent.

## Acceptance criteria (draft, for the option B. picks)
1. With no accepted release and the rule's condition met, `summarize()["hint"]` is the picked sentence, naming the profile minimum number and "Radarr/Sonarr > Settings > Profiles".
2. A release set where the condition is not met still gives `hint is None` (two cases: something accepted; the minimum not involved).
3. The existing 30-release fixture with `unknown_has_cf=False` flips from `hint is None` to the hint. That edit to `test_summarize_hint_only_when_the_minimum_rejects_everything` is dated in this spec's Shipped notes.
4. The rendered card shows the hint with its state words (no colour alone); no other card line changes.
5. Red test first: the flipped fixture fails on the old code.

## Data
None. Reads the kept interactive-search answer only; no new call on page render (rule 7).

## Performance budget
None apply (no new reads).

## Out of scope
Grouped reasons, the top-5 list, Grab anyway, and the reason regexes.

## Accept checklist
Ask Why? on a title whose search answer has mixed rejections: the hint shows, reads plainly, and names the minimum.

## Questions for B.
**1. Which rule shows the hint?**
- **1A (recommended):** show it when nothing is accepted and the profile minimum is a reason on the first rejected release (the app lists its best first) or on at least half of the rejected releases. Smallest change from today, still one number in the sentence. Needs 2.
- **1B:** show it when nothing is accepted and the minimum is a reason on any rejected release. Loosest. Risk: fires when one stray release has it and the real blocker is something else.
- **1C:** leave as is ("every release only"). Close JY-108 as won't do.

**2. New sentence (needed for 1A/1B).**
- **2A (recommended):** "The 1080p profile's minimum custom-format score (1000) rejects N of M releases for this title - lower it in Sonarr > Settings > Profiles, or grab one anyway." Counts keep it true under any rule; "every release" stays only when N = M.
- **2B:** "... rejects most releases for this title ..." (no counts).
- **2C:** keep today's sentence for N = M, and a second sentence "The profile's minimum custom-format score (1000) rejects the best release too." otherwise.

Answer as "1A, 2A".

## Shipped notes
Not built. Spec only.
