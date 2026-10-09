"""Weather: Open-Meteo forecast (one GET: now, 24 hours, 7 days) plus the BOM radar
loop, which is gated off unless RADAR_LOOP=1 (2026-10-07)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from connectors.base import Connector, log
from connectors.feeds._http import http_json


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
        # RADAR SUPERSESSION (2026-10-07): Windy is the radar surface; the BOM fetch is
        # gated OFF by default and runs only with RADAR_LOOP=1 (code kept for a switch back).
        if os.environ.get("RADAR_LOOP") != "1":
            return raw
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
        # One call, so no session. The URL's query carries the home coordinates; http_json's
        # reason is type/status only (C-06).
        return http_json("Open-Meteo forecast", self.FORECAST_URL, params={
            "latitude": os.environ["WEATHER_LAT"],
            "longitude": os.environ["WEATHER_LON"],
            "current": "temperature_2m,weather_code",
            "hourly": self.HOURLY,
            "daily": self.DAILY,
            # `or`, not a .get default: compose passes a blank `TZ=` through as ""
            "timezone": os.environ.get("TZ") or "auto",
            "forecast_days": 7,
        })

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
    """Same discipline as write_envelope: unique tmp, then os.replace (with its
    Windows reader-lock retry)."""
    import threading

    from connectors.base import replace_with_retry

    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(blob)
    replace_with_retry(tmp, path)


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
