"""Upcoming (W3 split of hub/main.py, H-44; was hub/calendar.py, renamed so it no longer shadows the stdlib `calendar`):
the day-grouped "next 7 days" list an area page renders under a gcal tile (build_upcoming / find_upcoming) and the hub's
"Next 7 days" card with its per-day KPI bars (hub_upcoming).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from hub import shell
from hub.ids import ARR_SNAPSHOT_ID, GCAL_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, WEATHER_SNAPSHOT_ID
from hub.store import connected, data_of, parse_utc, tile_state
from hub.weather import day_forecasts, forecast_line


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
                time_text = start_text = "All day"
            else:
                still_on = end > now
                time_text = f"{start:%H:%M} – {end:%H:%M}"
                start_text = f"{start:%H:%M}"
            if not still_on or start.date() >= window_end:
                continue
            rows.append((max(start.date(), today),
                         start, {"title": str(ev["title"]), "time_text": time_text,
                                 "start_text": start_text, "owner": owner}))
        except Exception:
            continue
    rows.sort(key=lambda r: (r[0], r[1]))
    groups: list[dict] = []
    for day, _, event in rows:
        if not groups or groups[-1]["day"] != day:
            groups.append({"day": day, "label": _day_label(day, today), "events": []})
        groups[-1]["events"].append(event)
    return groups


# Media releases in Next 7 days (E5, H2, 2026-10-13). A gcal tile with `show_media_releases: true` (areas.yaml) merges
# the arr snapshot's `this_week` calendar rows into its list while some registry tile reads the arr snapshot. Films are
# what Radarr's calendar returns (monitored only); an episode only for a show watched in the last RELEASE_RECENT_DAYS
# (the jellyfin snapshot's library rows), in progress (its up-next rows) or followed (media.db `media_follows`).
# Matched on the normalised show title: Sonarr rows carry TheTVDB keys, Jellyfin rows their own ids. The rows say
# what they are in words ("Premiere", "Digital release"; the template adds its word chip) and never count as events.
RELEASE_RECENT_DAYS = 30
RELEASE_WORDS = {"Premiere": "Premiere", "Finale": "Finale", "Digital": "Digital release", "Disc": "On disc",
                 "Cinemas": "In cinemas"}


def _wants_releases(tile) -> bool:
    return bool(getattr(tile, "show_media_releases", False)) and any(
        t.snapshot == ARR_SNAPSHOT_ID for a in shell.registry.areas for t in a.tiles)


def watched_shows(snaps, view: str, now: datetime) -> set[str]:
    """Normalised titles of the shows the owner view is following along: watched in the last RELEASE_RECENT_DAYS, in
    progress, or followed. Snapshot reads plus one small media.db read; an unreadable source adds nothing."""
    from hub import media_follow
    from hub.media_upgrades import norm_title

    jelly = data_of(snaps.get(JELLYFIN_SNAPSHOT_ID))
    her = jelly.get("her") or {}
    profiles = {"you": [jelly], "her": [her]}.get(view, [jelly, her])
    cut = now - timedelta(days=RELEASE_RECENT_DAYS)
    titles: set[str] = set()
    for p in profiles:
        for s in p.get("shows") or []:
            at = parse_utc(s.get("last_played_at"))
            if at is not None and at >= cut:
                titles.add(norm_title(s.get("title")))
        titles.update(norm_title(r.get("show_title")) for r in p.get("up_next") or [] if r.get("show_title"))
    try:
        titles.update(norm_title(f.get("name")) for f in media_follow.follows() if f.get("kind") == "show")
    except Exception:   # the follow list is a nicety here: never break the calendar
        pass
    titles.discard("")
    return titles


def release_rows(snaps, view: str, now: datetime, days: int = UPCOMING_DAYS) -> list[tuple[date, dict]]:
    """(day, row) for the arr calendar rows inside the window that pass the filter above; [] when not connected."""
    from hub.media_upgrades import norm_title

    snap = snaps.get(ARR_SNAPSHOT_ID)
    if not connected(snap) or not isinstance(snap.data, dict):
        return []
    today = now.date()
    shows = None
    out = []
    for r in snap.data.get("this_week") or []:
        try:
            day = date.fromisoformat(str(r["date"]))
            title = str(r["title"])
        except (KeyError, TypeError, ValueError):
            continue
        if not today <= day < today + timedelta(days=days):
            continue
        if r.get("kind") != "movie":
            shows = watched_shows(snaps, view, now) if shows is None else shows
            if norm_title(title.split(" · ", 1)[0]) not in shows:
                continue
        word = RELEASE_WORDS.get(r.get("label") or "") or ("Release" if r.get("kind") == "movie" else "New episode")
        out.append((day, {"title": title, "time_text": word, "start_text": word, "owner": "shared", "release": True}))
    return out


def merge_releases(groups: list[dict], releases, today: date) -> list[dict]:
    """build_upcoming's groups with the release rows added after each day's own events (new days slotted in order)."""
    by_day = {g["day"]: g for g in groups}
    for day, row in releases:
        if day not in by_day:
            by_day[day] = {"day": day, "label": _day_label(day, today), "events": []}
        by_day[day]["events"].append(row)
    return [by_day[d] for d in sorted(by_day)]


def attach_forecast(groups: list[dict], weather_data) -> list[dict]:
    """JY-160: each day group gets that day's forecast line (`wx`, with its glyph id `wx_glyph`) from the open_meteo
    snapshot's `days`, matched on the date. A day the snapshot does not cover gets no keys: the template shows no line.
    The event rows are not touched."""
    forecasts = day_forecasts(weather_data)
    for g in groups:
        f = forecasts.get(g["day"].isoformat())
        if f:
            g["wx"], g["wx_glyph"] = forecast_line(f), f["glyph"]
    return groups


def find_upcoming(tiles, snaps, view: str):
    """The area's upcoming list: present when a visible tile reads the gcal
    snapshot and that snapshot holds data (fresh or stale — never fabricated). E5: plus the media releases when the
    tile asks for them (show_media_releases)."""
    for row in tiles:
        if row["tile"].snapshot == GCAL_SNAPSHOT_ID and row["st"]["state"] in ("fresh", "stale"):
            snap = snaps.get(GCAL_SNAPSHOT_ID)
            now = datetime.now().astimezone()
            groups = build_upcoming(snap.data.get("events", []), view, now)
            if _wants_releases(row["tile"]):
                groups = merge_releases(groups, release_rows(snaps, view, now), now.date())
            attach_forecast(groups, data_of(snaps.get(WEATHER_SNAPSHOT_ID)))   # JY-160: a snapshot read, no call
            return {"groups": groups, "st": row["st"], "days": UPCOMING_DAYS}
    return None


def per_day_counts(groups, today: date, days: int = UPCOMING_DAYS) -> list[int]:
    """Events per day for today + the next days-1, from build_upcoming's groups (Calendar KPI bars). E5: media release
    rows are not events, so the bars stay calendar only."""
    by_day = {g["day"]: sum(1 for e in g["events"] if not e.get("release")) for g in groups}
    return [by_day.get(today + timedelta(days=i), 0) for i in range(days)]


NEXT_DAYS = 366   # how far ahead the hub Calendar card looks for "Next up" (the band itself shows UPCOMING_DAYS)


def next_event(snaps, view: str) -> dict | None:
    """The hub Calendar card's value and meta line (E3, 2026-10-13): the owner view's next event, however far ahead,
    as {title, when: "Today · 09:00" / "Wed 8 Oct · All day"}; None when nothing is coming (the card then keeps the
    snapshot's own summary). The title alone is the value, so a long "title · day time" never wraps at 24 px."""
    snap = snaps.get(GCAL_SNAPSHOT_ID)
    groups = build_upcoming((snap.data if snap else {}).get("events", []), view, datetime.now().astimezone(), NEXT_DAYS)
    if not groups:
        return None
    first = groups[0]["events"][0]
    return {"title": first["title"], "when": f'{groups[0]["label"]} · {first["start_text"]}'}


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
                    "per_day": per_day_counts(up["groups"], today) if up else None,
                    "next": next_event(snaps, view) if up else None}
    return None
