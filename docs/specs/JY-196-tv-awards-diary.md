# JY-196 Diary and Awards on the TV (U10)

Status: building
Size: M
Live risk: none
Area: `hub/templates/media_awards.html` and a new `_award_tv.html` (the TV Awards view), `hub/media_awards_pages.py` (the shelves data, TV forces the films view), `hub/templates/media_diary.html`, `hub/templates/media_history.html`, `hub/templates/_diary_row.html`, `_to_rate.html` and `media_to_rate.html` (the TV "OK to rate" fold), `hub/static/tv.css` (a commented "JY-196" block), tests in `tests/hub/`
Needs: JY-248 (no Overview pill; "Joey Media" = Home) and JY-195 (U9: TV empty states), both merged
Options page: `JoeyTV\mockups\tv-v2\02-library.html` (Awards option B, `02-library-awards-B*.png`) and `05-diary.html` (option A, `05-diary-A*.png`)

## Problem
TV UI evaluation 2026-10-23 (`JoeyTV\review\TV_UI_EVALUATION_2026-10-23.md`), plan row U10 (`JoeyTV\TV_UI_PLAN.md`):
- A1: the Awards page on the TV is the desktop page at 1.5x: 508 text nodes under 16 px, a chip row past the right safe margin, 218 focusables, and Down from the sub-tabs stops on the ceremony dropdown (details/summary + select a remote cannot drive).
- A2: hide Awards on the TV, or build a TV Awards view.
- Y1: the Diary's "This month" card showed household numbers on a friend's TV (data fixed in JY-190 / JY-247; this item is the layout).
- Y2: "Log a watch" is a search box, date, place and note: a remote cannot type, and Down lands on it.
- Y3: the All / Films / TV chips are small round pills.
- Y4: To rate is the "Rate TV by" chips plus empty boxes (empty states done in JY-195; this item is the rows).

## Options and the pick
B., Gate 1, 2026-10-25: **"3B · 5A"**.
- **3B, Awards TV view.** Awards get a real TV layout on the friends' TV front. They are not hidden.
- **5A, slim friend-only Diary on the TV.** JY-190 and JY-247 already scope the friend's Diary data to the friend, so this is the layout.

## Acceptance criteria
TV mode only (`html.tv`). Desktop, iPad and phone render exactly as before. JY-248's nav stays (no Overview pill, "Joey Media" is Home). JY-188 density B applies (104x156 cards, 18 px floor).

### Awards (3B)
1. On the TV, Movies > Awards and TV shows > Awards show, top to bottom: a row of ceremony chips (one per ceremony, the current one lit with `aria-current` and first focus), the edition line ("97th Academy Awards · 2 Mar 2025 · films of 2024"), then one poster shelf per category group. Nothing else: no picker sheet, no `<select>`, no `<details>`, no Films / Categories switch, no filter or sort chips, no "Next up" fold, no staleness line.
2. Shelves, in this order, each left out when empty: the headline category (its own name, e.g. "Best Picture"), Acting, the direction group ("Directing & writing" for films), Craft. Heading "<name> · <count>". Each card: poster (TV fetch, h=600), the title, a gold "N wins" / "1 win" chip on the poster when it won, and the words "On Joey" (green) or "Not on Joey". A card links to the title page when the work resolves, else it is plain text.
3. The ceremony chips wrap inside the safe area (never past x = 912 of 960). The chips keep the year the viewer is on (the existing ceremony links).
4. The TV view always draws the films data (a `?v=categories` link falls back to it). The shelves come from the edition already in `media.db`; no live call on render (the existing after-response poster fill stays as it is).
5. Privacy: no seen / played state for a friend (WP-B3 Q20 unchanged). "On Joey" is library presence only.

### Diary (5A)
6. On the TV the Diary shows: the month card as one slim row (label, films, episodes, hours watched), the All / Films / TV chips (44 px tall, 18 px+ text), then the month-grouped rows (poster, title, "Film · <date>" meta, the score on the right).
7. Hidden on the TV: "Log a watch" and its form, the stats line ("0 this week · ..."), milestones, the Play stats link, the Mine / Everyone scope form, the month card's Days watched / Average score / sentence / Wrapped link.
8. An unrated row shows "OK to rate"; OK opens the 1-10 strip inline (a `<details>` fold, `summary` is focusable in tv.js). Desktop and phone keep the inline picker.
9. To rate (`/media/history`) on the TV: the "Rate TV by" chips and the numbers line are hidden; the heading reads "To rate · <n>"; each row shows "OK to rate" and opens the same strip (with Skip). The JY-195 empty state is unchanged.
10. Privacy: the month card and rows are the friend's own (JY-190 / JY-247). A test pins that a friend's TV Diary carries no household title or number.

### Device check
11. **Device check (grouped TV session):** `tv_ui_capture.py device --only diary,history,movies_awards` gives 0 `tiny` and `outsideSafe 0`.

## Data
No schema change. Reads the awards edition, `diary` and `play` already read by these pages. `awards_ctx`'s ballot gains `shelves` (the same rows, grouped).

## Performance budget
Media list / item page, warm, p95 <= 150 ms. The TV Awards view draws every row of the edition (no lazy rows part); one edition is at most ~60 works, already pivoted on every page render. No added query.

## Decisions made while building
- `base.html` (the section row) and `_library_page.html` need no change: JY-248's nav already draws the TV row (no Overview pill, "Joey Media" = Home), and the Awards sub-tab already shows on the friends' Movies / TV shows rows.
- The shelves are the work's total wins (as the mockup's "6 wins"), so a film shows the same chip on every shelf it sits on.
- The desktop To rate heading stays the literal `<h2 class="seclabel">To rate</h2>` (pinned by `test_first_screens_e3.py`); the TV branch adds the count.
- A friend's To rate rows come from their own history, which `view_jelly` leaves empty today, so on the friends' TV `/media/history` is usually the JY-195 empty state; the fold is tested with stubbed rows.

## Out of scope
The desktop / phone Awards page and Diary; Wrapped; the title page's rating strip; Awards on the private front; a TV year picker (the chips keep the current year).

## Accept checklist
1. TV, Movies > Awards: ceremony chips, the edition line, Best Picture shelf with gold win chips and On Joey / Not on Joey; Down moves through the shelves; Right on a chip switches ceremony.
2. TV, TV shows > Awards: the same layout.
3. TV, Diary: slim month row, big All / Films / TV chips, no Log a watch; an unrated row says "OK to rate" and OK opens 1-10.
4. TV, Diary > To rate: no "Rate TV by" chips; rows say "OK to rate".
5. Desktop and phone: Awards and Diary look as before.
6. Device check (criterion 11).

## Questions for B.
None.

## Shipped notes
