# JY-150 Ballot page height at 375 px

Status: shipped 2026-10-27
Size: S
Live risk: none
Area: `hub/media_awards_pages.py` (`FIRST_ROWS`), `tests/hub/test_awards_ballot.py`, `hub/README.md` (two lines)
Needs: none
Options page: none: one constant; the numbers below are measured, and the screenshots are in the PR

## Questions for B.
1. The ballot page is 3,197 px tall at 375 px with the demo 97th Oscars (the review saw 3,166 px) against a 2,500 px target. What should change? (**built as: A**)
   - **A) Draw 7 rows on the first screen, not 12** (recommended, built as): page height 2,381 px at 375 px, under the target. No template or CSS change. The other rows still arrive in the same single request when the sentinel scrolls into view, so nothing is lost; only the first draw is shorter.
   - B) Draw 8 rows (the number in the BACKLOG note): 2,557 px, 57 px over the target.
   - C) Put "Details" on the tally line instead of its own line: about 490 px less (2,705 px with 12 rows), still 205 px over. Changes the row layout on every device, so it needs an options page first, and does not reach the target alone.
   - D) Accept 3,197 px and drop the target to match. Nothing changes.
   Measured by removing rows from the page in headless Chrome at 375 x 844, dpr 2: 12 rows 3,197 px, 9 rows 2,734, 8 rows 2,557, 7 rows 2,381, 6 rows 2,171.

## Problem
HITLIST: "Ballot page height at 375 px: 3,166 px vs 2,500 target (decision)". Source (BACKLOG, C3 eyes-on): "Page height at 375 px is 3,166 px vs the review's 2,500 target. Decision needed: accept, or `FIRST_ROWS` 12 to 8 (two test pins move), or put 'Details' on the tally line." Where the page height goes at 375 px (demo Oscars): 508 px of header and controls, 2,373 px for the 12 rows, 160 px for the shorts fold and the people strip, and the rest is the bottom nav and padding.

## Acceptance criteria
1. `FIRST_ROWS` is 7. The films ballot page draws 7 rows in the main list (the folded shorts are separate) and `ballot.rest` counts the others. Test: `tests/hub/test_awards_ballot.py` (red on the old code: 3 failed).
2. The rows part route still brings every row after the first 7 (`want[7:]`), one request, same filter and sort.
3. Page height at 375 px with the demo Oscars is at most 2,500 px (measured 2,381 px; numbers in the PR).
4. The categories view, the TV shelves view and the filters are unchanged.

### Test changes (dated)
2026-10-26: four pins move with the constant, none deleted or loosened: `FIRST_ROWS == 12` and `rest == 28` become `7` and `33`; the rows-part test slices at 7, not 12, and counts 33 rows, not 28; the headline filter's `rest` (ten Best Picture nominees) goes from 0 to `10 - FIRST_ROWS`. One test is added (the page draws `FIRST_ROWS` rows). The test names say "seven" instead of "twelve".

## Data
None.

## Performance budget
None apply (a shorter first render; the deferred request is unchanged). Page render budgets are measured on the NAS at close-out.

## Out of scope
The row layout (option C), the TV pill names (JY-151), the year strip.

## Accept checklist
`/media/movies/awards` on a phone: seven films, then the rest load as you scroll to the bottom of them; the page is about 2,400 px tall at 375 px. Desktop, iPad and TV widths show the same seven rows first and load the rest on scroll.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #194, squash-merged as `936b440` (936b44028001a4d86a41124048fd979a2aeb8e6b).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
