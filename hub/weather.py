"""Weather (W3 split of hub/main.py, H-44): the hub glimpse card (find_weather), the /weather forecast page with
its 24-hour chart and 7-day strip, the Windy radar embed and the parked BOM radar file route.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from hub import shell
from hub.ids import WEATHER_SNAPSHOT_ID, home_tz
from hub.store import _snapshot_dir, connected, data_of, parse_utc, tile_state

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


def find_weather(snaps) -> dict | None:
    """The hub glimpse card: first registry tile reading the weather snapshot."""
    for a in shell.registry.areas:
        for t in a.tiles:
            if t.snapshot == WEATHER_SNAPSHOT_ID:
                data = data_of(snaps.get(WEATHER_SNAPSHOT_ID))
                return {"tile": t, "st": tile_state(t, snaps),
                        "glyph": weather_glyph(data.get("condition_text")), "data": data}
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


# BOM radar loop (2026-10-06, Option 1 approved by B.): the open_meteo connector stores
# raw PNG layers + up to 6 rain frames under SNAPSHOT_DIR/radar/ and names them in
# data.radar. The page stacks <img> layers and cycles the frames with CSS keyframes (no
# JS); the route below serves ONLY names matching this allowlist, never arbitrary paths.
RADAR_FILE_RE = re.compile(r"^(?:layer_(?:background|topography|locations|range)|frame_\d{12})\.png$")
RADAR_UNDER = ("background", "topography")   # below the rain
RADAR_OVER = ("range", "locations")          # above it, so town names stay readable
RADAR_SLOTS = 6                              # the CSS cycle is built for 6 frame slots


def _radar_dir() -> Path:
    return _snapshot_dir() / "radar"


def _radar_clock(iso: str) -> str | None:
    t = parse_utc(iso) if iso else None
    if t is None:
        return None
    return f"{t.astimezone(home_tz()):%H:%M}"


def weather_radar(snaps) -> dict | None:
    """Template context for the radar panel; None when the snapshot carries no usable radar."""
    snap = snaps.get(WEATHER_SNAPSHOT_ID)
    data = snap.data if snap else None
    radar = data.get("radar") if isinstance(data, dict) else None
    if not isinstance(radar, dict):
        return None
    frames = []
    for f in radar.get("frames") or []:
        name = f.get("file") if isinstance(f, dict) else None
        clock = _radar_clock(f.get("time_iso")) if name else None
        if isinstance(name, str) and RADAR_FILE_RE.match(name) and clock:
            frames.append({"src": f"/weather/radar/{name}", "time": clock})
    if not frames:
        return None
    layers = {n for n in radar.get("layers") or [] if isinstance(n, str) and RADAR_FILE_RE.match(n)}

    def urls(names):
        return [f"/weather/radar/layer_{n}.png" for n in names if f"layer_{n}.png" in layers]

    # Always RADAR_SLOTS slots so one fixed CSS cycle fits: pad by repeating the oldest frame.
    slots = [frames[0]] * (RADAR_SLOTS - len(frames)) + frames[-RADAR_SLOTS:]
    steps = sorted({_frame_minutes(a, b) for a, b in zip(frames, frames[1:])} - {None})
    return {
        "under": urls(RADAR_UNDER), "over": urls(RADAR_OVER), "slots": slots,
        "count": len(frames), "first": frames[0]["time"], "last": frames[-1]["time"],
        "step": steps[0] if len(steps) == 1 else None,
        "stale": radar.get("fetched_ok") is False,
        "station": radar.get("station") or "",
    }


def _frame_minutes(a: dict, b: dict) -> int | None:
    try:
        ha, ma = map(int, a["time"].split(":"))
        hb, mb = map(int, b["time"].split(":"))
    except (KeyError, ValueError):
        return None
    return ((hb * 60 + mb) - (ha * 60 + ma)) % 1440 or None



@router.get("/weather", response_class=HTMLResponse)
def weather_page(request: Request):
    """Detail behind the hub glimpse (2026-09-11). Reads the same snapshot; today plus,
    since the 2026-10-06 upgrade, the next 24 hours and 7 days when the snapshot has them."""
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)
    resp = shell.render_page(request, "weather.html", {
        "w": find_weather(snaps),
        "fc": weather_forecast(snaps),   # the parked BOM panel's weather_radar() context is not built (H-05)
        "windy_src": windy_embed_url(),
    })
    return shell._maybe_set_cookie(resp, view, from_query)


@router.get("/weather/radar/{name}")
def weather_radar_file(name: str):
    """One stored BOM radar PNG (2026-10-06). Allowlisted names only — anything else,
    traversal attempts included, is a 404; so is a name the connector has pruned."""
    from fastapi.responses import FileResponse

    if not RADAR_FILE_RE.match(name):
        raise HTTPException(status_code=404)
    path = _radar_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    # frames are immutable (timestamped names); layers are rewritten in place — revalidate
    cache = "public, max-age=86400, immutable" if name.startswith("frame_") else "no-cache"
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": cache})
