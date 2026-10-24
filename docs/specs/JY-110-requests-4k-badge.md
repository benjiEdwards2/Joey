# JY-110 Requests page 4K badge lags

Status: building
Size: S
Live risk: none
Area: hub/media_quality.py, hub/media_season_state.py, tests/hub/test_media_quality.py
Needs: none
Options page: none: no screen change; the existing "4K" chip (WP-R1) just stops lagging

Live risk sets the review tier (see `docs/PROCESS.md`). Anything other than `none` is reviewed as L.

## Problem
HITLIST: "Shows lag 10 min; films fill on second view". After a 4K request, the Requests page's "4K" chip shows only
after a cache refresh: about 10 minutes for shows, and films only on the second view.

Root cause (2026-10-24):
- Films: `media_quality._row_pid` read the chip from `media_requests.kept`, the 5-minute (`LOOKUP_TTL`) lookup cache.
  Every Joey write (a request, a Remove, a quality switch) calls `forget_lookups()`, and the cache also expires after
  5 minutes, so on most visits it is empty: no film has its chip until `later` reads Radarr after the response, and
  the chip appears on the second view. This hit every 4K film on the page, not only the new one.
- Shows: `_row_pid` read `media_season_state._entry`, the Sonarr series list kept for `TTL` (10 min). A request's
  safety net (`ensure`) and a quality switch read or PUT the series live but never told that list, so a new show (or
  a switched one) kept its old answer until the next re-read.

## Acceptance criteria
1. A film's chip stays on the page after the lookup cache is dropped or expires (its last seen profile is kept however
   old), and the film is still re-read after the response as before (same `later` plan, same LATER_MAX bound).
2. A 4K film request through Joey has its chip on the next Requests view, with no extra call (the safety net's own
   read / PUT fills the cache).
3. A 4K show request through Joey has its chip on the next view without waiting for the 10-minute Sonarr list, and
   without making that list due.
4. A show Sonarr has not added yet when the safety net gives up ("notyet") makes the Sonarr list due, so the next
   page re-reads it.
5. A quality switch on a title page moves the chip on the Requests page at once (films and shows).
6. `attach` still never makes a call; nothing new runs on the page's hot path; no new writes to Seerr or the arr apps.

## Data
No tables or snapshots. In-memory only: `media_quality._films` (tmdb -> last seen Radarr `qualityProfileId`, capped at
1,024 entries, cleared with `clear_cache`); `media_season_state.put` (upsert one series entry into the kept list) and
`expire` (mark the list due).

## Performance budget
Media list page, warm p95 <= 150 ms. The change adds dict reads to `attach` and no call, so the budget is unchanged;
the PR states this rather than a new measurement (no NAS access for builders).

## Options and the pick
None: follows the existing "last good answer, served however old, re-read after the response" pattern of
`media_season_state` and `media_quality.peek`.

## Out of scope
- Season words for a show requested on the default profile (no safety-net read happens, so the list still re-reads on
  its own TTL).
- The request row itself appearing (the Seerr snapshot's own schedule).

## Accept checklist
1. Request a film in 4K, open Requests: the "4K" chip is there on the first view (once the request row is listed).
2. Request a show in 4K, open Requests: the chip is there without waiting 10 minutes.
3. Switch a title to 1080p on its page, open Requests: its chip is gone.
4. Open Requests after more than 5 minutes away: existing 4K films keep their chips on the first view.

## Questions for B.
None.

## Shipped notes
