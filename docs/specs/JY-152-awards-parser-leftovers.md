# JY-152 Awards parser leftovers (5 small)

Status: building
Size: M
Live risk: none
Area: `hub/media_awards.py`, `hub/media_awards_parse.py`, `tests/hub/test_awards_*.py`, `tests/hub/fixtures/awards/`
Needs: none
Options page: none: parser and sync fixes, no screen change

## Problem
The awards round-2 build (WP-D1 to D3, 2026-10-16) left five known gaps, logged in the old BACKLOG ("Awards parser leftovers (2026-10-16, Ready, small)") and the 2026-10-16 decisions:

1. **Song people.** On a song category line (`"[[Song]]" (writers) – ''[[Film]]''`) the song title lands in `people`, so a song shows as a person and the songwriters are lost.
2. **Table headers.** An unlinked table header cell (old Globes TV tables: `! colspan=2 | Best Television Series` then `! Drama`) has no category page, so its `cat_key` is a slug and never merges with the same category in linked years (whose key is the category page's QID).
3. **Honorary.** Honorary sections (Cecil B. DeMille, Carol Burnett, SAG Life Achievement, BAFTA Fellowship) are not read on any page shape.
4. **Re-queue.** A `done` Wikipedia edition with nominations and no winner is re-pulled only at the next `PARSER_V` bump. A page fixed later on Wikipedia never fills in.
5. **Fixture.** No real-page fixture for the `{{Award category}}`-inside-table-cells shape (19th BAFTA, 1966).

Sources: `archive/BACKLOG_to_2026-10-23.md` line 92, `archive/DECISIONS_to_2026-10-23.md` (2026-10-16, "Accepted D1 gaps"), `archive/HANDOVER_to_2026-10-23.md` line 78.

## Acceptance criteria
1. **Song people (fixed here).** A nominee line whose text starts with a quoted title is a song line: the film in italics is the `work`, the song title is never in `people`. Songwriters named in the line's first parenthesis go in `people` ("Written by" / "Music and lyrics by" prefixes dropped; the "performed by" part and anything after a bare "performed by" are never people). With writers the entry is person-led; with none it is work-led (film only). Pinned on real pages: Globes 2025 "El Mal" -> Emilia Pérez with Clément Ducol, Camille, Jacques Audiard; Critics' Choice 2025 the same three without the performers; Critics' Choice 2001 "My Funny Friend and Me" -> The Emperor's New Groove, no people (Sting performed it); Critics' Choice 2005 "Old Habits Die Hard" -> Alfie, work-led. No song title is in `people` on any fixture page.
2. **Table headers (fixed here).** A category with no page whose name (case-folded) and kind match exactly one QID-keyed category of the same body already in `award_category` takes that QID as its `cat_key`. No match, or more than one: the slug, as today. Pinned: pull the 80th Globes (linked tables) then the 40th (unlinked TV cells); the 40th's "Best Television Series – Drama" nominations carry the 80th's QID key, and no slug category is written for it.
3. **Honorary: left for B.** (Question 1). Not in this PR.
4. **Re-queue (fixed here).** The pass re-pulls a `done` Wikipedia edition that has nominations and no winner once its last pull is at least `WINNERLESS_AFTER` (30 days) old. It joins after the backlog and the recent refresh, newest first, inside the same cap. It does not count as backlog, so the 6-hourly cadence does not come back for it. A winner-less edition pulled less than 30 days ago, a done edition with a winner, and a Wikidata-sourced edition are not picked.
5. **Fixture (fixed here).** `wp_bafta_19.json` (the 19th BAFTA page saved on 2026-10-16 during WP-D3, formatversion 2 shape, gzipped like the rest) joins the fixtures. Pinned: 18 `{{Award category}}` headers, 18 blocks, 18 winners, Best Film won by My Fair Lady (George Cukor).
6. Every fix starts with a test that fails on the old code. No live fetch: every test reads saved pages (`CLAUDE.md` rule 7).

## Data
No schema change. `award_category` gains no new rows for matched unlinked categories (they reuse the QID row). `award_nomination` rows for song categories change shape on the next pull of a page (film + writers instead of the song as a person). `PARSER_V` is not bumped here (see Question 2).

## Performance budget
None apply: no page or route changes. The sync adds one `award_category` lookup per pull and one grouped `award_nomination` query per pass.

## Options and the pick
None: no screen change.

## Out of scope
- Honorary awards (Question 1).
- Re-pulling old editions so items 1 and 2 reach data already in `media.db` (Question 2).
- Storing the song title anywhere: there is no column for it; the film and the writers carry the nomination, as on the Oscars rows from Wikidata.
- Mapping renamed categories (for example 1983's "Best Performance in a Television Series – Drama – Actor" to today's "Best Actor – Television Series Drama"). Only exact name matches merge.

## Accept checklist
- PR shows the awards tests and the full `tests/hub` run green, with the commit tested.
- Each of the four fixes has a test that failed before its commit (named in the PR).

## Questions for B.
1. **Honorary awards (Cecil B. DeMille, Carol Burnett, SAG Life Achievement, BAFTA Fellowship): read them?**
   - **A (recommended):** read them on every page shape as a winners-only category (one person, no film, `won`), folded under "More categories" on the ceremony, and counted on the person's page as a win. Needs a parser rule for the honorary headings and a FOLD word ("DeMille", "Burnett", "Life Achievement", "Fellowship"). One small follow-up item.
   - **B:** person pages only: show "Cecil B. DeMille Award 2025" on Viola Davis's page, not on the ceremony.
   - **C:** leave them unread (today).
2. **Re-pull every done Wikipedia edition once, so the song and category-key fixes reach old years?**
   - **A (recommended):** yes: bump `PARSER_V` to 3 and let the bump re-queue every done Wikipedia edition (about 300 pages; one parse call each plus pageprops for newly linked writers). The backlog clears in about 3 days of 6-hourly passes, or one manual `--pass --cap 200` kick after deploy. A small follow-up item.
   - **B:** no: only new pulls and the 120-day refresh pick the fixes up; old years keep the song as a person until a later bump.

## Shipped notes
