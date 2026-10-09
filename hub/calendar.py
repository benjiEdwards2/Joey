"""Calendar (W3 split of hub/main.py, H-44): the day-grouped "next 7 days" list an area page renders under a gcal
tile (build_upcoming / find_upcoming) and the hub's "Next 7 days" card with its per-day KPI bars (hub_upcoming).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from hub import shell
from hub.ids import GCAL_SNAPSHOT_ID
from hub.store import tile_state


# Calendar upcoming list (2026-09-11 decision: next 7 days, day-grouped).
# Rendered on any area page whose tiles read this snapshot — keyed by connector
# id (GCAL_SNAPSHOT_ID) like the weather glimpse, never an area name (WP17 grep exception).
UPCOMING_DAYS = 7


def _event_dt(value: str, tz) -> datetime:
    """Parse an event timestamp (ISO with offset, or bare date for all-day)."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _day_label(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    return f"{d:%a} {d.day} {d:%b}"   # "Wed 8 Oct" (guide §9: no zero padding)


def build_upcoming(events, view: str, now: datetime, days: int = UPCOMING_DAYS) -> list[dict]:
    """Day-grouped event rows for the coming week, honouring the owner view (Q9).

    All-day events carry an ICS-style exclusive end date. An event already in
    progress groups under Today. A malformed event is skipped, never a crash.
    """
    tz = now.tzinfo
    today = now.date()
    window_end = today + timedelta(days=days)
    rows: list[tuple[date, datetime, dict]] = []
    for ev in events:
        try:
            owner = ev["owner"]
            if not (view == "both" or owner == "shared" or owner == view):
                continue
            start = _event_dt(ev["start"], tz)
            end = _event_dt(ev["end"], tz)
            if ev["all_day"]:
                if end <= start:
                    end = start + timedelta(days=1)
                still_on = end.date() > today  # exclusive end
                time_text = "All day"
            else:
                still_on = end > now
                time_text = f"{start:%H:%M} – {end:%H:%M}"
            if not still_on or start.date() >= window_end:
                continue
            rows.append((max(start.date(), today),
                         start, {"title": str(ev["title"]), "time_text": time_text,
                                 "owner": owner}))
        except Exception:
            continue
    rows.sort(key=lambda r: (r[0], r[1]))
    groups: list[dict] = []
    for day, _, event in rows:
        if not groups or groups[-1]["day"] != day:
            groups.append({"day": day, "label": _day_label(day, today), "events": []})
        groups[-1]["events"].append(event)
    return groups


def find_upcoming(tiles, snaps, view: str):
    """The area's upcoming list: present when a visible tile reads the gcal
    snapshot and that snapshot holds data (fresh or stale — never fabricated)."""
    for row in tiles:
        if row["tile"].snapshot == GCAL_SNAPSHOT_ID and row["st"]["state"] in ("fresh", "stale"):
            snap = snaps.get(GCAL_SNAPSHOT_ID)
            return {"groups": build_upcoming(snap.data.get("events", []), view,
                                             datetime.now().astimezone()),
                    "st": row["st"], "days": UPCOMING_DAYS}
    return None


def per_day_counts(groups, today: date, days: int = UPCOMING_DAYS) -> list[int]:
    """Events per day for today + the next days-1, from build_upcoming's groups (Calendar KPI bars)."""
    by_day = {g["day"]: len(g["events"]) for g in groups}
    return [by_day.get(today + timedelta(days=i), 0) for i in range(days)]


def hub_upcoming(snaps, view: str) -> dict | None:
    """Hub "Next 7 days" card: the first visible tile reading the gcal snapshot, its area's
    page for "View all", and find_upcoming's groups (None data = not connected)."""
    for a in shell.registry.areas:
        rows = [{"tile": t, "st": tile_state(t, snaps)} for t in a.tiles if shell.owner_visible(t, view)]
        row = next((r for r in rows if r["tile"].snapshot == GCAL_SNAPSHOT_ID), None)
        if row:
            up = find_upcoming(rows, snaps, view)
            today = datetime.now().astimezone().date()  # the clock find_upcoming groups on
            return {"href": f"/a/{a.id}", "st": row["st"], "days": UPCOMING_DAYS,
                    "groups": up["groups"] if up else [],
                    "per_day": per_day_counts(up["groups"], today) if up else None}
    return None
