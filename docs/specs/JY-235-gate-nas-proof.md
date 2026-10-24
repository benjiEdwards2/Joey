# JY-235 Gate ≤ 10 min on the NAS (proof after JY-227)

Status: shipped 2026-10-24
Size: M
Live risk: deploy (measures real deploys; may change the gate's worker count)
Area: `deploy/deploy.sh` (the gate's `docker run` only: tmpfs /tmp, criterion 2), `tests/` (any NAS-only hot spot found), this spec
Needs: JY-227 (faster tooling tests)
Options page: none: no screen

Split from JY-227 on 2026-10-24 (its criteria 3–5 and the NAS half of criterion 1). B.'s answers on JY-227 carry over: 1a (profile and fix first, `-n 3` only if still over 10 min), 2a (keep `tests/scripts/` in the gate), 3a (one profiled gate run on a quiet NAS is allowed).

## Problem
The full gate took 15.0–15.3 min (2026-10-23) and 16–26 min under load (2026-10-24) against a 10-minute budget. JY-227 cut the tooling tests' cost on the laptop (tests/scripts 136 → 95 s wall at `-n 4`). Whether that brings the NAS gate under 10 minutes is unproven.

## Acceptance criteria
1. A quiet-NAS profile: the `life-test` image run by hand on the NAS with `pytest -q -n 2 --durations=40 tests/` after JY-227 is deployed; the top hot spots and the wall time are recorded here, with `free -m` sampled during the run (available ≥ 1,200 MB, swap ≤ 1,273 MB).
   - Measured 2026-10-24 (orchestrator, quiet NAS). Deploy of e930710 (after JY-227): history `dur=1326s`.
   - `docker run --rm life-test python -m pytest -q -n 2 --durations=40 tests/`: wall 996 s, 3509 passed, 4 skipped. Slowest are SQLite-heavy hub tests (test_media_db migration 19.5 s, test_media_diary 15.6 s, many awards/media DB tests 6–8 s): the container's `/tmp` sits on the NAS's slow overlay disk. Memory: min available 1,401 MB, max swap 1,023 MB.
   - Same with `--tmpfs /tmp:rw,size=768m,mode=1777 -e TMPDIR=/tmp`: wall 197 s, 1 failure (`test_blocked_commit_is_a_fail_with_the_hook_message`: Docker's tmpfs defaults to noexec, so git skipped the test's hook). Min available 1,242 MB.
   - Same with `--tmpfs /tmp:rw,exec,size=512m,mode=1777 -e TMPDIR=/tmp` and `-o tmp_path_retention_policy=failed`: wall 192 s, 3509 passed, 4 skipped, 0 failed. Min available 1,381 MB (start 1,791), max swap 1,010 MB.
2. Any NAS-only hot spot (≥ 20 s and fixable without weakening a test) is fixed (rule 4). The hot spot is the disk under `/tmp`, not a test: the gate's `docker run` in `deploy.sh` now mounts `/tmp` as an `exec` tmpfs (512m) with `TMPDIR=/tmp` and pytest `-o tmp_path_retention_policy=failed` (suite 996 → 192 s on the NAS, memory inside the floors). No test changed.
3. Not needed (2026-10-24): with the tmpfs fix the suite is 192 s at `-n 2`, so the gate keeps `-n 2`; `-n 3` is not tried. Re-pointed pins in `tests/deploy/test_deploy_script.py` (2026-10-24): the gate's `docker run` string gained the tmpfs flags; offline, full-suite and `-n 2` assertions are unchanged, and a new test pins `exec`, `TMPDIR` and the retention option.
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
- Closed out with `scripts/joey.py close-out`.
- PR: #103, squash-merged as `d94660a` (d94660ac09384e5869942fb15555e6f742e7484e).
- Deploy: `2026-10-24T07:49:28Z PASS prev=1fe6af0 new=d94660a suite green, smoke ok tv=current end=2026-10-24T08:07:19Z dur=1071s`
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
