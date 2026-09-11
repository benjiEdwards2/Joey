"""Per-feed stub connectors (WP23 step 3).

These transforms ARE the real connectors' `transform()` — written once, here,
against the committed fixtures. WP24-WP30 each add only the live `fetch()` for
one feed; nothing below is throwaway.

Every `data` block carries the hub display convention: a required `summary`
string plus an optional `secondary` line (D17, WP18) on top of the feed's own
fields. ClickUp has no stub — removed from v1 (2026-08-25). Money is Track E's
importer, not a Connector (D14).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from connectors import registry
from connectors.base import Connector, _now_iso

CALENDAR_WINDOW_DAYS = 14
NAS_RECENT_DAYS = 7


def _now() -> datetime:
    """The clock every stub reads — pinned in fixture mode, so output is stable."""
    return datetime.fromisoformat(_now_iso())


# ---------------------------------------------------------------- open_meteo


class OpenMeteo(Connector):
    id = "open_meteo"
    requires_env = ("WEATHER_LAT", "WEATHER_LON")

    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    # Every WMO code Open-Meteo documents. The condition must always be a
    # word — colour is never the only encoding (WP24 step 3).
    CONDITIONS = {
        0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "freezing fog",
        51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
        56: "freezing drizzle", 57: "heavy freezing drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain",
        66: "freezing rain", 67: "heavy freezing rain",
        71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
        80: "showers", 81: "heavy showers", 82: "violent showers",
        85: "snow showers", 86: "heavy snow showers",
        95: "thunderstorms", 96: "thunderstorms with hail",
        99: "thunderstorms with heavy hail",
    }

    # Undocumented codes still land on a readable word for their WMO decade.
    CONDITION_GROUPS = {
        0: "hazy", 1: "mist", 2: "recent precipitation", 3: "dust",
        4: "fog", 5: "drizzle", 6: "rain", 7: "snow", 8: "showers",
        9: "thunderstorms",
    }

    @classmethod
    def condition(cls, code: int) -> str:
        return cls.CONDITIONS.get(code) or cls.CONDITION_GROUPS.get(code // 10, "unknown")

    def fetch(self) -> dict:
        import requests

        response = requests.get(
            self.FORECAST_URL,
            params={
                "latitude": os.environ["WEATHER_LAT"],
                "longitude": os.environ["WEATHER_LON"],
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max",
                "timezone": os.environ.get("TZ", "auto"),
                "forecast_days": 1,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def transform(self, raw: dict) -> dict:
        current = raw["current"]
        daily = raw["daily"]
        now_c = float(current["temperature_2m"])
        condition = self.condition(int(current["weather_code"]))
        low = float(daily["temperature_2m_min"][0])
        high = float(daily["temperature_2m_max"][0])
        rain = int(daily["precipitation_probability_max"][0])
        return {
            "summary": f"{now_c:g} °C · {condition}",
            "secondary": f"{low:g}–{high:g} °C · {rain}% rain",
            "now_c": now_c,
            "condition_text": condition,
            "today_min_c": low,
            "today_max_c": high,
            "rain_prob_pct": rain,
        }


# ---------------------------------------------------------------------- gcal


class Gcal(Connector):
    """B.'s Google feed + Georgina's Outlook feed, merged and owner-tagged."""

    id = "gcal"
    requires_env = ("ICS_URL_YOU", "ICS_URL_HER")

    FEEDS = (("raw_you", "ICS_URL_YOU", "you"), ("raw_her", "ICS_URL_HER", "her"))

    def fetch(self) -> dict:
        import requests

        raw: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for key, var, owner in self.FEEDS:
            try:
                response = requests.get(os.environ[var], timeout=10)
                response.raise_for_status()
                raw[key] = response.text
            except Exception as exc:
                # Reason is type/status ONLY — requests exception text embeds the
                # secret URL, and this string ends up in envelopes and logs.
                errors[owner] = _safe_reason(exc)
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
        return data


def _safe_reason(exc: Exception) -> str:
    """A failure reason that can never contain the secret URL."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


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


# ---------------------------------------------------------------- macromates


class MacroMates(Connector):
    id = "macromates"
    requires_env = ("SUPABASE_URL", "SUPABASE_KEY")

    def transform(self, raw: dict) -> dict:
        meals = {m["id"]: m["name"] for m in raw["meals"]}
        entries = {e["slot_id"]: e for e in raw["plan_entries"]}

        week = []
        tonight = None
        for slot in raw["plan_slots"]:
            entry = entries.get(slot["id"])
            if not entry:
                continue
            meal = meals.get(entry["meal_id"], "TBD")
            week.append({"day": slot["day"], "meal": meal})
            if (slot["day"], slot["meal_time"]) == (raw["today"]["day"], raw["today"]["meal_time"]):
                tonight = {"meal": meal, "serves": int(entry["serves"])}

        return {
            "summary": f"Tonight: {tonight['meal']}" if tonight else "Nothing planned tonight",
            "secondary": (
                f"Serves {tonight['serves']} · {len(week)} nights planned" if tonight
                else f"{len(week)} nights planned"
            ),
            "tonight": tonight,
            "week": week,
            "owner": "shared",
        }


# ------------------------------------------------------------ home_assistant


class HomeAssistant(Connector):
    """One feed, three areas — the `areas` keying is what lets House, Car and
    Garden tiles show DIFFERENT things off a single snapshot (WP18 limit)."""

    id = "home_assistant"
    requires_env = ("HA_URL", "HA_TOKEN")

    CAR_HINTS = ("car",)
    GARDEN_HINTS = ("garden", "irrigation", "soil")
    OWNER_BY_AREA = {"house": "shared", "car": "you", "garden": "shared"}

    @classmethod
    def area_of(cls, entity_id: str) -> str:
        name = entity_id.lower()
        if any(h in name for h in cls.CAR_HINTS):
            return "car"
        if any(h in name for h in cls.GARDEN_HINTS):
            return "garden"
        return "house"

    def transform(self, raw: dict) -> dict:
        areas: dict[str, list] = {"house": [], "car": [], "garden": []}
        for state in raw["states"]:
            area = self.area_of(state["entity_id"])
            attributes = state.get("attributes", {})
            areas[area].append({
                "entity_id": state["entity_id"],
                "label": attributes.get("friendly_name", state["entity_id"]),
                "state": str(state["state"]),
                "unit": attributes.get("unit_of_measurement"),
                "owner": self.OWNER_BY_AREA[area],
            })

        house = areas["house"]
        headline = f"{house[0]['label']} {house[0]['state']}{_unit(house[0])}" if house else "TBD"
        counted = ", ".join(f"{len(v)} {k}" for k, v in areas.items())
        return {
            "summary": headline,
            "secondary": counted,
            "areas": areas,
        }


def _unit(entity: dict) -> str:
    return f" {entity['unit']}" if entity.get("unit") else ""


# ------------------------------------------------------------------ jellyfin


class Jellyfin(Connector):
    id = "jellyfin"
    requires_env = ("JELLYFIN_URL", "JELLYFIN_TOKEN")

    def transform(self, raw: dict) -> dict:
        sessions = raw["raw_sessions"]
        latest_raw = raw["raw_latest"]

        now_playing = []
        for session in sessions:
            item = session.get("NowPlayingItem")
            if not item:
                continue
            runtime = int(item.get("RunTimeTicks") or 0)
            position = int(session.get("PlayState", {}).get("PositionTicks") or 0)
            now_playing.append({
                "title": item["Name"],
                "user": session.get("UserName", "someone"),
                "progress_pct": round(position / runtime * 100) if runtime else 0,
            })

        latest = [
            {"title": i["Name"], "added_at": i["DateCreated"], "type": i["Type"]}
            for i in latest_raw["Items"]
        ]
        counts = latest_raw["Counts"]
        return {
            "summary": (
                f"{len(now_playing)} playing now" if now_playing
                else f"Nothing playing · {len(latest)} new"
            ),
            "secondary": f"Latest: {latest[0]['title']}" if latest else "No new titles",
            "now_playing": now_playing,
            "latest": latest,
            "library": {
                "movies": int(counts["MovieCount"]),
                "episodes": int(counts["EpisodeCount"]),
            },
        }


# ----------------------------------------------------------------- nas_stats


class NasStats(Connector):
    """Capacity comes from the NAS; the per-share file counts come from walking
    a directory tree, which is what the live WP30 connector will do over the
    mounted shares."""

    id = "nas_stats"
    requires_env = ("NAS_SHARES_ROOT",)

    def fetch_fixture(self) -> dict:
        meta = json.loads((self.fixture_dir / "raw_shares.json").read_text(encoding="utf-8"))
        # since=0 -> every fixture file counts as recent, so the snapshot stays
        # byte-reproducible whatever mtimes a fresh checkout happens to have.
        return {"meta": meta, "root": self.fixture_dir / "tree", "since_ts": 0.0}

    def transform(self, raw: dict) -> dict:
        root = Path(raw["root"])
        shares = [
            {
                "name": share["name"],
                "total_gb": share["total_gb"],
                "free_gb": share["free_gb"],
                "files_added_7d": count_files(root / share["name"], raw["since_ts"]),
            }
            for share in raw["meta"]["shares"]
        ]
        free = sum(s["free_gb"] for s in shares)
        added = sum(s["files_added_7d"] for s in shares)
        return {
            "summary": f"{free:,.0f} GB free across {len(shares)} shares",
            "secondary": f"{added} files added in {NAS_RECENT_DAYS} days",
            "shares": shares,
        }


def count_files(share_root: Path, since_ts: float) -> int:
    """Files anywhere under `share_root` modified at or after `since_ts`."""
    if not share_root.is_dir():
        return 0
    return sum(
        1 for p in share_root.rglob("*")
        if p.is_file() and p.stat().st_mtime >= since_ts
    )


# ------------------------------------------------------------------ register

STUBS: tuple[type[Connector], ...] = (
    OpenMeteo, Gcal, MacroMates, HomeAssistant, Jellyfin, NasStats,
)

for _cls in STUBS:
    registry.register(_cls, _cls.id)
