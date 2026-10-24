# JY-235 Gate ≤ 10 min on the NAS (proof after JY-227)

Status: building
Size: M
Live risk: deploy (measures real deploys; may change the gate's worker count)
Area: `deploy/deploy.sh` (pytest worker count only, criterion 3), `tests/` (any NAS-only hot spot found), this spec
Needs: JY-227 (faster tooling tests)
Options page: none: no screen

Split from JY-227 on 2026-10-24 (its criteria 3–5 and the NAS half of criterion 1). B.'s answers on JY-227 carry over: 1a (profile and fix first, `-n 3` only if still over 10 min), 2a (keep `tests/scripts/` in the gate), 3a (one profiled gate run on a quiet NAS is allowed).

## Problem
The full gate took 15.0–15.3 min (2026-10-23) and 16–26 min under load (2026-10-24) against a 10-minute budget. JY-227 cut the tooling tests' cost on the laptop (tests/scripts 136 → 95 s wall at `-n 4`). Whether that brings the NAS gate under 10 minutes is unproven.

## Acceptance criteria
1. A quiet-NAS profile: the `life-test` image run by hand on the NAS with `pytest -q -n 2 --durations=40 tests/` after JY-227 is deployed; the top hot spots and the wall time are recorded here, with `free -m` sampled during the run (available ≥ 1,200 MB, swap ≤ 1,273 MB).
2. Any NAS-only hot spot (≥ 20 s and fixable without weakening a test) is fixed (rule 4).
3. Only if the gate is still over 10 min after 1–2: `deploy.sh` runs the suite with `-n 3`, kept only if `free -m` sampled during a gate stays within the floors in criterion 1; otherwise reverted with the numbers recorded.
4. Three consecutive PASS deploys on a quiet NAS with `dur ≤ 600 s` in `deploy/history.log`; lines in the PR.
5. The full suite still runs before every deploy (rule 13).

## Data
None.

## Performance budget
Full gate ≤ 10 min; NAS available memory ≥ 1,200 MB and swap ≤ 1,273 MB during the gate.

## Options and the pick
None: no screen.

## Out of scope
CI speed; NAS hardware; moving tests out of the gate (JY-227 answer 2a).

## Accept checklist
- The profile, the three history lines and the memory samples in this spec / the PR.

## Questions for B.
Answers carried from JY-227 (B., 2026-10-24: "Approve all changes … just close it out"): 1a, 2a, 3a.

## Shipped notes
(filled at close-out)
