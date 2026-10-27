# JY-160 Forecast on each day of Next 7 days

Status: shipped 2026-10-27
Size: S
Live risk: none
Area: `hub/weather.py`, `hub/upcoming.py`, `hub/templates/_upcoming_table.html`, `hub/static/control-surface.css` (one rule block, outside `:root`), `tests/hub/test_upcoming_forecast.py`
Needs: none
Options page: `JoeyTV/review/decisions-2026-10-27/options.md` (JY-160, recommended A). B. has not picked yet.

## Problem
Next 7 days lists events but not the weather for them. B.'s option A: each day carries that day's forecast in one short line.

## Acceptance criteria
1. Each day group in Next 7 days (hub `/` and `/a/calendar`, the same `_upcoming_table.html`) shows one line before that day's first row: the glyph, the condition word, the low-high range and the rain chance, for example "Light rain · 12–24 °C · rain 60%". The word is always there; the glyph is decoration.
2. The data is the `open_meteo` snapshot's `days[]`, matched by `date` to the group's day. No new call, no new snapshot: `find_upcoming` reads the snapshots it is already given.
3. A day with no matching `days[]` row, a malformed row, or no weather snapshot shows no line (never a dash line, never a crash). A row with a condition but no temperatures shows the word only; a missing rain chance drops only that part.
4. Media release rows and the media-only days (an arr release on a day with no calendar event) get the same day line: the line belongs to the day group.
5. Event rows are unchanged: the `events` dicts gain no key, the per-day KPI bars are unchanged.
6. Household data stays private: the media front (`JOEY_FRONT=media`) serves neither `/` (303 to the guest home) nor `/a/calendar` (the ordinary 404), and no forecast line text reaches any media-front response. Tested.
7. Phone (393): the line wraps, never scrolls sideways. TV (1920): readable at the existing row size.

## Data
Reads `open_meteo` `data.days[]`: `date`, `condition_text`, `min_c`, `max_c`, `rain_prob_pct`. No table or snapshot change. Only the forecast days present are used: a snapshot older than the window covers fewer days and the rest show no line.

## Performance budget
Hub page render p95 <= 50 ms: seven dict lookups per render, no I/O. Not measurable on the NAS from this branch (no live calls); the cost is a loop over at most 7 rows.

## Options and the pick
Option A (day heading carries the forecast) is the recommendation. B. has not picked. If B. picks B (hourly beside timed events) or C (leave it), this branch is dropped or reworked.

## Out of scope
Days with no events do not appear in Next 7 days today and still do not (the forecast line sits on existing day groups). Hourly weather beside timed events (option B). Any change to the weather glimpse or `/weather`.

## Accept checklist
1. Hub `/`: each day in Next 7 days has a forecast line; a day beyond the forecast has none.
2. `/a/calendar`: same.
3. Phone and TV widths read cleanly.
4. The media front still shows no calendar.

## Questions for B.
1. Pick A, B or C for JY-160 (recommended A).
2. Should a day with no events but a media release keep the forecast line? (Built: yes, recommended.)

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #222, squash-merged as `65f6868` (65f68687d88b79a534800623bbe69b77e12653c1).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-27: Accept every recommendation on the Joey decisions page: merge the 4 built-ahead PRs, drop the 7, apply the rest as recommended."
- Follow-ups: none
