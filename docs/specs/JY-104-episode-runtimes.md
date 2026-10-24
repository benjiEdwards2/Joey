# JY-104 Episode runtimes from Jellyfin item data

Status: building
Size: S
Live risk: none
Area: `hub/media_item.py`, `hub/media_film.py`, `hub/media_home.py`, `hub/media_pages.py`, `tests/hub/`
Needs: none
Options page: none: no new screen; the existing progress words ("6 left · ~4h 30m") get their hours from a better source

## Problem
HITLIST: "Today from recorded plays only". The hours in a show's progress words (show hero status line, Continue
watching cards, My shows rows and cards) come from `media_plays_db.show_runtimes`, the average runtime of the show's
recorded plays. A show nobody has played through Joey's recorder says "6 left" with no hours, although Jellyfin knows
every episode's runtime (`RunTimeTicks`, 10,000,000 per second).

## Acceptance criteria
1. The show hero's progress words take the hours from the average `RunTimeTicks` of the show's episodes in the item
   read the page already makes (`media_item._seasons`, `/Shows/{id}/Episodes`, cached): no new Jellyfin call.
2. Continue watching and My shows take the same average from the show's cached item read (`media_item.peek`: never a
   Jellyfin read on these pages). A show with no cached read, or whose episodes carry no runtime, falls back to the
   recorded plays' average (today's behaviour), else no hours.
3. Jellyfin item data wins over recorded plays when both exist.
4. Durations use the existing format (`media_text.duration`, via `progress_words`).
5. Tests: unit test of the average (episodes without a runtime ignored); show hero with Jellyfin runtimes and no plays;
   item data beats plays; library / Continue watching from a cached read, plays fallback without one. Existing
   progress tests stay green.

## Data
No table, migration or snapshot change. Each episode dict in the item cache gains `runtime_min` (minutes, 1 decimal,
null without `RunTimeTicks`), from the read it already makes. The connector contract is unchanged.

## Performance budget
Media list / item page, warm p95 <= 150 ms. Adds no upstream call: one in-memory cache lookup per show row (the same
`peek` the library already does per row for its TheTVDB id) and, when every show has item data, one fewer SQLite read.

## Options and the pick
None: no screen change.

## Out of scope
- A per-show runtime in the jellyfin connector snapshot (series `RunTimeTicks`): it would cover shows whose page was
  never opened, but it is an additive field to the frozen data block (contract doc, schema, samples). See Questions.
- Summing the exact unwatched episodes' runtimes instead of count x average.

## Accept checklist
- Open a show nobody has played through Joey: the status line says "N left · ~Xh Ym".
- After that, My shows (list view) and its Continue watching card show the same hours.

## Questions for B.
1. Library rows for shows whose page has not been opened (or warmed) since the hub started still fall back to recorded
   plays. **A (recommended): leave it**; the warm-up already reads the home-shelf titles, so Continue watching is covered.
   **B:** a follow-up item adds `runtime_min` to the jellyfin connector's show rows from the series `RunTimeTicks`
   (additive, optional; Jellyfin fills it from metadata, so some shows may still lack it).

## Shipped notes
(filled at close-out)
