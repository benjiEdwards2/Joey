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
from connectors.base import Connector, _now_iso, log, mode

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

    # Weather upgrade (2026-10-06): one GET now also carries the next hours and
    # 7 days. The first three daily fields keep their order — day 0 still
    # composes summary/secondary exactly as before.
    HOURLY = "temperature_2m,precipitation_probability,apparent_temperature"
    DAILY = (
        "temperature_2m_min,temperature_2m_max,precipitation_probability_max,"
        "weather_code,sunrise,sunset,uv_index_max,wind_speed_10m_max"
    )
    HOURS = 24

    @classmethod
    def condition(cls, code: int) -> str:
        return cls.CONDITIONS.get(code) or cls.CONDITION_GROUPS.get(code // 10, "unknown")

    @staticmethod
    def _num(values, i, cast=float):
        """values[i] cast, or None — Open-Meteo pads missing hours/days with null."""
        try:
            v = values[i]
        except (IndexError, TypeError):
            return None
        return None if v is None else cast(v)

    def _hourly(self, raw: dict) -> list[dict]:
        """The next HOURS hours from the current hour (local ISO times sort as text)."""
        hourly = raw.get("hourly") or {}
        times = hourly.get("time") or []
        start = str(raw["current"]["time"])[:13]  # "YYYY-MM-DDTHH" — floor to the hour
        first = next((i for i, t in enumerate(times) if t[:13] >= start), len(times))
        return [
            {
                "time": times[i],
                "temp_c": self._num(hourly.get("temperature_2m"), i),
                "rain_prob_pct": self._num(hourly.get("precipitation_probability"), i, int),
                "feels_c": self._num(hourly.get("apparent_temperature"), i),
            }
            for i in range(first, min(first + self.HOURS, len(times)))
        ]

    def _days(self, daily: dict) -> list[dict]:
        def clock(values, i):  # "2026-01-01T05:57" -> "05:57"
            v = self._num(values, i, str)
            return v[11:16] if v else None

        days = []
        for i, day in enumerate((daily.get("time") or [])[:7]):
            code = self._num(daily.get("weather_code"), i, int)
            days.append({
                "date": day,
                "min_c": self._num(daily.get("temperature_2m_min"), i),
                "max_c": self._num(daily.get("temperature_2m_max"), i),
                "rain_prob_pct": self._num(daily.get("precipitation_probability_max"), i, int),
                "condition_text": "unknown" if code is None else self.condition(code),
                "sunrise": clock(daily.get("sunrise"), i),
                "sunset": clock(daily.get("sunset"), i),
                "uv_max": self._num(daily.get("uv_index_max"), i),
                "wind_max_kmh": self._num(daily.get("wind_speed_10m_max"), i),
            })
        return days

    # BOM radar loop (2026-10-06, Option 1 approved by B.): rides this connector — the id
    # namespace is frozen (D13). Raw PNG layers + rain frames are stored as sidecar files
    # under SNAPSHOT_DIR/radar/; the /weather page stacks them (no server-side compositing).
    # Fixture mode never reaches fetch(), so the committed sample carries no radar.
    RADAR_HOST = "ftp.bom.gov.au"
    RADAR_STATION = "IDR023"                       # Melbourne 128 km (IDR022 is the 256 km view)
    RADAR_FRAMES_DIR = "/anon/gen/radar/"
    RADAR_LAYERS_DIR = "/anon/gen/radar_transparencies/"
    RADAR_LAYERS = ("background", "topography", "locations", "range")
    RADAR_FRAMES = 6
    RADAR_TIMEOUT = 10

    def fetch(self) -> dict:
        raw = self._fetch_forecast()
        radar = self._radar()   # never raises — radar trouble can't fail the weather
        if radar:
            raw["_radar"] = radar
        return raw

    def _radar(self) -> dict | None:
        """Fresh radar block; on any error the previous block (files still on disk)
        marked fetched_ok=False, or None when there never was one."""
        try:
            return fetch_radar(self)
        except Exception as exc:
            log.warning("open_meteo radar step failed: %s: %s", type(exc).__name__, exc)
            prev = ((self._previous() or {}).get("data") or {}).get("radar")
            if isinstance(prev, dict) and prev.get("frames"):
                return {**prev, "fetched_ok": False}
            return None

    def _fetch_forecast(self) -> dict:
        import requests

        response = requests.get(
            self.FORECAST_URL,
            params={
                "latitude": os.environ["WEATHER_LAT"],
                "longitude": os.environ["WEATHER_LON"],
                "current": "temperature_2m,weather_code",
                "hourly": self.HOURLY,
                "daily": self.DAILY,
                "timezone": os.environ.get("TZ", "auto"),
                "forecast_days": 7,
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
        data = {
            "summary": f"{now_c:g} °C · {condition}",
            "secondary": f"{low:g}–{high:g} °C · {rain}% rain",
            "now_c": now_c,
            "condition_text": condition,
            "today_min_c": low,
            "today_max_c": high,
            "rain_prob_pct": rain,
            "hourly": self._hourly(raw),
            "days": self._days(daily),
        }
        if raw.get("_radar"):
            data["radar"] = raw["_radar"]
        return data


RADAR_FRAME_RE = re.compile(r"(?:^|/)(IDR\d{3})\.T\.(\d{12})\.png$")
RADAR_DIRNAME = "radar"


def radar_frame_stamps(names, station: str, count: int) -> list[str]:
    """The latest `count` UTC stamps (YYYYMMDDHHMM) for `station`, oldest first.
    `names` is an FTP NLST — bare names or full paths, any order, other stations mixed in."""
    stamps = set()
    for name in names:
        m = RADAR_FRAME_RE.search(str(name).strip())
        if m and m.group(1) == station:
            stamps.add(m.group(2))
    return sorted(stamps)[-count:] if count > 0 else []


def _write_bytes_atomic(path: Path, blob: bytes) -> None:
    """Same discipline as write_envelope: unique tmp, then os.replace."""
    import threading

    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, path)


def fetch_radar(connector: "OpenMeteo") -> dict:
    """Pull the BOM layers + latest rain frames over anonymous FTP, store them under
    SNAPSHOT_DIR/radar/, prune what no envelope references. Raises on any failure —
    everything is downloaded to memory BEFORE a byte is written, so a failed pull
    leaves the previous set intact."""
    import ftplib
    from contextlib import suppress

    from connectors.base import snapshot_dir

    c = connector
    ftp = ftplib.FTP(c.RADAR_HOST, timeout=c.RADAR_TIMEOUT)
    try:
        ftp.login()
        ftp.set_pasv(True)
        stamps = radar_frame_stamps(ftp.nlst(c.RADAR_FRAMES_DIR), c.RADAR_STATION, c.RADAR_FRAMES)
        if not stamps:
            raise RuntimeError(f"no {c.RADAR_STATION} frames listed")

        def get(path: str) -> bytes:
            chunks: list[bytes] = []
            ftp.retrbinary(f"RETR {path}", chunks.append)
            blob = b"".join(chunks)
            if not blob.startswith(b"\x89PNG"):
                raise ValueError(f"{path.rsplit('/', 1)[-1]} is not a PNG")
            return blob

        layers = {f"layer_{n}.png": get(f"{c.RADAR_LAYERS_DIR}{c.RADAR_STATION}.{n}.png")
                  for n in c.RADAR_LAYERS}
        frames = {f"frame_{s}.png": get(f"{c.RADAR_FRAMES_DIR}{c.RADAR_STATION}.T.{s}.png")
                  for s in stamps}
    finally:
        with suppress(Exception):
            ftp.quit()

    directory = snapshot_dir() / RADAR_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    for name, blob in {**layers, **frames}.items():
        _write_bytes_atomic(directory / name, blob)

    # Keep this set AND the one the current envelope still points at — the hub may be
    # serving the old envelope until run() replaces it; that set goes next sweep.
    prev = ((c._previous() or {}).get("data") or {}).get("radar") or {}
    keep = set(layers) | set(frames) | {
        f.get("file") for f in (prev.get("frames") or []) if isinstance(f, dict)}
    prune_radar_dir(directory, keep)

    return {
        "station": c.RADAR_STATION,
        "fetched_ok": True,
        "layers": list(layers),
        "frames": [{"file": f"frame_{s}.png",
                    "time_iso": datetime.strptime(s, "%Y%m%d%H%M")
                    .replace(tzinfo=timezone.utc).isoformat()}
                   for s in stamps],
    }


def prune_radar_dir(directory: Path, keep: set) -> list[str]:
    """Delete every file in the radar dir not named in `keep` (stray tmp files too)."""
    removed = []
    for p in directory.iterdir():
        if p.is_file() and p.name not in keep:
            try:
                p.unlink()
                removed.append(p.name)
            except OSError as exc:  # a reader holding it open on Windows — next sweep
                log.warning("radar prune skipped %s: %s", p.name, exc)
    return sorted(removed)


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
TICKS_PER_HOUR = TICKS_PER_MINUTE * 60
HISTORY_FETCH_LIMIT = 500  # watched items pulled per sweep
FIXTURE_HER_USER = "georgina"  # fixture mode never reads JELLYFIN_USER_HER
HISTORY_RECENT = 20
HISTORY_TOP = 10           # rows in each most-played / on-this-day list
UP_NEXT_LIMIT = 8
LIBRARY_FETCH_LIMIT = 2000  # whole-library movie/series lists (F3a)

# Jellyfin's PlayState.PlayMethod -> a word, never a colour.
PLAY_METHODS = {"DirectPlay": "Direct play", "DirectStream": "Direct stream", "Transcode": "Transcoding"}


def _media_title(item: dict) -> str:
    """'Show · S02E05 · Episode name' for an episode; the plain name otherwise."""
    if item.get("Type") == "Episode" and item.get("SeriesName"):
        season, number = item.get("ParentIndexNumber"), item.get("IndexNumber")
        code = f"S{int(season):02d}E{int(number):02d}" if season is not None and number is not None else None
        return " · ".join(p for p in (item["SeriesName"], code, item["Name"]) if p)
    return item["Name"]


def _item_kind(item: dict) -> str:
    return "episode" if item.get("Type") == "Episode" else "movie"


def _jf_art(item: dict) -> str | None:
    """Jellyfin item id whose art represents this item: an episode shows its series'
    poster (fallback its own id). Refs are `jf:<id>` / `jfb:<id>` — the hub's /img proxy."""
    if item.get("Type") == "Episode" and item.get("SeriesId"):
        return item["SeriesId"]
    return item.get("Id")


def _jf_ref(prefix: str, item: dict) -> str | None:
    art = _jf_art(item)
    return f"{prefix}:{art}" if art else None


def _jf_key(item: dict) -> str | None:
    """Stable identity for ratings/diary (`item_key`): a movie is `tmdb:<id>` (else
    `jf:<ItemId>`); an episode is its SERIES — the payload carries no series provider
    id, so `jf:<SeriesId>` (episodes without a SeriesId fall back to their own id)."""
    if item.get("Type") == "Episode" and item.get("SeriesId"):
        return f"jf:{item['SeriesId']}"
    tmdb = (item.get("ProviderIds") or {}).get("Tmdb")
    if tmdb:
        return f"tmdb:{tmdb}"
    return f"jf:{item['Id']}" if item.get("Id") else None


def _jf_levels(item: dict) -> dict:
    """Per-level rating keys + numbers for a row (F5). `item_key` stays the show key for
    episodes; these let the hub rate at show / season / episode level. Movies: all null."""
    if item.get("Type") != "Episode":
        return {"show_key": None, "season_key": None, "episode_key": None,
                "season": None, "episode": None, "show_title": None}

    def num(v):
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    return {"show_key": f"jf:{item['SeriesId']}" if item.get("SeriesId") else None,
            "season_key": f"jf:{item['SeasonId']}" if item.get("SeasonId") else None,
            "episode_key": f"jf:{item['Id']}" if item.get("Id") else None,
            "season": num(item.get("ParentIndexNumber")), "episode": num(item.get("IndexNumber")),
            "show_title": item.get("SeriesName")}


def _play_method(session: dict) -> str:
    method = PLAY_METHODS.get(session.get("PlayState", {}).get("PlayMethod"))
    if method:
        return method
    # Older servers omit PlayMethod; a TranscodingInfo block still says it.
    return "Transcoding" if session.get("TranscodingInfo") else "Direct play"


class Jellyfin(Connector):
    id = "jellyfin"
    requires_env = ("JELLYFIN_URL", "JELLYFIN_API_KEY")  # JELLYFIN_USER is optional

    ITEM_FIELDS = "DateCreated,SeriesName,SeriesId,SeasonId,ParentIndexNumber,IndexNumber,ProviderIds"
    MOVIE_FIELDS = "DateCreated,ProviderIds,Genres,ProductionYear,Overview"
    SHOW_FIELDS = "DateCreated,ProviderIds,Genres,ProductionYear,Status,RecursiveItemCount,Overview"

    @classmethod
    def _library_params(cls, kind: str) -> dict:
        return {"IncludeItemTypes": kind, "Recursive": "true", "SortBy": "SortName",
                "SortOrder": "Ascending", "Limit": LIBRARY_FETCH_LIMIT,
                "Fields": cls.MOVIE_FIELDS if kind == "Movie" else cls.SHOW_FIELDS}

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

    @staticmethod
    def pick_her_user(users: list[dict], name: str | None) -> dict | None:
        """Georgina's account by EXACT display name, else None. Never falls back to
        the administrator: her view must not show B.'s data by accident."""
        if not name:
            return None
        return next((u for u in users if u.get("Name") == name and u.get("Id")), None)

    @staticmethod
    def _her_name() -> str | None:
        """JELLYFIN_USER_HER in live mode; fixture mode never reads the real env."""
        if mode() == "fixture":
            return FIXTURE_HER_USER
        return os.environ.get("JELLYFIN_USER_HER") or None

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
        history_params = {
            "Filters": "IsPlayed", "SortBy": "DatePlayed", "SortOrder": "Descending",
            "Recursive": "true", "IncludeItemTypes": "Movie,Episode",
            "Fields": "UserData,RunTimeTicks,SeriesName,SeriesId,SeasonId,ParentIndexNumber,IndexNumber,ProductionYear,ProviderIds",
            "Limit": HISTORY_FETCH_LIMIT}
        raw = {
            "raw_users": users,
            "raw_system": get("system", "/System/Info/Public"),
            "raw_sessions": get("sessions", "/Sessions"),
            "raw_resume": get("resume", f"/Users/{uid}/Items/Resume",
                              {"Limit": 10, "MediaTypes": "Video", **fields}),
            "raw_nextup": get("next up", "/Shows/NextUp", {"UserId": uid, "Limit": 10, **fields}),
            "raw_latest": get("latest", f"/Users/{uid}/Items/Latest", {"Limit": 5, **fields}),
            "raw_counts": get("counts", "/Items/Counts", {"UserId": uid}),
            "raw_history": get("history", f"/Users/{uid}/Items", history_params),
            # Library lists (F3a). Two extra GETs (four with her) ride the 2-minute sweep;
            # acceptable for a 42-film library; a split sweep is a later decision.
            "raw_movies": get("movies", f"/Users/{uid}/Items", self._library_params("Movie")),
            "raw_shows": get("shows", f"/Users/{uid}/Items", self._library_params("Series")),
        }
        # Georgina's view (2026-10-05): only when JELLYFIN_USER_HER names an existing user.
        her = self.pick_her_user(users, self._her_name())
        if her:
            hid = her["Id"]
            raw["raw_her_resume"] = get("her resume", f"/Users/{hid}/Items/Resume",
                                        {"Limit": 10, "MediaTypes": "Video", **fields})
            raw["raw_her_nextup"] = get("her next up", "/Shows/NextUp",
                                        {"UserId": hid, "Limit": 10, **fields})
            raw["raw_her_history"] = get("her history", f"/Users/{hid}/Items", history_params)
            raw["raw_her_movies"] = get("her movies", f"/Users/{hid}/Items", self._library_params("Movie"))
            raw["raw_her_shows"] = get("her shows", f"/Users/{hid}/Items", self._library_params("Series"))
        elif os.environ.get("JELLYFIN_USER_HER"):
            log.info("jellyfin: her user not found")
        return raw

    @staticmethod
    def _library_row(item: dict) -> dict:
        """Fields shared by movie and show library rows."""
        user = item.get("UserData") or {}
        rating = item.get("CommunityRating")
        return {
            "title": item["Name"],
            "year": item.get("ProductionYear"),
            "jf_id": item["Id"],
            "poster": _jf_ref("jf", item), "backdrop": _jf_ref("jfb", item),
            "played": bool(user.get("Played")),
            "last_played_at": user.get("LastPlayedDate"),
            "added_at": item.get("DateCreated"),
            "community_rating": round(float(rating), 1) if rating is not None else None,
            "genres": list(item.get("Genres") or [])[:3],
        }

    @classmethod
    def _movies(cls, payload: dict) -> list[dict]:
        rows = []
        for item in (payload or {}).get("Items", []):
            ticks = item.get("RunTimeTicks")
            rows.append({**cls._library_row(item), "item_key": _jf_key(item),
                         "runtime_min": int(ticks) // TICKS_PER_MINUTE if ticks else None})
        return rows

    @classmethod
    def _shows(cls, payload: dict) -> list[dict]:
        rows = []
        for item in (payload or {}).get("Items", []):
            ids = item.get("ProviderIds") or {}
            key = (f"tmdb:{ids['Tmdb']}" if ids.get("Tmdb")
                   else f"tvdb:{ids['Tvdb']}" if ids.get("Tvdb") else f"jf:{item['Id']}")
            rows.append({**cls._library_row(item), "item_key": key,
                         "status_word": {"Continuing": "Continuing", "Ended": "Ended"}.get(
                             item.get("Status"), "Unknown"),
                         "episodes": int(item.get("RecursiveItemCount") or 0),
                         "unplayed": int((item.get("UserData") or {}).get("UnplayedItemCount") or 0)})
        return rows

    @staticmethod
    def _history(items: list[dict], now: datetime) -> dict:
        """Watch history for the history page: windows, hours, top shows/movies, on-this-day."""
        week, month = now - timedelta(days=7), now - timedelta(days=30)
        played = []  # (item, last-played datetime, runtime hours, plays)
        for item in items:
            stamp = (item.get("UserData") or {}).get("LastPlayedDate")
            if not stamp:
                continue
            plays = int((item.get("UserData") or {}).get("PlayCount") or 1)
            played.append((item, _dt(stamp), int(item.get("RunTimeTicks") or 0) / TICKS_PER_HOUR, plays))
        played.sort(key=lambda p: p[1], reverse=True)

        shows: dict[str, dict] = {}
        for item, _, hours, plays in played:
            if _item_kind(item) == "episode" and item.get("SeriesName"):
                show = shows.setdefault(item["SeriesName"], {"title": item["SeriesName"], "episodes": 0, "hours": 0.0,
                                                             "poster": _jf_ref("jf", item),
                                                             "item_key": _jf_key(item)})
                show["episodes"] += 1
                show["hours"] += hours * plays
        movies = sorted(({"title": item["Name"], "plays": plays, "poster": _jf_ref("jf", item),
                          "item_key": _jf_key(item)} for item, _, _, plays in played
                         if _item_kind(item) == "movie" and plays >= 1),
                        key=lambda m: (-m["plays"], m["title"]))
        return {
            "recent": [{"title": _media_title(item), "kind": _item_kind(item),
                        "watched_at": item["UserData"]["LastPlayedDate"], "when": _ago(dt, now),
                        "poster": _jf_ref("jf", item), "item_key": _jf_key(item),
                        "jf_id": item.get("Id"), **_jf_levels(item)}
                       for item, dt, _, _ in played[:HISTORY_RECENT]],
            "week_count": sum(1 for _, dt, _, _ in played if dt >= week),
            "month_count": sum(1 for _, dt, _, _ in played if dt >= month),
            "hours_total": round(sum(h * plays for _, _, h, plays in played), 1),
            "hours_month": round(sum(h for _, dt, h, _ in played if dt >= month), 1),
            "most_played_shows": [{**s, "hours": round(s["hours"], 1)} for s in sorted(
                shows.values(), key=lambda s: (-s["episodes"], s["title"]))[:HISTORY_TOP]],
            "most_played_movies": movies[:HISTORY_TOP],
            "on_this_day": [{"title": _media_title(item), "kind": _item_kind(item), "years_ago": now.year - dt.year,
                             "poster": _jf_ref("jf", item), "item_key": _jf_key(item),
                             "jf_id": item.get("Id")}
                            for item, dt, _, _ in played
                            if (dt.month, dt.day) == (now.month, now.day) and dt.year < now.year][:HISTORY_TOP],
        }

    @staticmethod
    def _up_next(resume: dict, nextup: dict) -> list[dict]:
        """Resume items first, then next-episode suggestions not already resumable."""
        up_next, seen = [], set()
        for item in resume["Items"]:
            runtime = int(item.get("RunTimeTicks") or 0)
            position = int(item.get("UserData", {}).get("PlaybackPositionTicks") or 0)
            left = max(0, runtime - position) // TICKS_PER_MINUTE
            seen.add(item.get("Id"))
            up_next.append({
                "title": _media_title(item),
                "kind": "episode" if item.get("Type") == "Episode" else "movie",
                "remaining_text": f"{left} min left",
                "poster": _jf_ref("jf", item), "backdrop": _jf_ref("jfb", item),
                "item_key": _jf_key(item), "jf_id": item.get("Id"), **_jf_levels(item),
            })
        for item in nextup["Items"]:
            if item.get("Id") in seen:  # already resumable — don't list twice
                continue
            up_next.append({"title": _media_title(item), "kind": "episode",
                            "remaining_text": "Next episode",
                            "poster": _jf_ref("jf", item), "backdrop": _jf_ref("jfb", item),
                            "item_key": _jf_key(item), "jf_id": item.get("Id"), **_jf_levels(item)})
        return up_next[:UP_NEXT_LIMIT]

    def _her_block(self, raw: dict) -> dict | None:
        """Georgina's up next + history, or None when her keys are absent."""
        if not all(k in raw for k in ("raw_her_resume", "raw_her_nextup", "raw_her_history")):
            return None
        user = self.pick_her_user(raw.get("raw_users") or [], self._her_name())
        block = {"user": (user or {}).get("Name") or "her",
                 "up_next": self._up_next(raw["raw_her_resume"], raw["raw_her_nextup"]),
                 "history": self._history(raw["raw_her_history"].get("Items", []), _now())}
        if "raw_her_movies" in raw:
            block["movies"] = self._movies(raw["raw_her_movies"])
        if "raw_her_shows" in raw:
            block["shows"] = self._shows(raw["raw_her_shows"])
        return block

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
                "poster": _jf_ref("jf", item),
                "backdrop": _jf_ref("jfb", item),
                "item_key": _jf_key(item),
                "jf_id": item.get("Id"),
                **_jf_levels(item),
            })

        up_next = self._up_next(raw["raw_resume"], raw["raw_nextup"])

        latest = [
            {"title": i["Name"], "added_at": i["DateCreated"], "type": i["Type"], "poster": _jf_ref("jf", i),
             "item_key": _jf_key(i), "jf_id": i.get("Id")}
            for i in raw["raw_latest"]
        ]
        counts = raw["raw_counts"]
        first = now_playing[0] if now_playing else None
        if first:
            secondary = f"{first['title']} · {first['user']} · {first['play_method']}"
        else:
            secondary = up_next[0]["title"] if up_next else "Nothing up next"
        library_lists = {}
        if "raw_movies" in raw:  # older fixtures/snapshots carry none - the keys stay absent
            library_lists["movies"] = self._movies(raw["raw_movies"])
        if "raw_shows" in raw:
            library_lists["shows"] = self._shows(raw["raw_shows"])
        return {
            **library_lists,
            "summary": (
                f"{len(now_playing)} playing now" if now_playing
                else f"Nothing playing · {len(up_next)} up next"
            ),
            "secondary": secondary,
            "now_playing": now_playing,
            "up_next": up_next,
            "latest": latest,
            "server_id": (raw.get("raw_system") or {}).get("Id"),  # older fixtures carry none
            "library": {
                "movies": int(counts["MovieCount"]),
                "episodes": int(counts["EpisodeCount"]),
            },
            # older fixtures/snapshots carry no raw_history — an empty block, never a failure
            "history": self._history((raw.get("raw_history") or {}).get("Items", []), _now()),
            "her": self._her_block(raw),
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


def _arr_ref(app: str, record: dict, movie: bool = False) -> str | None:
    """`radarr:<movieId>` / `sonarr:<seriesId>` for the hub's /img proxy (episode and
    season rows use the series id). Nested movie/series wins, the flat id is the
    fallback; `movie=True` marks a Radarr calendar row, whose own id is the movie id."""
    if app == "radarr":
        art = (record.get("movie") or {}).get("id") or record.get("movieId") or (record.get("id") if movie else None)
    else:
        art = (record.get("series") or {}).get("id") or record.get("seriesId")
    return f"{app}:{art}" if art else None


def _arr_key(app: str, record: dict, movie: bool = False) -> str | None:
    """`tmdb:<tmdbId>` (Radarr) / `tvdb:<tvdbId>` (Sonarr) from the nested movie/series
    object, or from the record itself for a Radarr calendar row (`movie=True`)."""
    if app == "radarr":
        tmdb = (record.get("movie") or (record if movie else {})).get("tmdbId")
        return f"tmdb:{tmdb}" if tmdb else None
    tvdb = (record.get("series") or {}).get("tvdbId")
    return f"tvdb:{tvdb}" if tvdb else None


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
            row = {"title": title, "kind": kind, "when": _ago(when, now), "at": when.isoformat(),
                   "poster": _arr_ref("sonarr" if grouped else "radarr", newest),
                   "item_key": _arr_key("sonarr" if grouped else "radarr", newest)}
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
                rows.append({"title": m["title"], "kind": "movie", "date": day.isoformat(), "label": label,
                             "poster": _arr_ref("radarr", m, movie=True),
                             "item_key": _arr_key("radarr", m, movie=True)})
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
                         "kind": "episode", "date": day.isoformat(), "label": label,
                         "poster": _arr_ref("sonarr", e), "item_key": _arr_key("sonarr", e)})
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
                "poster": _arr_ref(app, r), "item_key": _arr_key(app, r),
                # the download client's id (a torrent hash) — joins a qbittorrent row
                "download_id": str(r["downloadId"]).lower() if r.get("downloadId") else None,
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

        # Already arrived this week -> not also listed under "This week". Sonarr keys are
        # per series, so a row only counts as arrived when its title starts with the arrived
        # row's (a season group "Show · S02 · 3 episodes" matches its S02 episodes only).
        arrived_prefix = [(r["item_key"], re.sub(r" · \d+ episodes$", "", r["title"]))
                          for r in arrived_rows if r.get("item_key")]
        this_week = [r for r in self._this_week(_records(raw.get("raw_radarr_calendar")),
                                                _records(raw.get("raw_sonarr_calendar")), now)
                     if not any(r["item_key"] == k and r["title"].startswith(pre)
                                for k, pre in arrived_prefix)]
        downloading = (self._queue("radarr", _records(raw.get("raw_radarr_queue")))
                       + self._queue("sonarr", _records(raw.get("raw_sonarr_queue"))))

        disk, seen = [], set()
        for d in _records(raw.get("raw_radarr_diskspace")) + _records(raw.get("raw_sonarr_diskspace")):
            total, free = int(d.get("totalSpace") or 0), int(d.get("freeSpace") or 0)
            # One NAS volume shows up under several mount paths: dedupe on the sizes (to the GiB).
            volume = (round(total / GIB), round(free / GIB))
            if volume in seen or not total:
                continue
            seen.add(volume)
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


# ---------------------------------------------------------------- jellyseerr

SEERR_LIST_TAKE = 50       # requests fetched per sweep
SEERR_ROW_LIMIT = 30       # rows kept in the data block
SEERR_LOOKUP_CAP = 20      # new TMDB title lookups per sweep (the rest keep "TMDB #id")
# Jellyseerr request.status / media.status -> a word, never a colour.
SEERR_REQUEST_STATUS = {1: "Pending", 2: "Approved", 3: "Declined"}
SEERR_MEDIA_STATUS = {5: "Available", 4: "Partly available", 3: "Processing"}


def _seerr_kind(request: dict) -> str:
    kind = request.get("type") or (request.get("media") or {}).get("mediaType")
    return "tv" if kind == "tv" else "movie"


def _seerr_status_text(request: dict) -> str:
    text = SEERR_REQUEST_STATUS.get(request.get("status"), "Pending")
    if text == "Approved":  # an approved request reports how far the download got
        text = SEERR_MEDIA_STATUS.get((request.get("media") or {}).get("status"), text)
    return text


def _seerr_year(value) -> int | None:
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


class Jellyseerr(Connector):
    """Jellyseerr's request queue. Titles come from per-request TMDB lookups,
    capped per sweep and reused from the previous envelope; one failed lookup
    leaves that row as 'TMDB #id' and never fails the run."""

    id = "jellyseerr"
    requires_env = ("JELLYSEERR_URL", "JELLYSEERR_API_KEY")

    def fetch(self) -> dict:
        import requests

        base = os.environ["JELLYSEERR_URL"].rstrip("/")
        headers = {"X-Api-Key": os.environ["JELLYSEERR_API_KEY"]}

        def get(label: str, path: str, params: dict | None = None):
            try:
                response = requests.get(base + path, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                # Reason is type/status ONLY — requests exception text embeds the
                # server URL, and this string ends up in envelopes and logs.
                raise RuntimeError(f"Jellyseerr {label} failed ({_safe_reason(exc)})") from None

        raw_count = get("count", "/api/v1/request/count")
        raw_requests = get("requests", "/api/v1/request",
                           {"take": SEERR_LIST_TAKE, "skip": 0, "sort": "added", "filter": "all"})

        # Titles already resolved last sweep are reused, so repeats cost no calls.
        known: dict[str, dict] = {}
        for row in ((self._previous() or {}).get("data") or {}).get("requests", []):
            if (row.get("tmdb_id") and "poster" in row  # pre-poster rows are looked up again
                    and not str(row.get("title", "")).startswith("TMDB #")):
                known[f"{row['kind']}:{row['tmdb_id']}"] = {
                    "title": row["title"], "name": row["title"],
                    "releaseDate": str(row["year"]) if row.get("year") else None,
                    "posterPath": (row.get("poster") or "").removeprefix("tmdb:") or None}
        titles, lookups = {}, 0
        for request in raw_requests.get("results", []):
            tmdb = (request.get("media") or {}).get("tmdbId")
            if not tmdb:
                continue
            kind = _seerr_kind(request)
            key = f"{kind}:{tmdb}"
            if key in titles:
                continue
            if key in known:
                titles[key] = known[key]
            elif lookups < SEERR_LOOKUP_CAP:
                lookups += 1
                try:
                    titles[key] = get("title lookup", f"/api/v1/{kind}/{tmdb}")
                except Exception:  # row stays "TMDB #id"
                    pass
        return {"raw_count": raw_count, "raw_requests": raw_requests, "raw_titles": titles}

    def transform(self, raw: dict) -> dict:
        now = _now()
        host = (f"http://{FIXTURE_MEDIA_HOST}:5055" if mode() == "fixture"
                else os.environ["JELLYSEERR_URL"].rstrip("/"))
        titles = raw.get("raw_titles") or {}
        rows: list[tuple[bool, datetime, dict]] = []
        for request in (raw.get("raw_requests") or {}).get("results", []):
            media = request.get("media") or {}
            tmdb = media.get("tmdbId")
            kind = _seerr_kind(request)
            info = titles.get(f"{kind}:{tmdb}") or {}
            title = info.get("title") or info.get("name") or f"TMDB #{tmdb}"
            created = _dt(request["createdAt"])
            by = request.get("requestedBy") or {}
            rows.append((request.get("status") == 1, created, {
                "id": int(request["id"]),
                "kind": kind,
                "tmdb_id": int(tmdb) if tmdb else 0,
                "title": title,
                "year": _seerr_year(info.get("releaseDate") or info.get("firstAirDate")),
                "requested_by": by.get("displayName") or by.get("username") or "someone",
                "status_text": _seerr_status_text(request),
                "when": _ago(created, now),
                "href": f"{host}/{kind}/{tmdb}",
                "poster": f"tmdb:{info['posterPath']}" if info.get("posterPath") else None,
                "item_key": f"tmdb:{tmdb}" if tmdb else None,
            }))
        rows.sort(key=lambda r: r[1], reverse=True)    # newest first ...
        rows.sort(key=lambda r: not r[0])              # ... then pending first (stable)
        requests_out = [r[2] for r in rows][:SEERR_ROW_LIMIT]

        count = raw.get("raw_count") or {}
        counts = {k: int(count.get(k) or 0)
                  for k in ("pending", "approved", "available", "declined", "total")}
        pending = [r for r in requests_out if r["status_text"] == "Pending"]
        open_requests = counts["pending"] or counts["approved"]
        return {
            "summary": (f"{counts['pending']} pending · {counts['approved']} approved"
                        if open_requests else "No open requests"),
            "secondary": pending[0]["title"] if pending else "",
            "counts": counts,
            "requests": requests_out,
        }


# --------------------------------------------------------------- qbittorrent

QBIT_ROW_LIMIT = 20
QBIT_FINISHED_WINDOW = 86400  # seconds: "finished today" = completed in the last 24 h
QBIT_ETA_INFINITE = 8640000   # qBittorrent's "no ETA" sentinel
# Download-side states -> a word, never a colour.
QBIT_ACTIVE_STATES = {
    "downloading": "Downloading", "forcedDL": "Downloading", "stalledDL": "Stalled",
    "metaDL": "Fetching metadata", "forcedMetaDL": "Fetching metadata",
    "pausedDL": "Paused", "stoppedDL": "Paused", "queuedDL": "Queued",
    "checkingDL": "Checking", "allocating": "Allocating",
}
QBIT_PAUSED_STATES = {"pausedDL", "stoppedDL"}
QBIT_SEEDING_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP", "pausedUP", "stoppedUP"}


def _bytes_text(n) -> str:
    """Decimal units, as a person reads them: '230 kB', '1.4 MB', '900 MB', '4.2 GB'.
    kB and anything >= 100 are whole numbers; smaller MB/GB/TB keep one decimal."""
    value = float(n or 0)
    if value < 1000:
        return f"{int(value)} B"
    for unit in ("kB", "MB", "GB", "TB"):
        value /= 1000
        if value < 999.5 or unit == "TB":
            break
    return f"{value:.0f} {unit}" if unit == "kB" or value >= 99.95 else f"{value:.1f} {unit}"


def _eta_text(seconds) -> str:
    """qBittorrent eta seconds -> '12 min' / '2 h 05 min' (blank when unknown or infinite)."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0 or seconds >= QBIT_ETA_INFINITE:
        return ""
    minutes = max(1, round(seconds / 60))
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def _qbit_kind(category) -> str:
    cat = str(category or "").lower()
    if "radarr" in cat or "movie" in cat:
        return "movie"
    if "sonarr" in cat or "tv" in cat:
        return "tv"
    return "other"


def _epoch_iso(ts) -> str:
    return datetime.fromtimestamp(int(ts or 0), timezone.utc).isoformat(timespec="seconds")


class QBittorrent(Connector):
    """qBittorrent Web API, read only: what is downloading, what finished in the
    last 24 h, how much is seeding, and the global transfer speeds."""

    id = "qbittorrent"
    requires_env = ("QBIT_URL", "QBIT_USER", "QBIT_PASS")

    def fetch(self) -> dict:
        import requests

        base = os.environ["QBIT_URL"].rstrip("/")
        session = requests.Session()
        step = "login"
        try:
            response = session.post(f"{base}/api/v2/auth/login",
                                    data={"username": os.environ["QBIT_USER"],
                                          "password": os.environ["QBIT_PASS"]},
                                    headers={"Referer": base}, timeout=10)
            # 5.x answers 204 + empty body; older builds 200 "Ok." / "Fails.". Either
            # way the session cookie (SID / QBT_SID / QBT_SID_<port>) is the proof.
            has_sid = any(c.name == "SID" or c.name.startswith("QBT_SID") for c in session.cookies)
            if response.status_code >= 400 or not has_sid:
                raise PermissionError
            raw = {}
            for step, key, path in (("torrents", "raw_torrents", "/api/v2/torrents/info"),
                                    ("transfer", "raw_transfer", "/api/v2/transfer/info")):
                response = session.get(base + path, timeout=10)
                response.raise_for_status()
                raw[key] = response.json()
            return raw
        except PermissionError:
            raise RuntimeError("login refused") from None
        except Exception as exc:
            # Reason is type/status ONLY — requests exception text embeds the
            # server URL, and this string ends up in envelopes and logs.
            raise RuntimeError(f"qBittorrent {step} failed ({_arr_reason(exc)})") from None
        finally:
            session.close()

    def transform(self, raw: dict) -> dict:
        now = _now().timestamp()
        torrents = raw.get("raw_torrents") or []
        transfer = raw.get("raw_transfer") or {}

        def size_text(t: dict) -> str:
            return _bytes_text(t.get("size") or t.get("total_size"))

        active = [t for t in torrents if t.get("state") in QBIT_ACTIVE_STATES]
        # downloading-with-speed first, then by progress (desc); stable for ties
        active.sort(key=lambda t: (int(t.get("dlspeed") or 0) > 0, float(t.get("progress") or 0)),
                    reverse=True)
        active_rows = []
        for t in active[:QBIT_ROW_LIMIT]:
            state, speed = t["state"], int(t.get("dlspeed") or 0)
            active_rows.append({
                "hash": str(t.get("hash") or "").lower(),
                "name": str(t.get("name") or "Unknown"),
                "kind": _qbit_kind(t.get("category")),
                "category": str(t.get("category") or ""),
                "pct": min(100, max(0, int(float(t.get("progress") or 0) * 100))),
                "state_text": QBIT_ACTIVE_STATES[state],
                "speed_text": f"{_bytes_text(speed)}/s" if speed > 0 else "",
                "eta_text": "" if state in QBIT_PAUSED_STATES else _eta_text(t.get("eta")),
                "size_text": size_text(t),
                "added": _epoch_iso(t.get("added_on")),
            })

        done = [t for t in torrents
                if int(t.get("completion_on") or 0) > 0
                and now - int(t["completion_on"]) <= QBIT_FINISHED_WINDOW]
        done.sort(key=lambda t: int(t["completion_on"]), reverse=True)
        finished = [{
            "hash": str(t.get("hash") or "").lower(),
            "name": str(t.get("name") or "Unknown"),
            "kind": _qbit_kind(t.get("category")),
            "size_text": size_text(t),
            "when": _epoch_iso(t["completion_on"]),
        } for t in done[:QBIT_ROW_LIMIT]]

        seeding = sum(1 for t in torrents if t.get("state") in QBIT_SEEDING_STATES)
        dl, up = int(transfer.get("dl_info_speed") or 0), int(transfer.get("up_info_speed") or 0)
        totals = {"dl_bps": dl, "up_bps": up,
                  "dl_text": f"{_bytes_text(dl)}/s", "up_text": f"{_bytes_text(up)}/s"}

        if active:
            summary = f"{len(active)} downloading" + (f" · {totals['dl_text']}" if dl > 0 else "")
        else:
            summary = "Nothing downloading"
        finished_text = f"{len(done)} finished today" if done else "Nothing finished today"
        return {
            "summary": summary,
            "secondary": f"{seeding} seeding · {finished_text}" if seeding else finished_text,
            "active": active_rows,
            "finished": finished,
            "seeding": seeding,
            "totals": totals,
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
    OpenMeteo, Gcal, MacroMates, HomeAssistant, Jellyfin, MediaStatus, Arr, Jellyseerr, QBittorrent, NasStats,
)

for _cls in STUBS:
    registry.register(_cls, _cls.id)
