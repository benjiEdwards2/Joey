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
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from connectors import registry
from connectors.base import Connector, _now_iso, mode

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

TICKS_PER_MINUTE = 600_000_000  # Jellyfin runtime/position ticks are 100 ns units
UP_NEXT_LIMIT = 8

# Jellyfin's PlayState.PlayMethod -> a word, never a colour.
PLAY_METHODS = {"DirectPlay": "Direct play", "DirectStream": "Direct stream", "Transcode": "Transcoding"}


def _media_title(item: dict) -> str:
    """'Show · S02E05 · Episode name' for an episode; the plain name otherwise."""
    if item.get("Type") == "Episode" and item.get("SeriesName"):
        season, number = item.get("ParentIndexNumber"), item.get("IndexNumber")
        code = f"S{int(season):02d}E{int(number):02d}" if season is not None and number is not None else None
        return " · ".join(p for p in (item["SeriesName"], code, item["Name"]) if p)
    return item["Name"]


def _play_method(session: dict) -> str:
    method = PLAY_METHODS.get(session.get("PlayState", {}).get("PlayMethod"))
    if method:
        return method
    # Older servers omit PlayMethod; a TranscodingInfo block still says it.
    return "Transcoding" if session.get("TranscodingInfo") else "Direct play"


class Jellyfin(Connector):
    id = "jellyfin"
    requires_env = ("JELLYFIN_URL", "JELLYFIN_API_KEY")  # JELLYFIN_USER is optional

    ITEM_FIELDS = "DateCreated,SeriesName"

    @staticmethod
    def pick_user(users: list[dict], preferred: str | None) -> dict:
        """JELLYFIN_USER by name, else the first administrator, else the first user."""
        if not users:
            raise RuntimeError("Jellyfin returned no users")
        if preferred:
            for user in users:
                if user.get("Name") == preferred:
                    return user
        for user in users:
            if user.get("Policy", {}).get("IsAdministrator"):
                return user
        return users[0]

    def fetch(self) -> dict:
        import requests

        base = os.environ["JELLYFIN_URL"].rstrip("/")
        headers = {"Authorization": f"MediaBrowser Token={os.environ['JELLYFIN_API_KEY']}"}

        def get(label: str, path: str, params: dict | None = None):
            try:
                response = requests.get(base + path, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                # Reason is type/status ONLY — requests exception text embeds the
                # server URL, and this string ends up in envelopes and logs.
                raise RuntimeError(f"Jellyfin {label} failed ({_safe_reason(exc)})") from None

        users = get("users", "/Users")
        uid = self.pick_user(users, os.environ.get("JELLYFIN_USER")).get("Id")
        if not uid:
            raise RuntimeError("Jellyfin user has no Id")
        fields = {"Fields": self.ITEM_FIELDS}
        return {
            "raw_users": users,
            "raw_sessions": get("sessions", "/Sessions"),
            "raw_resume": get("resume", f"/Users/{uid}/Items/Resume",
                              {"Limit": 10, "MediaTypes": "Video", **fields}),
            "raw_nextup": get("next up", "/Shows/NextUp", {"UserId": uid, "Limit": 10, **fields}),
            "raw_latest": get("latest", f"/Users/{uid}/Items/Latest", {"Limit": 5, **fields}),
            "raw_counts": get("counts", "/Items/Counts", {"UserId": uid}),
        }

    def transform(self, raw: dict) -> dict:
        now_playing = []
        for session in raw["raw_sessions"]:
            item = session.get("NowPlayingItem")
            if not item:
                continue
            runtime = int(item.get("RunTimeTicks") or 0)
            position = int(session.get("PlayState", {}).get("PositionTicks") or 0)
            now_playing.append({
                "title": _media_title(item),
                "user": session.get("UserName", "someone"),
                "progress_pct": min(100, round(position / runtime * 100)) if runtime else 0,
                "play_method": _play_method(session),
            })

        up_next, seen = [], set()
        for item in raw["raw_resume"]["Items"]:
            runtime = int(item.get("RunTimeTicks") or 0)
            position = int(item.get("UserData", {}).get("PlaybackPositionTicks") or 0)
            left = max(0, runtime - position) // TICKS_PER_MINUTE
            seen.add(item.get("Id"))
            up_next.append({
                "title": _media_title(item),
                "kind": "episode" if item.get("Type") == "Episode" else "movie",
                "remaining_text": f"{left} min left",
            })
        for item in raw["raw_nextup"]["Items"]:
            if item.get("Id") in seen:  # already resumable — don't list twice
                continue
            up_next.append({"title": _media_title(item), "kind": "episode",
                            "remaining_text": "Next episode"})
        up_next = up_next[:UP_NEXT_LIMIT]

        latest = [
            {"title": i["Name"], "added_at": i["DateCreated"], "type": i["Type"]}
            for i in raw["raw_latest"]
        ]
        counts = raw["raw_counts"]
        first = now_playing[0] if now_playing else None
        if first:
            secondary = f"{first['title']} · {first['user']} · {first['play_method']}"
        else:
            secondary = up_next[0]["title"] if up_next else "Nothing up next"
        return {
            "summary": (
                f"{len(now_playing)} playing now" if now_playing
                else f"Nothing playing · {len(up_next)} up next"
            ),
            "secondary": secondary,
            "now_playing": now_playing,
            "up_next": up_next,
            "latest": latest,
            "library": {
                "movies": int(counts["MovieCount"]),
                "episodes": int(counts["EpisodeCount"]),
            },
        }


# -------------------------------------------------------------- media_status

# The Media area's app list (hard-coded by decision 2026-10-05): id, display
# name, port, health path. Any HTTP answer counts as up — a 401 still means the
# app is alive (qBittorrent); only no answer or a 5xx is down.
MEDIA_APPS = (
    {"id": "jellyfin", "name": "Jellyfin", "port": 8096, "path": "/health"},
    {"id": "radarr", "name": "Radarr", "port": 7878, "path": "/ping"},
    {"id": "sonarr", "name": "Sonarr", "port": 8989, "path": "/ping"},
    {"id": "jellyseerr", "name": "Jellyseerr", "port": 5055, "path": "/api/v1/status"},
    {"id": "prowlarr", "name": "Prowlarr", "port": 9696, "path": "/ping"},
    {"id": "qbittorrent", "name": "qBittorrent", "port": 8080, "path": "/api/v2/app/version"},
    {"id": "uptime_kuma", "name": "Uptime Kuma", "port": 3001, "path": "/"},
    {"id": "portainer", "name": "Portainer", "port": 9000, "path": "/api/status"},
)
FIXTURE_MEDIA_HOST = "nas.local"  # fixture mode never reads the real host


def _probe_note(exc: Exception) -> str:
    """Why an app is down, in words — never the URL a requests error embeds."""
    import requests

    if isinstance(exc, requests.Timeout):  # before ConnectionError: ConnectTimeout is both
        return "timeout"
    if isinstance(exc, requests.ConnectionError):
        return "connection refused"
    return type(exc).__name__


class MediaStatus(Connector):
    id = "media_status"
    requires_env = ("MEDIA_STATUS_HOST",)

    def fetch(self) -> list[dict]:
        import requests

        host = os.environ["MEDIA_STATUS_HOST"]
        results = []
        for app in MEDIA_APPS:
            up, note = False, None
            try:
                response = requests.get(f"http://{host}:{app['port']}{app['path']}",
                                        timeout=5, allow_redirects=False)
                up = response.status_code < 500
                if not up:
                    note = f"HTTP {response.status_code}"
            except Exception as exc:  # one app failing never fails the run
                note = _probe_note(exc)
            results.append({"id": app["id"], "up": up, "note": note})
        return results

    def transform(self, raw: list[dict]) -> dict:
        host = FIXTURE_MEDIA_HOST if mode() == "fixture" else os.environ["MEDIA_STATUS_HOST"]
        probes = {p["id"]: p for p in raw}
        apps = []
        for app in MEDIA_APPS:
            probe = probes.get(app["id"], {"up": False, "note": "no result"})
            apps.append({
                "id": app["id"],
                "name": app["name"],
                "href": f"http://{host}:{app['port']}",
                "up": bool(probe["up"]),
                "status_text": "Up" if probe["up"] else "Down",
                "note": None if probe["up"] else probe.get("note"),
            })
        down = [a["name"] for a in apps if not a["up"]]
        return {
            "summary": f"{len(apps) - len(down)} of {len(apps)} up",
            "secondary": f"Down: {', '.join(down)}" if down else "All apps up",
            "apps": apps,
        }


# ----------------------------------------------------------------------- arr

ARR_WINDOW_DAYS = 7
ARR_LIMIT = 20
GIB = 1024 ** 3
# (app, url var, key var) — each app is fetched independently
ARR_APPS = (("radarr", "RADARR_URL", "RADARR_API_KEY"), ("sonarr", "SONARR_URL", "SONARR_API_KEY"))


def _arr_reason(exc: Exception) -> str:
    """Why an app failed, in words — never the URL/key a requests error embeds."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else _probe_note(exc)


def _dt(value) -> datetime:
    """ISO timestamp (Z suffix, >6 fractional digits tolerated) -> aware datetime."""
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value).replace("Z", "+00:00"))
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ago(dt: datetime, now: datetime) -> str:
    seconds = (now - dt).total_seconds()
    if seconds < 3600:
        return "just now"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    days = int(seconds // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def _records(payload) -> list[dict]:
    """v3 history/queue are paged ({records: [...]}); calendar/diskspace are bare lists."""
    return (payload.get("records", []) if isinstance(payload, dict) else payload) or []


def _upgrade_text(record: dict) -> str:
    quality = (record.get("quality") or {}).get("quality") or {}
    name, res = str(quality.get("name") or ""), int(quality.get("resolution") or 0)
    if res >= 2160:
        return "Upgraded to 4K"
    if name.lower().startswith("bluray"):
        return "Upgraded to Blu-ray"
    return f"Upgraded to {res}p" if res else "Upgraded"


def _episode_code(season, number) -> str | None:
    if season is None:
        return None
    return f"S{int(season):02d}" + (f"E{int(number):02d}" if number is not None else "")


def _episode_title(series: str, episode: dict) -> str:
    code = _episode_code(episode.get("seasonNumber"), episode.get("episodeNumber"))
    return " · ".join(p for p in (series, code, episode.get("title")) if p)


def _timeleft(text) -> str:
    """Servarr 'd.hh:mm:ss' / 'hh:mm:ss' -> '12 min' / '1h 05m' (blank when unknown)."""
    try:
        days, _, clock = str(text).rpartition(".")
        h, m, _s = (int(p) for p in clock.split(":"))
        minutes = (int(days or 0) * 24 + h) * 60 + m
    except Exception:
        return ""
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{max(minutes, 1)} min"


class Arr(Connector):
    """Radarr + Sonarr: what arrived / was upgraded this week, what's due, the
    download queue and disk space. One app down is data (app_errors), not a failure."""

    id = "arr"
    requires_env = ("RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY")

    @staticmethod
    def endpoints(app: str, now: datetime) -> list[tuple[str, str, dict]]:
        since = (now.astimezone(timezone.utc) - timedelta(days=ARR_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        start, end = now.date(), now.date() + timedelta(days=ARR_WINDOW_DAYS)
        hist = {"pageSize": 100, "sortKey": "date", "sortDirection": "descending", "since": since}
        cal = {"start": start.isoformat(), "end": end.isoformat()}
        if app == "radarr":
            extra = {"includeMovie": "true"}
        else:
            extra = {"includeSeries": "true", "includeEpisode": "true"}
            cal["includeSeries"] = "true"
        return [
            (f"raw_{app}_history", "/api/v3/history", {**hist, **extra}),
            (f"raw_{app}_calendar", "/api/v3/calendar", cal),
            (f"raw_{app}_queue", "/api/v3/queue", {"pageSize": 50, **extra}),
            (f"raw_{app}_diskspace", "/api/v3/diskspace", {}),
        ]

    def fetch(self) -> dict:
        import requests

        now = _now()
        raw: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for app, url_var, key_var in ARR_APPS:
            base = os.environ[url_var].rstrip("/")
            headers = {"X-Api-Key": os.environ[key_var]}
            got: dict[str, Any] = {}
            try:
                for key, path, params in self.endpoints(app, now):
                    response = requests.get(base + path, headers=headers, params=params, timeout=10)
                    response.raise_for_status()
                    got[key] = response.json()
                raw.update(got)
            except Exception as exc:
                # Reason is type/status ONLY — requests exception text embeds the
                # app URL, and this string ends up in envelopes and logs.
                errors[app] = _arr_reason(exc)
        if len(errors) == len(ARR_APPS):
            raise RuntimeError(
                "both apps failed (" + ", ".join(f"{a}: {r}" for a, r in sorted(errors.items())) + ")"
            )
        if errors:
            raw["app_errors"] = errors
        return raw

    # ---- transform ---------------------------------------------------------

    @staticmethod
    def _imports(records: list[dict], now: datetime, id_key: str, deleted_event: str, grouped: bool):
        """(arrived, updated) as (datetime, entry) lists. An import is an upgrade
        when flagged (data.isUpgrade) or when the same movie/episode had a file
        deleted 'for an upgrade' at or before the import."""
        cutoff = now - timedelta(days=ARR_WINDOW_DAYS)
        recs = sorted((r for r in records if _dt(r["date"]) >= cutoff),
                      key=lambda r: _dt(r["date"]), reverse=True)
        deletes: dict[Any, list[datetime]] = {}
        for r in recs:
            if r.get("eventType") == deleted_event and "upgrade" in str((r.get("data") or {}).get("reason", "")).lower():
                deletes.setdefault(r.get(id_key), []).append(_dt(r["date"]))

        buckets: dict[bool, dict[Any, list[dict]]] = {False: {}, True: {}}
        for r in recs:  # newest first, so each group's [0] is its newest import
            if r.get("eventType") != "downloadFolderImported":
                continue
            when = _dt(r["date"])
            upgrade = (str((r.get("data") or {}).get("isUpgrade", "")).lower() in ("true", "1")
                       or any(d <= when for d in deletes.get(r.get(id_key), [])))
            if grouped:  # a season's episodes imported together become one line
                key = ((r.get("series") or {}).get("title") or r.get("sourceTitle") or "Unknown",
                       (r.get("episode") or {}).get("seasonNumber"))
            else:
                key = r.get(id_key)
            buckets[upgrade].setdefault(key, []).append(r)

        def entry(group: list[dict], upgrade: bool) -> tuple[datetime, dict]:
            newest = group[0]
            when = _dt(newest["date"])
            if grouped:
                series = (newest.get("series") or {}).get("title") or newest.get("sourceTitle") or "Unknown"
                if len(group) == 1:
                    title, kind = _episode_title(series, newest.get("episode") or {}), "episode"
                else:
                    code = _episode_code((newest.get("episode") or {}).get("seasonNumber"), None)
                    title = " · ".join(p for p in (series, code, f"{len(group)} episodes") if p)
                    kind = "season"
            else:
                title = (newest.get("movie") or {}).get("title") or newest.get("sourceTitle") or "Unknown"
                kind = "movie"
            row = {"title": title, "kind": kind, "when": _ago(when, now)}
            if upgrade:
                row["what"] = _upgrade_text(newest)
            return when, row

        return ([entry(g, False) for g in buckets[False].values()],
                [entry(g, True) for g in buckets[True].values()])

    @staticmethod
    def _this_week(radarr: list[dict], sonarr: list[dict], now: datetime) -> list[dict]:
        today, end = now.date(), now.date() + timedelta(days=ARR_WINDOW_DAYS)
        rows: list[dict] = []
        for m in radarr:
            for field, label in (("digitalRelease", "Digital"), ("physicalRelease", "Disc"),
                                 ("inCinemas", "Cinemas")):
                if not m.get(field):
                    continue
                day = _dt(m[field]).date()
                if not today <= day <= end or (label == "Disc" and m.get("hasFile")):
                    continue  # a disc release already on disk is not news
                rows.append({"title": m["title"], "kind": "movie", "date": day.isoformat(), "label": label})
        for e in sonarr:
            stamp = e.get("airDateUtc") or e.get("airDate")
            if not stamp:
                continue
            day = _dt(stamp).date()
            if not today <= day <= end:
                continue
            if e.get("episodeNumber") == 1:
                label = "Premiere"
            elif e.get("finaleType") in ("series", "season"):
                label = "Finale"
            else:
                label = ""
            rows.append({"title": _episode_title((e.get("series") or {}).get("title", "Unknown"), e),
                         "kind": "episode", "date": day.isoformat(), "label": label})
        return sorted(rows, key=lambda r: (r["date"], r["title"]))

    @staticmethod
    def _queue(app: str, records: list[dict]) -> list[dict]:
        rows = []
        for r in records:
            size, left = float(r.get("size") or 0), float(r.get("sizeleft") or 0)
            if app == "radarr":
                title, kind = (r.get("movie") or {}).get("title") or r.get("title") or "Unknown", "movie"
            else:
                series = (r.get("series") or {}).get("title") or r.get("title") or "Unknown"
                if r.get("episode"):
                    title, kind = _episode_title(series, r["episode"]), "episode"
                else:
                    code = _episode_code(r.get("seasonNumber"), None)
                    title, kind = " · ".join(p for p in (series, code) if p), "season"
            rows.append({
                "title": title, "kind": kind,
                "pct": min(100, max(0, round((size - left) / size * 100))) if size else 0,
                "status_text": str(r.get("status") or "queued").capitalize(),
                "time_left": _timeleft(r.get("timeleft")),
            })
        return rows

    def transform(self, raw: dict) -> dict:
        now = _now()
        arrived: list[tuple[datetime, dict]] = []
        updated: list[tuple[datetime, dict]] = []
        for app, id_key, deleted, grouped in (("radarr", "movieId", "movieFileDeleted", False),
                                              ("sonarr", "episodeId", "episodeFileDeleted", True)):
            a, u = self._imports(_records(raw.get(f"raw_{app}_history")), now, id_key, deleted, grouped)
            arrived += a
            updated += u
        arrived_rows = [row for _, row in sorted(arrived, key=lambda p: p[0], reverse=True)]
        updated_rows = [row for _, row in sorted(updated, key=lambda p: p[0], reverse=True)]

        this_week = self._this_week(_records(raw.get("raw_radarr_calendar")),
                                    _records(raw.get("raw_sonarr_calendar")), now)
        downloading = (self._queue("radarr", _records(raw.get("raw_radarr_queue")))
                       + self._queue("sonarr", _records(raw.get("raw_sonarr_queue"))))

        disk, seen = [], set()
        for d in _records(raw.get("raw_radarr_diskspace")) + _records(raw.get("raw_sonarr_diskspace")):
            total, free = int(d.get("totalSpace") or 0), int(d.get("freeSpace") or 0)
            if d["path"] in seen or not total:
                continue
            seen.add(d["path"])
            disk.append({"path": d["path"], "free_gb": round(free / GIB, 1),
                         "total_gb": round(total / GIB, 1),
                         "pct_used": round((total - free) / total * 100)})

        data = {
            "summary": (f"{len(arrived_rows)} arrived this week · {len(downloading)} downloading"
                        if arrived_rows else "Nothing new this week"),
            "secondary": (arrived_rows[0]["title"] if arrived_rows
                          else this_week[0]["title"] if this_week else ""),
            "arrived": arrived_rows[:ARR_LIMIT],
            "updated": updated_rows[:ARR_LIMIT],
            "this_week": this_week[:ARR_LIMIT],
            "downloading": downloading[:ARR_LIMIT],
            "disk": disk[:ARR_LIMIT],
        }
        if raw.get("app_errors"):
            data["app_errors"] = dict(raw["app_errors"])
        return data


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
    OpenMeteo, Gcal, MacroMates, HomeAssistant, Jellyfin, MediaStatus, Arr, NasStats,
)

for _cls in STUBS:
    registry.register(_cls, _cls.id)
