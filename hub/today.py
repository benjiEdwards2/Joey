"""The hub's Today line (E5, H1, 2026-10-13): ONE sentence under the greeting, composed from data the hub already holds —
no new feed, no call. Each clause comes from one source's existing facts and is dropped when that source has nothing to
say (a missing feed never invents a clause):

  * rain timing — the open_meteo hourly chances (weather.rain_words, short form): "Rain from 15:00" / "Dry today";
  * today's events — the Next 7 days groups (upcoming.hub_upcoming, already in the owner view): "2 events · first 9:30
    Dentist" / "Nothing on today";
  * new arrivals since yesterday — the arr snapshot's `arrived` rows: "New: Severance S02E03" (two titles, "+N more");
  * the Server card's state word, only when it is not fine: "<area name> needs attention" (the name is the registry's).

Clauses are joined by " · " (guide §9). Keyed on snapshot ids and the server card the hub already built — never an area
name in code.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from hub.ids import ARR_SNAPSHOT_ID
from hub.store import connected, parse_utc
from hub.weather import rain_words

NEW_MAX = 2   # arrival titles named before "+N more"
_EPISODE_TAIL = re.compile(r"^(.*?) · (S\d{2}(?:E\d{2,})?)(?: · .*)?$")


def _clock(start_text: str) -> str:
    """'09:30' -> '9:30' (the Today line's spoken time); anything else as it is."""
    h, sep, m = str(start_text).partition(":")
    return f"{int(h)}:{m}" if sep and h.isdigit() else str(start_text)


def _events_clause(upcoming, now: datetime) -> str | None:
    if not upcoming or (upcoming.get("st") or {}).get("state") not in ("fresh", "stale"):
        return None
    today = next((g for g in upcoming.get("groups") or [] if g.get("day") == now.date()), None)
    events = [e for e in (today or {}).get("events") or [] if not e.get("release")]   # E5 H2 media rows don't count
    if not events:
        return "Nothing on today"
    first = events[0]
    what = (f"{first['title']} all day" if first.get("start_text") == "All day"
            else f"{_clock(first.get('start_text'))} {first['title']}")
    if len(events) == 1:
        return f"1 event · {what}"
    return f"{len(events)} events · first {what}"


def short_title(title) -> str:
    """'Severance · S02E03 · Who Is Alive?' -> 'Severance S02E03'; 'Severance · S02 · 3 episodes' -> 'Severance S02';
    a film keeps its title."""
    text = str(title or "").strip()
    m = _EPISODE_TAIL.match(text)
    return f"{m.group(1)} {m.group(2)}" if m else text


def _arrivals_clause(snaps, now: datetime) -> str | None:
    snap = snaps.get(ARR_SNAPSHOT_ID)
    if not connected(snap) or not isinstance(snap.data, dict):
        return None
    since = datetime.combine(now.date() - timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
    titles = []
    for r in snap.data.get("arrived") or []:
        at = parse_utc(r.get("at")) if isinstance(r, dict) else None
        if at is not None and at >= since and r.get("title"):
            titles.append(short_title(r["title"]))
    titles = list(dict.fromkeys(titles))
    if not titles:
        return None
    named = titles[:NEW_MAX]
    more = len(titles) - len(named)
    return "New: " + " and ".join(named) + (f" +{more} more" if more else "")


def today_line(snaps, upcoming, weather, server_card, view: str, now: datetime) -> str | None:
    """The Today line, or None when no source has anything to say. `upcoming` is hub_upcoming's dict (already filtered
    to the owner `view`), `weather` find_weather's, `server_card` {name, state} of the server-layout card (None when
    there is none); `now` is home time."""
    clauses = []
    if weather and (weather.get("st") or {}).get("state") in ("fresh", "stale"):
        clauses.append(rain_words((weather.get("data") or {}).get("hourly"), now, short=True))
    clauses.append(_events_clause(upcoming, now))
    clauses.append(_arrivals_clause(snaps, now))
    if server_card and server_card.get("state") == "warn":
        clauses.append(f"{server_card['name']} needs attention")
    words = [c for c in clauses if c]
    return " · ".join(words) if words else None
