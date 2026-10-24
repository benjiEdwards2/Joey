# JY-242 Awards: honorary awards and a re-pull of old years

Status: spec
Size: M
Live risk: none
Area: `hub/media_awards.py`, `hub/media_awards_parse.py`, `hub/media_awards_seed.py`, `tests/hub/test_awards_*.py`
Needs: JY-152
Options page: none until B. answers Question 1 (option A or B changes what the ceremony or person page shows)

## Problem
Split from JY-152 on 2026-10-24. Two awards gaps need B.'s direction:

1. **Honorary awards.** Honorary sections (Cecil B. DeMille, Carol Burnett, SAG Life Achievement, BAFTA Fellowship) are not read on any page shape. They are one person, no film and no nominees: on table pages a `===[[Golden Globe Cecil B. DeMille Award|Cecil B. DeMille Award]]===` heading over a bare `[[Person]]` line; on today's pages a `* [[Golden Globe Cecil B. DeMille Award|Cecil B. DeMille Award]]: [[Viola Davis]]` line under "Honorary award recipient"; on SAG pages `===Screen Actors Guild Life Achievement Award===` over `* [[Person]]`.
2. **Old years keep the old parse.** JY-152 changed what the parser writes for song categories (film + writers, never the song as a person) and gave unlinked categories the key of their linked twin. Editions already `done` in `media.db` only pick that up when they are pulled again: today that is new pulls and the 120-day refresh. A `PARSER_V` bump re-queues only shapeless skips and winner-less editions.

## Acceptance criteria
After B.'s answers.

## Data
To be set by the answers. Question 2 A changes no schema; it re-writes the `award_nomination` rows of every done Wikipedia edition once.

## Performance budget
None apply to the re-pull (background sync). Question 1 A or B adds rows to existing page sections; the page budgets in `CLAUDE.md` apply to those pages.

## Options and the pick
Pending B.'s answers.

## Out of scope
Storing a song title (no column; see JY-152).

## Accept checklist
After B.'s answers.

## Questions for B.
1. **Honorary awards (Cecil B. DeMille, Carol Burnett, SAG Life Achievement, BAFTA Fellowship): read them?**
   - **A (recommended):** read them on every page shape as a winners-only category (one person, no film, `won`), folded under "More categories" on the ceremony, and counted on the person's page as a win. Needs a parser rule for the honorary headings and a FOLD word ("DeMille", "Burnett", "Life Achievement", "Fellowship"). One small follow-up item.
   - **B:** person pages only: show "Cecil B. DeMille Award 2025" on Viola Davis's page, not on the ceremony.
   - **C:** leave them unread (today).
2. **Re-pull every done Wikipedia edition once, so the song and category-key fixes reach old years?**
   - **A (recommended):** yes: bump `PARSER_V` to 3 and let the bump re-queue every done Wikipedia edition (about 300 pages; one parse call each plus pageprops for newly linked writers). The backlog clears in about 3 days of 6-hourly passes, or one manual `--pass --cap 200` kick after deploy. A small follow-up item.
   - **B:** no: only new pulls and the 120-day refresh pick the fixes up; old years keep the song as a person until a later bump.

## Shipped notes
