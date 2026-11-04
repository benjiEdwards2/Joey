# JY-279 Row view: more columns (upgrade, director, my score)

Status: shipped (#310, live 91c73ab 2026-11-04)
Size: M
Live risk: low (read only; one optional background TMDB read, see Data)
Area: `hub/templates/_library_row.html`, `_library_page.html`, `hub/static/control-surface.css` (`.listbox.libposters`), `hub/media_library.py` (sort keys), `hub/media_pages.py` (`_library_page`), `tests/hub/`
Needs: none (Options B and C add a director cache table; see Data)
Options page: yes, 3 options at desktop / iPad / phone / TV

## Problem
B., 2026-11-02: "in the row version instead of the grid. can you please provide more columns with an upgrade available, or the director, or my own score, etc." His sentence was cut off after "Can y" (later words in HITLIST: "show a choice for a few options").

## What the code does today
- List view (`?view=list`, cookie `media_libview`) draws `_library_row.html`: poster, title (year), one meta line, a "Below cutoff" note, and your score at the right. It is a stacked row, not a table, and has no column headers.
- Each row already carries (from `media_library._library_rows`): title, year, genres, runtime, `community` (TMDB average), `score` (your score), `added_at`, `played` / `last_played_at`, state words, and for shows episodes / unplayed / status.
- `media_upgrades.attach` already sets `r.upgrade` (the arr cutoff-unmet note) on every row from the arr snapshot. No call.
- Sorts exist for score, A-Z, year, added, community rating, last watched, runtime, genre (`SORT_LABELS`); they are a select, not header clicks.
- Director is NOT on a library row. It is read from TMDB credits when a title page opens (`media_film.py`, crew job "Director"; TV uses "Created by") and kept only in the page cache, so a library-wide column has no source yet.

## Columns and cost
No new calls: Title, Year, Your score, Average (TMDB), Upgrade?, Added, Runtime, Genres, Watched / Last watched, Status (shows), Episodes left (shows).
Needs the TMDB director lookup: Director (films), Creator (shows). One credits read per title not yet cached (about one per library title the first time, then none); run in the background after the response, rate limited, stored in a small SQLite table keyed by tmdb id, shown blank until filled.
Her score: her ratings are already loaded for her view; showing both scores side by side is one extra `get_ratings` call per render (see Q3).

## Acceptance criteria
1. List view shows a header row and one column per chosen field; Grid view is unchanged.
2. Default set (recommended): Title, Year, Your score, Average, Upgrade?, Director, Added.
3. Clicking a column header sorts by it; click again reverses; the current sort and direction are marked in words (arrow plus `aria-sort`), and the toolbar select stays in step.
4. Sort is a link (`?sort=&dir=`), so Back works and search / filter chips are kept (`_links_with`).
5. Upgrade? shows "Yes" plus the note word (for example "Below cutoff") or a dash; sorting puts Yes first.
6. Missing values (no score, no director yet, no rating) show a dash and sort last in both directions.
7. Phone (below 640 px) shows Title, Year, Your score and Upgrade? only; the rest are hidden by CSS, not removed from the page.
8. Director cells fill without blocking: the page renders in budget with an empty cache; a title with a cached director shows it on the next load; the lookup never runs on the request path.
9. Columns use existing tokens and the `.listbox` recipe (`CLAUDE.md` rule 9); no new `:root` values.
10. TV: list view is unchanged unless Question 5 says otherwise; `test_tv_*` untouched.
11. Tests: column set per option renders; header sort order asc / desc for score, year, director, upgrade; blanks last; phone class hides the extra columns; director cache fill and read on a temp database; the existing row and library tests stay green.

## Options (page to build)
- A. Light: Title, Year, Your score, Average, Upgrade?, Added. All from data already on the row; no director, no new calls, no new table.
- B. Recommended: Title, Year, Your score, Average, Upgrade?, Director, Added. A plus the director column and the background TMDB lookup.
- C. Rich: B plus Runtime, Genres and Last watched, with a small "Columns" menu (choice remembered in a cookie like `media_libview`). Most flexible, most to build and test.

All three: header sort on every column, reduced set on phone.

## Data
A: none. B: a `library_director` table (tmdb id, kind, name, fetched_at) filled by a background job that reads TMDB credits for uncached titles and refreshes rarely. C: the same as B, plus the cookie.

## Performance budget
Hub page p95 <= 50 ms; library list page <= 3 s with an empty director cache and never blocked by TMDB. The background fill is rate limited and stops on a 429. First fill is about one call per library title; I have not counted this library, so the builder reports the count and time in the PR. Measured on the preview.

## Out of scope
Grid view, the Suggestions carousel, new filters, editing a score from the row, her columns beyond Q3, TV remote navigation of headers.

## Accept checklist
- [ ] Desktop list shows the chosen columns and sorts from the headers.
- [ ] iPad shows the same; phone shows the reduced set.
- [ ] Upgrade? agrees with the Upgrades block on the Media home.
- [ ] Directors appear after the background fill, with no slowdown while it runs.

## Questions for B.
1. Which option? A. light, B. with director (recommended), C. rich with a Columns menu.
2. Your sentence stopped at "Can y". What did you mean to ask (a different column, a filter, saving the layout)?
3. Show her score too (next to yours)? A. no (recommended), B. yes, her view only, C. yes, both.
4. Director for shows: A. the creator (recommended), B. leave blank.
5. TV: A. leave list view as is (recommended), B. add two columns (score, upgrade).

## Shipped notes

## Shipped notes (2026-11-04)

Merged #310 on B.'s review-page answer (Accept, 2026-11-04 morning), live pending.
