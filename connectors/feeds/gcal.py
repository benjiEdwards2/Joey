"""Calendar: B.'s Google ICS feed + Georgina's Outlook ICS feed, merged and owner-tagged."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from connectors.base import Connector, partial_note
from connectors.feeds._common import _now
from connectors.feeds._http import http_json, session

CALENDAR_WINDOW_DAYS = 14


class Gcal(Connector):
    """B.'s Google feed + Georgina's Outlook feed, merged and owner-tagged."""

    id = "gcal"
    requires_env = ("ICS_URL_YOU", "ICS_URL_HER")

    FEEDS = (("raw_you", "ICS_URL_YOU", "you"), ("raw_her", "ICS_URL_HER", "her"))

    def fetch(self) -> dict:
        raw: dict[str, Any] = {}
        errors: dict[str, str] = {}
        client = session()
        try:
            for key, var, owner in self.FEEDS:
                try:
                    raw[key] = http_json(f"calendar {owner}", os.environ[var], session=client, text=True)
                except RuntimeError as exc:  # the reason never contains the secret URL
                    errors[owner] = exc.reason
        finally:
            client.close()
        if not raw:
            raise RuntimeError(
                "both calendar feeds failed ("
                + ", ".join(f"{o}: {r}" for o, r in sorted(errors.items()))
                + ")"
            )
        if errors:
            raw["errors"] = errors
        return raw

    def transform(self, raw: dict) -> dict:
        import icalendar
        import recurring_ical_events

        start = _now()
        end = start + timedelta(days=CALENDAR_WINDOW_DAYS)

        events: list[dict] = []
        for key, _var, owner in self.FEEDS:
            if key not in raw:
                continue
            calendar = icalendar.Calendar.from_ical(raw[key])
            for component in recurring_ical_events.of(calendar).between(start, end):
                events.append(_event(component, owner))

        events.sort(key=lambda e: (e["start"], e["title"]))
        first = events[0] if events else None
        errors = raw.get("errors") or {}
        secondary = f"{len(events)} events in {CALENDAR_WINDOW_DAYS} days"
        if errors:
            secondary += " · " + ", ".join(f"{o} feed down" for o in sorted(errors))
        data = {
            "summary": (
                f"{first['title']} · {_when(first)}" if first
                else f"Nothing in the next {CALENDAR_WINDOW_DAYS} days"
            ),
            "secondary": secondary,
            "events": events,
        }
        if errors:
            data["feed_errors"] = errors
            for owner, why in sorted(errors.items()):
                partial_note(data, owner, why)
        return data


def _event(component, owner: str) -> dict:
    start = component["DTSTART"].dt
    end = component["DTEND"].dt if "DTEND" in component else start
    all_day = not isinstance(start, datetime)
    return {
        "title": str(component.get("SUMMARY", "(no title)")),
        "start": _iso(start),
        "end": _iso(end),
        "all_day": all_day,
        "owner": owner,
    }


def _iso(value: date | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat(timespec="minutes")
    return value.isoformat()


def _when(event: dict) -> str:
    if event["all_day"]:
        return datetime.fromisoformat(event["start"]).strftime("%a %d %b · all day")
    return datetime.fromisoformat(event["start"]).strftime("%a %d %b %H:%M")
