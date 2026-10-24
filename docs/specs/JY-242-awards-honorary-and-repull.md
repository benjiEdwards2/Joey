# JY-242 Awards: honorary awards and a re-pull of old years

Status: building
Size: M
Live risk: none
Area: `hub/media_awards.py`, `hub/media_awards_parse.py`, `hub/media_awards_seed.py`, `tests/hub/test_awards_*.py`
Needs: JY-152
Options page: none: B. picked from the text options; the honorary rows reuse the existing category card, "More categories" fold and person-page row

## Problem
Split from JY-152 on 2026-10-24. Two awards gaps need B.'s direction:

1. **Honorary awards.** Honorary sections (Cecil B. DeMille, Carol Burnett, SAG Life Achievement, BAFTA Fellowship) are not read on any page shape. They are one person, no film and no nominees: on table pages a `===[[Golden Globe Cecil B. DeMille Award|Cecil B. DeMille Award]]===` heading over a bare `[[Person]]` line; on today's pages a `* [[Golden Globe Cecil B. DeMille Award|Cecil B. DeMille Award]]: [[Viola Davis]]` line under "Honorary award recipient"; on SAG pages `===Screen Actors Guild Life Achievement Award===` over `* [[Person]]`.
2. **Old years keep the old parse.** JY-152 changed what the parser writes for song categories (film + writers, never the song as a person) and gave unlinked categories the key of their linked twin. Editions already `done` in `media.db` only pick that up when they are pulled again: today that is new pulls and the 120-day refresh. A `PARSER_V` bump re-queues only shapeless skips and winner-less editions.

## Acceptance criteria
1. **Honorary awards are read (1A).** On every page shape a shape already reads, an honorary section becomes one winners-only category: one entry per recipient, `won`, person-led, no work. Recognised by name only, in three places: a heading (`===Cecil B. DeMille Award===`, `=== [[Golden Globe Cecil B. DeMille Award|Cecil B. DeMille Award]] ===`, `===Screen Actors Guild Life Achievement Award===`, `===BAFTA Fellowship===`) over prose and then a `* [[Person]]`, `* '''[[Person]]'''` or bare `[[Person]]` line; a list line `* [[<award>]]: [[Person]]` (today's Globes, under "Honorary award recipient"); a bold `'''[[<award>]]'''` line over a bold `'''[[Person]]'''` line (old Globes "Special awards"). The names: "Cecil B. DeMille Award", "Carol Burnett Award", "Life Achievement Award", and "Fellowship" alone or as "BAFTA Fellowship" / "Academy Fellowship". Kind: the nearest Film / Television heading above, else TV for the Carol Burnett Award, else film at sync time. Pinned on the saved fixtures: Globes 2025 (Viola Davis, Ted Danson), 2023 (Eddie Murphy, Ryan Murphy), 2003 (Gene Hackman), 1983 (Laurence Olivier), 1963 (Bob Hope); SAG 2025 (Jane Fonda), 2020 (Robert De Niro), 1996 (Robert Redford); BAFTA 2025 (Warwick Davis).
2. **Never a false honorary.** A nominee named Carol Burnett, prose, the presenters table, "Mr. Golden Globe", and a film title holding "Fellowship" in a colon list are not categories. A page with only an honorary section stays shapeless (an honorary block never makes a page readable on its own). A shape that already read the section keeps its block; the honorary one is not added twice.
3. **The ceremony folds them.** "DeMille", "Burnett", "Life Achievement" and "Fellowship" are FOLD words, so the four always rank in "More categories" (group `more`, rank 1000+), never in the core cards or the films rows (no work, so no ballot row).
4. **The person page counts the win.** The recipient's person page shows "<year> · Cecil B. DeMille Award" as Won, and the tally counts it as a win and a nomination.
5. **Re-pull once (2A).** `PARSER_V` is 3. On the first pass after deploy every `done` Wikipedia-sourced edition (Globes, BAFTA, Critics' Choice, SAG, Emmys) goes back to `pending`, with the "no page shape" skips; Oscars (Wikidata), the winners-only bodies and other skips stay. The next pass re-queues nothing. The rows stay readable until the edition is re-pulled and rewritten whole. Every later bump also re-pulls every done Wikipedia edition (before, a bump re-queued only shapeless skips and winner-less editions).
6. No manual kick is built. After deploy B. or the orchestrator may run `python scripts/awards_sync.py --pass --cap 200` once to clear most of the backlog in one go; otherwise the 6-hourly passes clear it.
7. Every test above failed on the old code first (commit `3135c4d`). No live fetch: every test reads the saved pages.

## Data
No schema change. `award_category` gains up to two rows per edition (the honorary categories; key = the award page's QID when linked, else the linked twin's key by name and kind (JY-152), else a slug). `award_nomination` gains one row per recipient (`work_qid` empty, `won` 1). The `PARSER_V` 3 bump rewrites the `award_nomination` rows of every done Wikipedia edition once, as each is re-pulled. `award_sync.parser_v` becomes 3.

## Performance budget
None of the `CLAUDE.md` page budgets move: an edition page gains at most two one-entry categories inside the folded "More categories", a person page at most one row per honour. The re-pull is background sync inside the existing limits, unchanged here:
- `CAP` 40 editions a pass, `PACE_S` 2 s between calls, sequential, one page in memory at a time, one transaction per edition.
- While a backlog exists a pass runs every 6 h, never 22:00 to 07:00, so 2 to 3 passes a day. About 300 done Wikipedia editions / 40 = 8 passes: about 3 days. Newest years go first, so the recent ceremonies are rewritten in the first pass (the one that bumps).
- Calls per edition: 1 parse, then pageprops only for titles not already in `award_title` (cached) and one ids query only for unseen QIDs; at most about 3 calls, so a pass is at most about 120 calls and about 4 min of pacing.
- While the backlog clears, the staleness line counts fewer ceremonies done (for example "130 of 430 ceremonies"), rising each pass. The ceremony pages keep their rows; only an edition's own state is `pending`.
- A manual `--pass --cap 200` (criterion 6) keeps the same pacing: about 600 calls, about 20 min.

## Options and the pick
No options page: the honorary rows reuse the existing category card, the "More categories" fold and the person-page row.
B.'s pick, 2026-10-24 in chat: "JY-242: A A". Question 1: A (read them on every page shape, winners-only, folded under "More categories", a win on the person page). Question 2: A (bump `PARSER_V` to 3; every done Wikipedia edition re-queued once; the 6-hourly passes clear it).

## Out of scope
- Storing a song title (no column; see JY-152).
- Other honours on the same pages: the Emmys' Bob Hope Humanitarian Award and Governors Award, BAFTA's Outstanding British Contribution to Cinema, Mr. / Miss Golden Globe. They stay unread.
- A manual kick in code (criterion 6).

## Test changes (dated)
- 2026-10-24: the exact block and winner counts in `test_awards_parse.py` grow by each page's honorary blocks (Globes 2025 and 2023: 2; Globes 2003, 1983, 1963, SAG 2025, 2020, 1996, BAFTA 2025: 1), the Globes 2025 film / TV split by one each and the Globes 2023 TV count by one (Burnett). `test_titles_of_lists_category_pages_works_and_people_once` now expects Warwick Davis (the Fellowship sits above Best Film on the page) before the Best Film page. No assertion was dropped.
- 2026-10-24: `test_a_parser_bump_requeues_shapeless_skips_once` now expects the done editions with a winner (Critics' Choice 2006) or with no nominations (Globes 1984) re-queued too, and the log line "1 shapeless skips, 3 done Wikipedia editions re-queued" (2A: a bump re-pulls every done Wikipedia edition).

## Accept checklist
- PR shows the awards tests and the full `tests/hub` run green, with the commit tested, and the red run of the new tests on the old code.
- On a preview with a synced `media.db`: Golden Globes 2025, Categories view, "More categories" holds "Cecil B. DeMille Award" with Viola Davis as the winner; the TV side holds "Carol Burnett Award" with Ted Danson.
- Viola Davis's person page shows "2025 · Cecil B. DeMille Award", Won, and the tally counts it as a win.
- After deploy, the first pass logs "parser v3, ... done Wikipedia editions re-queued"; the backlog then shrinks each pass.

## Questions for B.
1. **Honorary awards (Cecil B. DeMille, Carol Burnett, SAG Life Achievement, BAFTA Fellowship): read them?**
   - **A (recommended):** read them on every page shape as a winners-only category (one person, no film, `won`), folded under "More categories" on the ceremony, and counted on the person's page as a win. Needs a parser rule for the honorary headings and a FOLD word ("DeMille", "Burnett", "Life Achievement", "Fellowship"). One small follow-up item.
   - **B:** person pages only: show "Cecil B. DeMille Award 2025" on Viola Davis's page, not on the ceremony.
   - **C:** leave them unread (today).
2. **Re-pull every done Wikipedia edition once, so the song and category-key fixes reach old years?**
   - **A (recommended):** yes: bump `PARSER_V` to 3 and let the bump re-queue every done Wikipedia edition (about 300 pages; one parse call each plus pageprops for newly linked writers). The backlog clears in about 3 days of 6-hourly passes, or one manual `--pass --cap 200` kick after deploy. A small follow-up item.
   - **B:** no: only new pulls and the 120-day refresh pick the fixes up; old years keep the song as a person until a later bump.

## Shipped notes
