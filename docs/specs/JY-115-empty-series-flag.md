# JY-115 Connector: flag series with 0 Jellyfin episodes at source (flag half already done; missing-count fix)

Status: building
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

## Options and the pick
1A, orchestrator 2026-10-24: bug fix, no new look. The flag half (explicit field for counted-0 series) is verified already done: the connector drops them at source since 2026-10-10 (`jellyfin.py` `_shows()`, `tests/connectors/test_jellyfin_library.py::test_show_with_zero_items_on_disk_is_left_out`), and the hub's `empty_series` guard (WP-T1, 2026-10-19) already handles any 0 that reaches it. No `empty` field is added.

## Acceptance criteria (built)
1. A series Jellyfin gives no `RecursiveItemCount` for has `episodes: null` in the snapshot (unknown), not 0. Schema (`episodes` is `integer|null`) and `docs/connector-contract.md` say so. A missing unplayed count still defaults to 0.
2. `media_library.empty_series` is true only for a counted 0; None and an absent key are not empty.
3. What the hub renders for such a series: it is a library show (My shows grid and counts, "On disk"/"On server" keys), not under "Waiting for the first episode"; its row says nothing about episodes (no "0 episodes"), because no count was given.
4. Counted-0 series still wait, unchanged (existing tests untouched).
5. Red tests first: `test_show_missing_episode_count_stays_unknown` (connector), `test_a_series_with_no_episode_count_is_not_empty` and `test_my_shows_lists_a_series_with_no_count_as_a_library_show` (hub) all failed on old code.
Test edit (2026-10-24): `test_show_missing_counts_default_to_zero` became `test_show_missing_episode_count_stays_unknown` (episodes 0 -> None); this is the behaviour change itself.

## Data
`connectors/schema/data/jellyfin.schema.json` (shows items) gains an optional boolean under 1B; `jellyfin.py` `_shows()`. No migration. The frozen envelope's contract doc line in `docs/` changes too (checked by `tests/connectors/test_contract_doc.py`).

## Performance budget
None apply.

## Out of scope
The empty-show detection from an item's own season read (`empty_show`), and the Sonarr waiting words.

## Accept checklist
No visible change: My shows, Requests and an empty show's item page read exactly as before.

## Questions for B. (answered above: 1A)
**1. What should the connector do with a counted-0 series?**
- **1A (recommended):** leave as is (dropped at source) and close the flag half of JY-115 as already done; separately, make a missing count not read as 0 (`episodes` omitted, so `empty_series` stays false). Smallest and keeps behaviour.
- **1B:** keep counted-0 series with `empty: true` and have the hub read it (criteria above). More code, every library-list reader must honour the flag, no visible gain today.
- **1C:** keep them, flagged, and add a "Waiting for the first episode" list on My shows fed from the snapshot. New screen content; needs an options page first.

Answer as "1A".

## Shipped notes
- 2026-10-24: built on B.'s orchestrator's 1A. `tests/connectors` + `tests/hub/test_season_state.py` + `test_media_library.py`: 476 passed; `-n 4 tests/hub/`: 2757 passed.
