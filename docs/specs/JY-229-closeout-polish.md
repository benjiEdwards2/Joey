# JY-229 close-out polish

Status: spec
Size: S
Live risk: none (dry-run reporting and tests only; the merge and deploy paths do not change)
Area: `scripts/joey_closeout.py`, `tests/scripts/`
Needs: JY-011 (shipped)
Options page: none: no screen

Source: JY-011's first live uses (JY-011, JY-030), 2026-10-23.

## Problem
`joey.py close-out --dry-run` reports `docs.1` as FAIL before a merge, because the item's spec reaches `main` only when the PR merges, so every dry run ends "REFUSED" although nothing is wrong. And `tests/scripts/` takes about 7 minutes serially on the laptop, mostly in real git subprocesses, which slows every builder's local check.

## Acceptance criteria
1. In `--dry-run`, when the PR is not merged yet, `docs.1` looks for the spec on the PR head instead of `origin/main`, and reports DRY ("would find the spec after the merge") when it is there; it still FAILs when the spec is missing from the PR head too. The dry run of an otherwise ready PR ends with no FAIL and exit 0.
2. Real runs are unchanged (`docs.1` reads `origin/main` after the merge).
3. `tests/scripts/` runs in under half its current serial time on the laptop (measure before and after; numbers in the PR), without dropping or weakening any test (rule 4): share one throwaway origin/clone per module where a test only reads it, keep fresh repos only where a test writes.
4. Tests: the dry-run DRY and FAIL cases for `docs.1`.

## Data
None.

## Performance budget
None of the hub budgets apply. Full gate time (JY-227) must not grow.

## Options and the pick
None: no screen.

## Out of scope
Any change to gates, merge, deploy or verify.

## Accept checklist
- CI green; review posted; a dry run against an open PR ends with exit 0 (output in the PR); before/after test timings in the PR.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
