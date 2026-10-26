# JY-151 Long TV pill names

Status: shipped 2026-10-27
Size: S
Live risk: none
Area: `hub/media_awards_pages.py` (`short_name`), `tests/hub/test_awards_ballot.py`
Needs: none
Options page: none: tiny change that follows an existing pattern (`short_name` already strips "Best " / "Feature" / "Writing (X)")

## Questions for B.
1. How far should `short_name` shorten the long Emmy-style TV category names on a ballot pill? (**built as: A**)
   - **A) Cut the " in a ... Series / Movie" clause to its genre word in brackets, and drop a trailing " or Movie"** (recommended, built as). "Supp. Actress in a Limited or Anthology Series or Movie" becomes "Supp. Actress (Limited)"; "Lead Actor in a Drama Series" becomes "Lead Actor (Drama)"; "Limited or Anthology Series or Movie" becomes "Limited or Anthology Series". Film names that say "in a Leading Role" are untouched. The Details fold still shows the full name. Round 1 of this item dropped the clause entirely; review found that made Drama, Comedy and Limited all "Lead Actor" (Emmys 77, SAG, Critics' Choice 30), and the Winners people strip would show three people under one caption. The bracketed word keeps every short name in an edition different, for the cost of one short word per pill.
   - B) A, and also strip " for a ... Series" (Directing / Writing / Casting / Cinematography): "Writing for a Drama Series" becomes "Writing". Shortest, but the Drama / Comedy writing and directing categories then collide, and two tests that pin "Writing for a Drama Series" move too.
   - C) Leave the names as they are. The Emmys page stays about 3,800 px tall on a phone.

## Problem
HITLIST: "Long TV pill names: add a strip rule in `short_name` (decision)". Source (BACKLOG, C3 eyes-on): "TV pill names are long ('Supp. Actress in a Limited or Anthology Series or Movie · ...'; Emmys page 3,831 px). Ready once decided (one rule + parametrised test)." Pills wrap to two lines on a phone and make each row taller.

## Acceptance criteria
1. `short_name("Outstanding Supporting Actress in a Limited or Anthology Series or Movie")` is `Supp. Actress (Limited)`; `... Supporting Actor in a Comedy Series` is `Supp. Actor (Comedy)`; `... Lead Actor in a Drama Series` is `Lead Actor (Drama)`; SAG's `... Male Actor in a Television Movie or Limited Series` is `Performance by a Male Actor (Television Movie)`; `Outstanding Limited or Anthology Series or Movie` is `Limited or Anthology Series`. Test: the parametrised `test_short_pill_names` in `tests/hub/test_awards_ballot.py` (red on the old code).
2. Film names are unchanged: `Best Actor in a Leading Role` is `Actor in a Leading Role`, `Best Actor in a Supporting Role` is `Actor in a Supp. Role`.
3. Every other existing `short_name` case still passes (including `Writing for a Drama Series`).
3a. No two categories of one edition share a short name, on every recorded Wikipedia edition page (`wp_*` fixtures) and the recorded 97th Oscars. Test: `test_no_two_categories_of_one_edition_share_a_short_name` and `test_no_two_oscars_categories_share_a_short_name`. (A page that lists the same raw name twice, such as the 20th Golden Globes, is the page's own and is not counted.) The Winners people strip captions with the same names, so it is covered too.
4. The Details fold (`cats[].name`) keeps the full category name.

### Test change (dated)
2026-10-26: the `short_name` case `("Outstanding Supporting Actor in a Comedy Series", "Supp. Actor in a Comedy Series")` now expects `Supp. Actor (Comedy)`. Review round 1 (same day): the first build expected `Supp. Actor` and collapsed distinct categories; fixed with the bracketed genre word. This is the point of the item; no test is deleted or skipped.

## Data
None.

## Performance budget
None apply (one string rule; pill text is shorter).

## Out of scope
The phone page height (JY-150).

## Accept checklist
`/media/tv/awards` (Emmys): pills read "Supp. Actress (Limited)", "Lead Actor (Drama)", "Limited or Anthology Series"; the Details fold still shows full names; the Oscars page is unchanged.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #192, squash-merged as `3fb4fdb` (3fb4fdb7d26db930ae172514235722b85d7a9cfa).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-27: JY-246: A · JY-120: A · JY-151: A · JY-150: A · JY-121: A · JY-133: A · JY-134: A · JY-052: A · JY-053: A A A A · JY-230: go · JY-231: go approve · JY-232: go s1 · deploy"
- Follow-ups: none
