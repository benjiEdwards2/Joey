# JY-263 Image access check

Status: building
Size: S
Live risk: none
Area: hub/images.py (one gate), hub/img_access.py (new), one note line each in hub/media_item.py and hub/media_guest_home.py, tests/hub/test_img_access.py
Needs: none
Options page: none: no screen changes

## Problem
Found by the JY-262 review: `/img` has no viewer check for any ref, posters included, so anyone signed in could fetch any title's artwork by id. B., 2026-10-28: "1 sounds good." (the orchestrator's item 1: "closes a gap where anyone signed in could fetch any title's artwork by ID").

## Acceptance criteria
1. A friend (media front) cannot fetch `jf:` / `jfb:` / `jfb:<id>/<n>` or a stored Joey poster (`?v=`) for an id they were not shown. They get the same grey card an unknown id gets, with `Cache-Control: private, no-store`.
2. A friend can fetch images for ids in the shared library snapshot (movies, shows, latest) and for ids in their own reads (item read: title, show, seasons, episodes, cast; Continue watching / Recently watched). Headers are the ones today (`public, max-age=2592000, immutable`).
3. Household (`you`, `her`) on the media front, and the private front: unchanged.
4. No network call decides it: a set lookup per request; the snapshot id set is re-read at most every 30 s.
5. TMDB and Radarr/Sonarr refs are not checked (public data / unchanged).
6. A request on the media front with no identity gets the ordinary 404 page (GuestGate already redirects before this; the check is the second lock).

## Data
No migration. In memory only: `img_access._viewers` (jellyfin user id -> id set, 256 viewers, 20,000 ids each, restarts from the next read when full) and a 30 s snapshot id set. Reads the `jellyfin` snapshot through `shell.get_snapshots` (the media front's scrubbed view).

## Performance budget
None of the CLAUDE.md rows move. Per image: two set lookups under one lock.

## Options and the pick
No options page. B., 2026-10-28: "1 sounds good."

## Out of scope
- Per-user Jellyfin library rules: the snapshot is server-wide, so an id in it is visible to every friend, as the Home shelves already are.
- The public CDN cache: hits are `public ... immutable` as before, so once one friend has been served an image a cache in front of the hub may serve that URL to others. Not changed here (the headers must not change).

## Accept checklist
Sign in as a friend: Home, a film, a show with seasons, Continue watching all show their artwork. A household-only id in the URL gives the grey card.

## Tradeoff and failure mode
After a restart a friend's own set is empty until their next page read, which runs before the page's images are requested. A cold `/img` for an episode/season/cast id then shows the grey card (never a wrong image) until that read.

## Questions for B.
None.

## Shipped notes
PR and measured numbers: see the PR.
