# JY-120 Her view with no list: wording

Status: shipped 2026-10-27
Size: S
Live risk: none
Area: `hub/media_library.py`, `hub/media_pages.py`, `tests/hub/test_media_library_pages.py`
Needs: none
Options page: none: tiny change that follows an existing pattern (the 2026-10-22 "No marks for her yet" line)

## Questions for B.
1. In her view, before she has a Jellyfin list of her own, what should the empty "Not yet watched" carousel say? (**built as: A**)
   - **A) "No marks for her yet"** (recommended, built as): the same words her TV "Continue watching" already uses since 2026-10-22. Without her list there is no way to say what she has not watched, so "Nothing left to watch" is wrong; it claims she has seen everything. Films and TV both.
   - B) Leave "Nothing left to watch". No change; the line stays untrue for her.
   - C) New words, "Her list is not set up yet", for all three of her no-list lines. More to read, and it changes the 2026-10-22 line B. already accepted.
   Stays as is in every option: films' "Continue watching" in her view ("Nothing in progress" when her resume list is empty: that list comes from Jellyfin's own resume, not from marks) and "New" ("Nothing new this week": it counts arrivals, not marks).

## Problem
HITLIST: "Her view with no list: wording. 'Nothing left to watch' / 'Nothing in progress' (decision)". Source: DECISIONS 2026-10-22. On 2026-10-22 her TV "Continue watching" was fixed to say "No marks for her yet" when she has no list. Her "Not yet watched" carousel (films and TV) has the same cause and still says "Nothing left to watch"; the test `test_her_view_without_her_list_has_no_filter_chips` pins that text.

## Acceptance criteria
1. In her view with no list of her own (`marks` false), the "Not yet watched" carousel's empty line is `No marks for her yet`, for films and TV. Test: `tests/hub/test_media_library_pages.py` (red on the old text).
2. Her TV "Continue watching" keeps `No marks for her yet`; her films' "Continue watching" keeps `Nothing in progress` (resume list); "New" keeps `Nothing new this week`.
3. With marks (her list present, or the household view), "Not yet watched" still says `Nothing left to watch` when empty.

### Test change (dated)
2026-10-26: `test_her_view_without_her_list_has_no_filter_chips` asserted `"Nothing left to watch" in b` for her no-list view. It now asserts `No marks for her yet`; that is the point of this item. No test is deleted or weakened.

## Data
None.

## Performance budget
None apply (one string choice).

## Out of scope
The filter chips (already hidden without marks). The Tonight picks.

## Accept checklist
`/media/movies?owner_view=her&s=unwatched` and `/media/tv?owner_view=her&s=unwatched` with no list for her read "No marks for her yet". The household view is unchanged.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #189, squash-merged as `7802f2f` (7802f2fc793ed2afa2929f9715d3bf00a755ca5d).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-27: JY-246: A · JY-120: A · JY-151: A · JY-150: A · JY-121: A · JY-133: A · JY-134: A · JY-052: A · JY-053: A A A A · JY-230: go · JY-231: go approve · JY-232: go s1 · deploy"
- Follow-ups: none
