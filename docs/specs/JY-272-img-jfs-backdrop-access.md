# JY-272 `/img`: friend-access check for stored backdrops `jfs:<id>/1` and `/2`

Status: spec
Size: S
Live risk: none
Area: `hub/img_access.py` (`allowed()`), `hub/images.py` (the denied branch in `image()`, only if Question 1 changes it), `tests/hub/test_img_access.py`, `tests/hub/test_tmdb_logos_jy267.py` (read only unless a test moves)
Needs: none
Options page: none: tiny change that follows an existing pattern (the JY-267 `/logo` check)

## Problem
Found by the JY-267 review, 2026-11-02: JY-267 added the friend-access check for `jfs:<id>/logo` only. The two stored backdrops of a title, `jfs:<id>/1` and `/2` (JY-262), still skip it, so a friend can fetch a stored backdrop for a title their own Jellyfin user was never shown. `/jf:` and `/jfb:` images are already checked; this is the one gap left in `/img`.

## What the code does today
- `REF_RE` in `hub/images.py` accepts `jfs:<id>/1`, `jfs:<id>/2` and `jfs:<id>/logo`. `image()` splits it with `_kind_ident` (kind `jfs`, ident `<id>/<1|2|logo>`) and calls `img_access.allowed(request, kind, ident)` before anything is read.
- `allowed()` in `hub/img_access.py` returns True at once unless the front is the media front and the kind is `jf`, `jfb`, or `jfs` with an ident ending `/logo` (the `logo` local, added by JY-267). `jfs:<id>/1` and `/2` take the early True, so no friend lookup runs.
- For a checked kind: no signed-in viewer returns None (ordinary 404 page); a household member returns True; a friend goes to `friend_may_see(viewer, ident.partition("/")[0])`, a set lookup of the ids their own reads were shown plus the shared library snapshot. No Jellyfin call.
- When `allowed()` is False, `image()` answers a `jfs:.../logo` ref with a 404 (`Cache-Control: no-store`, so the page's `onerror` draws text), and any other ref with the SVG title card (`private, no-store`).
- Then `_stored()` serves the local backdrop file only when `&v=` is its published version; otherwise a `jfs` ref falls back to Jellyfin backdrop 0 (for `/1`) or 1 (for `/2`) through the `jfb` path, using the same ident id.
- Tests today: `tests/hub/test_img_access.py` covers the `jf` / `jfb` rules; `tests/hub/test_tmdb_logos_jy267.py::test_a_friend_gets_a_logo_only_for_a_title_they_may_see` covers the `/logo` rule (shown title 200 `image/png`, hidden title 404 `no-store`, body never the stored file). Nothing covers a friend on `jfs:<id>/1` or `/2`.

## Acceptance criteria
1. On the media front, a friend asking for `jfs:<id>/1` or `jfs:<id>/2` of a title they were not shown (not in their own reads, not in the shared snapshot) gets the same response as the same friend gets for `jfs:<id>/logo` of that title (Question 1 sets which), whether or not a stored file and a valid `v` exist for it. The body is never the stored file or Jellyfin's image.
2. A friend asking for `/1` or `/2` of a title they may see (read as them, or in the snapshot) is served exactly as today: stored file at a matching `v`, the Jellyfin fallback otherwise.
3. The owner and household members (`you`, `her`) get every `/1` and `/2` as before; no signed-in viewer on the media front gets the ordinary 404 page, as for `jf`.
4. The private front (not the media front) is unchanged for all `jfs` refs.
5. `/logo`, `jf`, `jfb`, `radarr`, `sonarr` and `tmdb` refs behave exactly as before.
6. The check is the existing set lookup: no new network call, no new file read, no new state in `img_access.py`.
7. Tests, added to `tests/hub/test_img_access.py`: friend denied `/1` and `/2` for a hidden id; friend allowed for a shown id (read as them) and for a snapshot id; household and owner allowed for a hidden id; the denied response equals the `/logo` one; a hostile ref is still rejected by `REF_RE`.
8. All existing tests stay green, including `test_tmdb_logos_jy267.py` and `test_img_access.py`; the full suite count is reported in the PR.

## Data
None. No schema, store or env change.

## Performance budget
`/img` p95 unchanged (<= 50 ms for a stored hit, in-process): the added work is one set lookup per `/1` or `/2` request from a friend. Measured in the test fixture and reported in the PR.

## Out of scope
The JY-263 tradeoff (an id in the shared snapshot is visible to every friend), new cache headers, the `jfb` / `jf` rules, the poster store, and any page or template.

## Accept checklist
- [ ] A friend's browser cannot load a hidden title's stored backdrop 1 or 2 by URL.
- [ ] The same friend still sees backdrops on every title page they can open.
- [ ] The owner's pages (Home, title page, Discover) show backdrops as before.

## Questions for B.
1. What does a friend see for a hidden backdrop? A. A 404 with no-store, as `/logo` does (recommended; the page's `onerror` or the browser draws nothing, and one rule covers all `jfs`). B. The SVG title card, as `jf` and `jfb` do.

## Shipped notes
