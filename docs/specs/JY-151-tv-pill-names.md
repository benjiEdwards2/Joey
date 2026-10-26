# JY-151 Long TV pill names

Status: spec (built as option A; waiting for B.'s pick)
Size: S
Live risk: none
Area: `hub/media_awards_pages.py` (`short_name`), `tests/hub/test_awards_ballot.py`
Needs: none
Options page: none: tiny change that follows an existing pattern (`short_name` already strips "Best " / "Feature" / "Writing (X)")

## Questions for B.
1. How far should `short_name` shorten the long Emmy-style TV category names on a ballot pill? (**built as: A**)
   - **A) Strip the " in a ... Series / Movie" clause and a trailing " or Movie"** (recommended, built as). "Supp. Actress in a Limited or Anthology Series or Movie" becomes "Supp. Actress"; "Lead Actor in a Drama Series" becomes "Lead Actor"; "Limited or Anthology Series or Movie" becomes "Limited or Anthology Series". Film names that say "in a Leading Role" are untouched. The Details fold still shows the full name. This is the rule the HITLIST row names.
   - B) A, and also strip " for a ... Series" (Directing / Writing / Casting / Cinematography): "Writing for a Drama Series" becomes "Writing". Shortest, but drops the one word that says which series group, and two tests that pin "Writing for a Drama Series" move too.
   - C) Leave the names as they are. The Emmys page stays about 3,800 px tall on a phone.

## Problem
HITLIST: "Long TV pill names: add a strip rule in `short_name` (decision)". Source (BACKLOG, C3 eyes-on): "TV pill names are long ('Supp. Actress in a Limited or Anthology Series or Movie · ...'; Emmys page 3,831 px). Ready once decided (one rule + parametrised test)." Pills wrap to two lines on a phone and make each row taller.

## Acceptance criteria
1. `short_name("Outstanding Supporting Actress in a Limited or Anthology Series or Movie")` is `Supp. Actress`; `... Supporting Actor in a Comedy Series` is `Supp. Actor`; `... Lead Actor in a Drama Series` is `Lead Actor`; `Outstanding Limited or Anthology Series or Movie` is `Limited or Anthology Series`. Test: the parametrised `test_short_pill_names` in `tests/hub/test_awards_ballot.py` (red on the old code).
2. Film names are unchanged: `Best Actor in a Leading Role` is `Actor in a Leading Role`, `Best Actor in a Supporting Role` is `Actor in a Supp. Role`.
3. Every other existing `short_name` case still passes (including `Writing for a Drama Series`).
4. The Details fold (`cats[].name`) keeps the full category name.

### Test change (dated)
2026-10-26: the `short_name` case `("Outstanding Supporting Actor in a Comedy Series", "Supp. Actor in a Comedy Series")` now expects `Supp. Actor`. This is the point of the item; no test is deleted or skipped.

## Data
None.

## Performance budget
None apply (one string rule; pill text is shorter).

## Out of scope
The phone page height (JY-150).

## Accept checklist
`/media/tv/awards` (Emmys): pills read "Supp. Actress", "Lead Actor", "Limited or Anthology Series"; the Details fold still shows full names; the Oscars page is unchanged.

## Shipped notes
(none yet)
