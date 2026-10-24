# JY-115 Connector: flag series with 0 Jellyfin episodes at source

Status: spec
Size: S
Live risk: none
Area: `connectors/feeds/jellyfin.py`, `connectors/schema/data/jellyfin.schema.json`, `hub/media_library.py`, `tests/connectors/`, `tests/hub/`
Needs: none
Options page: none: no screen change (the page must not change)

Source: HITLIST JY-115 (seed: "media_status connector keeps episodes: 0 series").

## Problem
A series Jellyfin lists with no episode (Sonarr made its folder before any file arrived) must read as "waiting for the first episode", never "On server". The item asks the connector to mark such series explicitly, and the hub to read that mark instead of inferring from `episodes == 0`, with no change on the page.

## What the code does today (evidence)
1. The premise names the wrong connector. `connectors/feeds/media_status.py` only probes the apps' health ports and carries no series. The series list comes from `connectors/feeds/jellyfin.py` `_shows()`.
2. That connector does not keep them. Since 2026-10-10 it skips any series whose `RecursiveItemCount` is exactly 0 (`jellyfin.py` `_shows()`; test `tests/connectors/test_jellyfin_library.py`, "an unaired show Sonarr added is an empty Jellyfin Series ... not listed").
3. The only `episodes: 0` row that can still reach the snapshot is a series whose count is missing (`int(item.get("RecursiveItemCount") or 0)`); the connector comment says a missing count "is not 0 (kept)".
4. The hub infers in two places, both pinned by tests: `media_library.empty_series(row)` (`"episodes" in row and not row["episodes"]`; used by My shows, watchlist keys, library links) and `empty_show` in `media_film.py` (no season has an episode, from the item's own read). The item page does not use the snapshot count at all.
So "the connector keeps them" is not true. A flag on kept rows would only ever mark the missing-count case, which today is ambiguous: a missing count reads as 0, and `empty_series` then treats the show as empty although Jellyfin never said so.

## Why this stops at the spec
The item has readings that pull opposite ways, and the choice changes what the snapshot holds and what other pages see, so it is B.'s call:
- Dropping at the source (today) means the hub never sees the empty series and cannot list it under "Waiting for the first episode" from Jellyfin data alone.
- Flagging means keeping them in the snapshot with a field, then every reader of `library.shows` must honour it (My shows, counts, shelves, Activity links, TV).

## Acceptance criteria (draft, for the option B. picks)
1. (1B) The connector keeps a counted-0 series and sets an explicit field (for example `empty: true`); a series with a count above 0 has `empty: false`; a series with no count has the field absent and is not treated as empty. Schema updated, fixtures carry the field.
2. `media_library.empty_series` reads the field, not `episodes`; rows without the field (older snapshots) are not empty, as today.
3. No page changes: `tests/hub/test_season_state.py` section 4, `test_media_library.py` and `test_media_follow_shows.py` pass unchanged except fixtures gaining the field.
4. A test on each side: the connector marks a counted 0 and leaves a missing count unmarked; the hub treats `empty: true` as waiting and `episodes: 0` without the field as not empty.
5. Red tests first (field absent on old code).
(1A instead: only the missing-count fix: `episodes` omitted when Jellyfin gave no count; red test: a series with no `RecursiveItemCount` must not be `empty_series`.)

## Data
`connectors/schema/data/jellyfin.schema.json` (shows items) gains an optional boolean under 1B; `jellyfin.py` `_shows()`. No migration. The frozen envelope's contract doc line in `docs/` changes too (checked by `tests/connectors/test_contract_doc.py`).

## Performance budget
None apply.

## Out of scope
The empty-show detection from an item's own season read (`empty_show`), and the Sonarr waiting words.

## Accept checklist
No visible change: My shows, Requests and an empty show's item page read exactly as before.

## Questions for B.
**1. What should the connector do with a counted-0 series?**
- **1A (recommended):** leave as is (dropped at source) and close the flag half of JY-115 as already done; separately, make a missing count not read as 0 (`episodes` omitted, so `empty_series` stays false). Smallest and keeps behaviour.
- **1B:** keep counted-0 series with `empty: true` and have the hub read it (criteria above). More code, every library-list reader must honour the flag, no visible gain today.
- **1C:** keep them, flagged, and add a "Waiting for the first episode" list on My shows fed from the snapshot. New screen content; needs an options page first.

Answer as "1A".

## Shipped notes
Not built. Spec only.
