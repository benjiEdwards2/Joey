"""Weather (W3 split of hub/main.py, H-44): the hub glimpse card (find_weather), the /weather forecast page with
its 24-hour chart and 7-day strip, and the Windy radar embed (the parked BOM radar was removed 2026-10-09, decision 5).
"""

from __future__ import annotations

import os
from datetime import date, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from hub import shell
from hub.ids import WEATHER_SNAPSHOT_ID, home_now
from hub.store import connected, data_of, tile_state

router = APIRouter()


# Hub weather glimpse (2026-09-11 decision — supersedes D18). The glimpse reuses
# the registry tile that reads this snapshot (Calendar's weather tile), so its
# stale_after/owner/states stay single-sourced in areas.yaml. Keyed by the connector id
# WEATHER_SNAPSHOT_ID (hub/ids.py), not an area name (WP17 grep exception, as in registry.py).

# Keyword -> wx-* glyph id, first match wins ("snow showers" must hit snow
# before shower). The condition word always renders beside the glyph.
_WEATHER_GLYPHS = (
    ("thunder", "wx-thunder"),
    ("snow", "wx-snow"), ("sleet", "wx-snow"), ("ice", "wx-snow"), ("freezing", "wx-snow"),
    ("rain", "wx-rain"), ("drizzle", "wx-rain"), ("shower", "wx-rain"),
    ("fog", "wx-fog"), ("mist", "wx-fog"),
    ("clear", "wx-sun"), ("sun", "wx-sun"),
)


def weather_glyph(condition_text) -> str:
    text = (condition_text or "").lower()
    for word, glyph in _WEATHER_GLYPHS:
        if word in text:
            return glyph
    return "wx-cloud"


RAIN_LIKELY_PCT = 30   # E5 (W1, 2026-10-13): an hour at or above this chance is "rain"; below it all day is "dry"


def _rain_today(hourly, now: datetime) -> list[tuple[str, int]] | None:
    """(HH:MM, chance) for the snapshot's hours from now's hour to the end of now's day (home-local ISO times); None
    when the snapshot carries no such hour (no hourly data, or a snapshot from yesterday)."""
    floor = now.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    out = []
    for h in hourly or []:
        if not isinstance(h, dict):
            continue
        try:
            at = datetime.fromisoformat(str(h.get("time"))[:16])
        except ValueError:
            continue
        pct = h.get("rain_prob_pct")
        if at.date() == floor.date() and at >= floor and isinstance(pct, int) and not isinstance(pct, bool):
            out.append((f"{at:%H:%M}", pct))
    return out or None


def rain_words(hourly, now: datetime, short: bool = False) -> str | None:
    """Rain timing in words (E5, W1): the first hour left today at RAIN_LIKELY_PCT or more and the day's peak chance —
    "Rain likely from 15:00 · 70%" (short, for the hub's Today line: "Rain from 15:00"); "Dry until tomorrow" ("Dry
    today") when every hour left today is under it; None without hourly data (a missing feed drops the words)."""
    hours = _rain_today(hourly, now)
    if hours is None:
        return None
    wet = [(t, p) for t, p in hours if p >= RAIN_LIKELY_PCT]
    if not wet:
        return "Dry today" if short else "Dry until tomorrow"
    start, peak = wet[0][0], max(p for _, p in wet)
    return f"Rain from {start}" if short else f"Rain likely from {start} · {peak}%"


def week_strip(data: dict) -> list[dict]:
    """The glimpse's 7-day row (E5; BACKLOG "7-day forecast on the weather glimpse"): one day letter, glyph, condition
    word (for the screen reader) and max temperature per day, from the same `days` the /weather strip reads."""
    out = []
    for i, d in enumerate([d for d in (data.get("days") or []) if isinstance(d, dict)][:7]):
        try:
            day = date.fromisoformat(str(d.get("date")))
        except ValueError:
            continue
        out.append({"letter": f"{day:%a}"[0], "name": "Today" if i == 0 else f"{day:%A}",
                    "glyph": weather_glyph(d.get("condition_text")), "word": d.get("condition_text") or "—",
                    "max": _wx_num(d.get("max_c"))})
    return out


def find_weather(snaps, now: datetime | None = None) -> dict | None:
    """The hub glimpse card: first registry tile reading the weather snapshot (E5: plus its rain words and 7-day row)."""
    for a in shell.registry.areas:
        for t in a.tiles:
            if t.snapshot == WEATHER_SNAPSHOT_ID:
                data = data_of(snaps.get(WEATHER_SNAPSHOT_ID))
                return {"tile": t, "st": tile_state(t, snaps),
                        "glyph": weather_glyph(data.get("condition_text")), "data": data,
                        "rain": rain_words(data.get("hourly"), now or home_now()), "week": week_strip(data)}
    return None


# /weather forecast (2026-10-06 weather upgrade): hero extras, a 24-hour chart drawn as
# inline SVG by Jinja (no JS), and the 7-day strip. Every number also renders as text.
# Envelopes written before the upgrade have no `hourly`/`days` — those sections are then
# simply absent, never a crash.
WX_CHART_W, WX_CHART_H = 720, 230
WX_CHART_PAD = 14
WX_TEMP_TOP, WX_TEMP_BOTTOM = 34, 118     # temperature line band
WX_RAIN_BASE, WX_RAIN_MAX_H = 196, 56     # rain-chance bars grow up from the base
WX_LABEL_EVERY = 3                        # value labels on every 3rd hour; the hour list has all


def _wx_num(v) -> str | None:
    """18.3 -> "18.3", 24.0 -> "24" (same :g as the connector's summary); None if not a number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return f"{v:g}"


def _wx_uv_word(uv) -> str | None:
    if not isinstance(uv, (int, float)):
        return None
    for limit, word in ((3, "low"), (6, "moderate"), (8, "high"), (11, "very high")):
        if uv < limit:
            return word
    return "extreme"


def _wx_day_label(iso: str, first: bool) -> str:
    if first:
        return "Today"
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return str(iso)
    return f"{d:%a} {d.day}"


def _wx_chart(hourly: list[dict]) -> dict | None:
    """SVG geometry for the 24-hour chart; None when there is nothing to draw."""
    temps = [h["temp_c"] for h in hourly if isinstance(h.get("temp_c"), (int, float))]
    if not hourly or not temps:
        return None
    lo, hi = min(temps), max(temps)
    span = (hi - lo) or 1.0
    step = (WX_CHART_W - 2 * WX_CHART_PAD) / len(hourly)
    points = []
    for i, h in enumerate(hourly):
        x = round(WX_CHART_PAD + (i + 0.5) * step, 1)
        temp, rain = h.get("temp_c"), h.get("rain_prob_pct")
        y = (round(WX_TEMP_BOTTOM - (temp - lo) / span * (WX_TEMP_BOTTOM - WX_TEMP_TOP), 1)
             if isinstance(temp, (int, float)) else None)
        bar_h = round(rain / 100 * WX_RAIN_MAX_H, 1) if isinstance(rain, (int, float)) else 0
        points.append({
            "x": x, "y": y, "bar_x": round(x - step * 0.35, 1), "bar_w": round(step * 0.7, 1),
            "bar_y": round(WX_RAIN_BASE - bar_h, 1), "bar_h": bar_h,
            "hour": str(h.get("time", ""))[11:13], "temp": _wx_num(temp), "rain": rain,
            "label": i % WX_LABEL_EVERY == 0,
        })
    return {
        "w": WX_CHART_W, "h": WX_CHART_H, "base": WX_RAIN_BASE, "pad": WX_CHART_PAD,
        "line": " ".join(f"{p['x']},{p['y']}" for p in points if p["y"] is not None),
        "points": points, "lo": _wx_num(lo), "hi": _wx_num(hi),
    }


def weather_forecast(snaps) -> dict | None:
    """Template context for /weather beyond today's core fields; None when not connected."""
    snap = snaps.get(WEATHER_SNAPSHOT_ID)
    if not connected(snap) or not isinstance(snap.data, dict):
        return None
    data = snap.data
    hourly = [h for h in (data.get("hourly") or []) if isinstance(h, dict)]
    days = [d for d in (data.get("days") or []) if isinstance(d, dict)]
    today = days[0] if days else {}
    now = hourly[0] if hourly else {}
    return {
        "feels": _wx_num(now.get("feels_c")),
        "wind": _wx_num(today.get("wind_max_kmh")),
        "uv": _wx_num(today.get("uv_max")), "uv_word": _wx_uv_word(today.get("uv_max")),
        "sunrise": today.get("sunrise"), "sunset": today.get("sunset"),
        "hours": [{"hour": str(h.get("time", ""))[11:16], "temp": _wx_num(h.get("temp_c")),
                   "feels": _wx_num(h.get("feels_c")), "rain": h.get("rain_prob_pct")}
                  for h in hourly],
        "chart": _wx_chart(hourly),
        "days": [{"label": _wx_day_label(d.get("date"), i == 0), "date": d.get("date"),
                  "word": d.get("condition_text") or "—",   # guide §9: missing is "—"
                  "glyph": weather_glyph(d.get("condition_text")),
                  "min": _wx_num(d.get("min_c")), "max": _wx_num(d.get("max_c")),
                  "rain": d.get("rain_prob_pct")}
                 for i, d in enumerate(days)],
    }


# RADAR SUPERSESSION (2026-10-07, B.'s call): the /weather radar is a Windy embed — the
# browser loads embed.windy.com directly (a recorded exception to "the phone talks only to
# Joey"). Coordinates come from the same WEATHER_LAT/LON the open_meteo connector reads,
# so they live in one place (.env); Newport VIC is the fallback when unset or unparsable.
WINDY_EMBED = "https://embed.windy.com/embed2.html"
WINDY_DEFAULT = (-37.84, 144.88)   # Newport VIC
WINDY_ZOOM = 8


def windy_embed_url() -> str:
    try:
        lat, lon = float(os.environ["WEATHER_LAT"]), float(os.environ["WEATHER_LON"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except (KeyError, ValueError):
        lat, lon = WINDY_DEFAULT
    return (f"{WINDY_EMBED}?lat={lat}&lon={lon}&detailLat={lat}&detailLon={lon}"
            f"&zoom={WINDY_ZOOM}&level=surface&overlay=radar&product=radar&type=map"
            f"&location=coordinates&metricWind=km%2Fh&metricTemp=%C2%B0C"
            f"&calendar=now&menu=&message=&marker=&pressure=&detail=&detectRotation=false")


@router.get("/weather", response_class=HTMLResponse)
def weather_page(request: Request):
    """Detail behind the hub glimpse (2026-09-11). Reads the same snapshot; today plus,
    since the 2026-10-06 upgrade, the next 24 hours and 7 days when the snapshot has them."""
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)
    resp = shell.render_page(request, "weather.html", {
        "w": find_weather(snaps),
        "fc": weather_forecast(snaps),
        "windy_src": windy_embed_url(),
    })
    return shell._maybe_set_cookie(resp, view, from_query)

