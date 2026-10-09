"""Weather: Open-Meteo forecast (one GET: now, 24 hours, 7 days). The parked BOM radar loop was removed
2026-10-09 (decision 5); Windy is the /weather radar."""

from __future__ import annotations

import os

from connectors.base import Connector
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

    def fetch(self) -> dict:
        return self._fetch_forecast()

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
        return data
