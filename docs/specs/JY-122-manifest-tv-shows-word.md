# JY-122 Manifest shortcut "TV Shows"

Status: shipped 2026-10-24
Size: S
Live risk: none
Area: `hub/static/manifest-media.webmanifest`, `tests/hub/test_media_phone_nav.py`
Needs: none
Options page: none: follows an existing pattern (the nav's own section words)

## Problem
HITLIST: "Manifest shortcut 'TV Shows'. Nav-tidy leftover." Nav-tidy (2026-10-13) made every section label sentence case: the section is "TV shows". The Joey Media manifest shortcut still said "TV Shows" (the guest manifest already says "TV shows").

## Acceptance criteria
1. The private Media manifest's shortcut reads "TV shows"; its other shortcuts and its `short_name` ("TV") are unchanged.
2. A test ties every shortcut name to the nav section label for the same URL, so the words cannot drift again.
3. Dated pin change: 2026-10-24, `test_joey_media_manifest_is_valid_and_served` pinned "TV Shows"; now "TV shows" per HITLIST JY-122.

## Data
None.

## Performance budget
None affected.

## Options and the pick
None: follows an existing pattern.

## Out of scope
Home-screen shortcuts already installed on a phone keep the old name until the PWA is re-added (the browser caches the manifest).

## Accept checklist
`/static/manifest-media.webmanifest` lists "TV shows".

## Questions for B.
None.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #83, squash-merged as `f23911d` (f23911d18faa893c23ce77e2df5f41f42890615f).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-24: Approve all changes. If I dont need to review any directions of changes, etc. Just close it out and apply the acceptance."
- Follow-ups: none
