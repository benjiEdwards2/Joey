# JY-030 Stale "Grouped" toolbar comment in `tv.css`

Status: building
Size: S
Live risk: none
Area: `hub/static/tv.css` (comments only)
Needs: Phases 1–3 (shipped)
Options page: none: a comment fix that changes nothing on screen

Phase 4 pilot item 1: proves the whole loop on the smallest possible change. Source: the old BACKLOG (archived 2026-10-23): "`hub/static/tv.css:99` comment names the "Grouped" toolbar, which the flat grid removed — Ready, trivial." The comment has since moved to about line 111.

## Problem
A comment in `hub/static/tv.css` describes a "search / Grouped / sort / layout" toolbar. The flat library grid removed the Grouped control, so the comment misleads the next person who edits the TV grid.

## Acceptance criteria
1. Every comment in `hub/static/tv.css` that names a "Grouped" toolbar control is corrected to match the toolbar the templates render today (check the library templates in `hub/templates/`; name only controls that exist).
2. Only comments change: no selector, property or value changes. `git diff -w` shows changes inside `/* … */` only.
3. If the CSS file carries a cache-busting version that tests pin, nothing about it changes (a comment-only edit needs no version bump unless a test says so; run the tests that read `tv.css`).
4. The tests that read `hub/static/tv.css` pass (find them with a grep in `tests/`).

## Data
None.

## Performance budget
None apply (no rule changes).

## Options and the pick
None: no screen change.

## Out of scope
Any other stale comment or CSS clean-up (note it in the PR instead).

## Accept checklist
- Read the one-hunk diff on the PR: the comment names the controls the TV library toolbar really has.
- CI green.

## Questions for B.
None.

## Shipped notes
(filled at close-out)
