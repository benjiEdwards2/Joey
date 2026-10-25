# JY-197 U11 TV docs sweep

Status: shipped 2026-10-25
Size: S
Live risk: none
Area: `docs/tv-release.md`, `hub/README.md`, this spec
Needs: JY-187 to JY-196 and JY-248 (all on main)
Options page: none: docs only.

## Problem
The TV UI round (JY-042) is on main. The docs still describe the old TV mode (six columns, rating chips, an Overview pill) and the release runbook does not say that shell 1.0.2 is held.

## Acceptance criteria
1. `docs/tv-release.md` says 1.0.2 (JY-191, PR #151) is pending, that merging it is the release (`tv.yml` fires on merge to `main`), and that it is merged only in a TV session with B.
2. `hub/README.md` "Guest surface and TV mode" has one block describing the new behaviour per area (JY-187 to JY-196, JY-248) and says it supersedes the older lines.
3. The mockups README is not in this repo (`docs/mockup/` has no README); the project-folder copy is outside this item.
4. Docs only: no code, test, CSS or `tv/` change.
5. Outside the repo (plain files): `JoeyTV\TV_UI_PLAN.md` marks each U-row's state; the grouped TV-session checklist and B.'s Gate 1 picks are recorded there (the project's DECISIONS, HANDOVER and DEFERRED files are archived with a banner, so they are not edited).

## Data
None.

## Performance budget
None: no runtime change.

## Questions for B.
None.

## Accept checklist
1. Read the `hub/README.md` TV block and `docs/tv-release.md` state line; say `accepted` or what to change.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #174, squash-merged as `afef649` (afef649640ebef5806fc520bfe9a70ebe4658c74).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
