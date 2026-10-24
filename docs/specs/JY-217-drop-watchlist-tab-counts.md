# JY-217 Remove unused watchlist `tab_counts()` read in `media_frame()`

Status: building
Size: S
Live risk: none
Area: `hub/media_home.py`, `hub/media_watchlist.py`, `tests/hub/test_media_phone_nav.py`
Needs: none
Options page: none: follows an existing pattern (housekeeping, no screen change)

## Problem
HITLIST: "Remove unused `tab_counts()` read in `media_frame()`. Nav-tidy leftover." Every Media page ran `media_watchlist.tab_counts()`, which queried the watchlist for `wl_movie` / `wl_tv` counts. Nothing reads those keys: the Watchlist tab left the nav in nav-tidy (2026-10-13) and `media_nav.nav_context` only uses `to_rate`, `to_rate_movie` and `to_rate_tv`.

## Acceptance criteria
1. `media_frame()` no longer reads the watchlist counts; the nav (sections, tabs, counts) is unchanged.
2. The now-dead `media_watchlist.tab_counts()` and the `media_watchlist` import in `media_home.py` are removed. `count_not_on_server` and `on_server_keys` stay (other callers and their own tests).
3. Test: `test_media_frame_reads_no_watchlist_counts` (new; failed on the old code) shows a Media page draw runs no watchlist count query.

## Data
None.

## Performance budget
Slightly less work per Media page (one fewer query); no budget risk.

## Options and the pick
None: follows an existing pattern.

## Out of scope
`wl.count_not_on_server` itself (still tested in `test_media_watchlist.py`; now only used by its own test: flagged for B., not removed).

## Accept checklist
Media pages and their nav counts look the same.

## Questions for B.
None.

## Shipped notes
