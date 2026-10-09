"""Joey hub — FastAPI skeleton. Every route and the tab bar render from
areas.yaml; no area name appears in this code (WP17 verify greps for that).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTasks

from hub import media_backup, media_db, media_downloads, media_nav
from hub.images import router as images_router
from hub import media_discover as _media_discover, media_write as _media_write
from hub.media_discover import DISCOVER_DETAIL, router as media_discover_router
from hub import media_film, media_item, media_person, media_library, media_plays, media_plays_db
from hub import media_awards_badges
from hub.media_write import router as media_write_router, year_ctx
from hub import media_arr_search, media_follow, media_requests, media_resume, media_watchlist, media_warmup
from hub import media_awards, media_awards_pages
from hub import server as server_area
from hub import server_alerts, server_history, server_updates
from hub.media_watchlist import router as media_watchlist_router
from hub.identity import IDENTITY_HEADER, Identity, resolve_identity
from hub.registry import Registry, load_registry
from hub.shell import _static_version, templates  # ONE Jinja env for every router (H-31)
from hub.store import get_runner, get_runner_history, get_snapshots as _read_snapshots, tile_state

HUB_DIR = Path(__file__).resolve().parent
REPO_ROOT = HUB_DIR.parent

log = logging.getLogger("hub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

registry: Registry | None = None


def get_snapshots(snapshot_dir=None):
    """Every envelope (hub.store), with resume items just marked watched / reset left out of the jellyfin
    `up_next` lists until a newer sweep (media_resume, 2026-10-08) — so every shelf, hero and list drops them."""
    return media_resume.apply_hidden(_read_snapshots(snapshot_dir), "jellyfin")

registry_loaded_at: str | None = None

# media.db backups (2026-10-05): first check ~30 s after startup (the NAS is off
# overnight, so this is what gives one a day), then hourly; maybe_backup skips
# while a backup under 20 h old exists. MEDIA_BACKUP=off disables the task.
BACKUP_FIRST_DELAY_S = 30
BACKUP_EVERY_S = 3600


async def _backup_loop():
    await asyncio.sleep(BACKUP_FIRST_DELAY_S)
    while True:
        try:
            await asyncio.to_thread(media_backup.maybe_backup)
        except Exception as exc:  # never let a backup take the hub down
            log.warning("media backup task error: %s: %s", type(exc).__name__, exc)
        await asyncio.sleep(BACKUP_EVERY_S)


async def _server_alerts_loop():
    """WP-U2: push NEW Server Attention items to Discord (no-op without the webhook).
    WP-U4: the same loop samples the `system` snapshot into media.db (server_history)."""
    await asyncio.sleep(server_alerts.FIRST_DELAY_S)
    while True:
        try:
            await asyncio.to_thread(server_history.sample)
        except Exception as exc:  # never let a history sample take the hub down
            log.warning("server history task error: %s", type(exc).__name__)
        try:
            await asyncio.to_thread(server_alerts.check_once, server_area.live_snapshot_ids(registry))
        except Exception as exc:  # never let an alert check take the hub down
            log.warning("server alerts task error: %s", type(exc).__name__)
        await asyncio.sleep(server_alerts.EVERY_S)


async def _media_warmup_loop():
    """media-speed: warm the film pages behind the Media home shelves ~60 s after startup, then every few
    hours (hub/media_warmup.py). Sequential and paced inside the thread; MEDIA_WARMUP=off disables it."""
    await asyncio.sleep(media_warmup.FIRST_DELAY_S)
    while True:
        try:
            await asyncio.to_thread(media_warmup.run_pass)
        except Exception as exc:  # never let a warm-up take the hub down
            log.warning("media warm-up task error: %s", type(exc).__name__)
        await asyncio.sleep(media_warmup.EVERY_S)


async def _media_follow_loop():
    """Follow (2026-10-07): request NEW films of followed people / series (hub/media_follow.py) ~2 min after
    startup, then every 6 h. Idempotent (the NAS is off overnight); MEDIA_FOLLOW=off disables it."""
    await asyncio.sleep(media_follow.FIRST_DELAY_S)
    while True:
        try:
            await asyncio.to_thread(media_follow.run_once)
        except Exception as exc:  # never let a follow check take the hub down
            log.warning("media follow task error: %s", type(exc).__name__)
        await asyncio.sleep(media_follow.EVERY_S)


async def _media_awards_loop():
    """Awards (2026-10-08): hourly check, a pass when one is due (hub/media_awards.py: every 6 h while a backlog
    exists, then weekly; skipped 22:00-07:00). MEDIA_AWARDS=off disables it; no AWARDS_CONTACT => no calls."""
    await asyncio.sleep(media_awards.FIRST_DELAY_S)
    while True:
        try:
            await asyncio.to_thread(media_awards.tick)
        except Exception as exc:  # never let an awards pass take the hub down
            log.warning("media awards task error: %s", type(exc).__name__)
        await asyncio.sleep(media_awards.TICK_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the registry at startup, failing fast with the aggregated violation list."""
    global registry, registry_loaded_at
    areas_path = os.environ.get("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    registry = load_registry(areas_path)  # ValueError here aborts startup by design
    registry_loaded_at = datetime.now(timezone.utc).isoformat()
    log.info("registry loaded from %s: %d areas", areas_path, len(registry.areas))
    backup_task = None if media_backup.disabled() else asyncio.create_task(_backup_loop())
    plays_task = media_plays.start_recorder()  # F7 play recorder; None when off
    alerts_task = asyncio.create_task(_server_alerts_loop())
    warmup_task = None if media_warmup.disabled() else asyncio.create_task(_media_warmup_loop())
    follow_task = None if media_follow.disabled() else asyncio.create_task(_media_follow_loop())
    awards_task = None if media_awards.disabled() else asyncio.create_task(_media_awards_loop())
    yield
    if awards_task is not None:
        awards_task.cancel()
        with suppress(asyncio.CancelledError):
            await awards_task
    if follow_task is not None:
        follow_task.cancel()
        with suppress(asyncio.CancelledError):
            await follow_task
    if warmup_task is not None:
        warmup_task.cancel()
        with suppress(asyncio.CancelledError):
            await warmup_task
    alerts_task.cancel()
    with suppress(asyncio.CancelledError):
        await alerts_task
    if plays_task is not None:
        plays_task.cancel()
        with suppress(asyncio.CancelledError):
            await plays_task
    if backup_task is not None:
        backup_task.cancel()
        with suppress(asyncio.CancelledError):
            await backup_task


app = FastAPI(title="Joey hub", lifespan=lifespan)


@app.middleware("http")
async def log_identity(request: Request, call_next):
    email = request.headers.get(IDENTITY_HEADER, "-")
    response = await call_next(request)
    log.info('%s %s user=%s -> %d', request.method, request.url.path, email, response.status_code)
    return response


@app.middleware("http")
async def no_store_pages(request: Request, call_next):
    """Back/Forward is navigation only (2026-10-08): an HTML page is never stored, so neither the browser's
    bfcache/HTTP cache nor a proxy can show a page as it was before a Follow / Request / Remove. Static files
    and /img keep their own caching (static URLs are content-versioned)."""
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html") and not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Query params that only carry a one-off flash line after a POST's 303 (2026-10-08). base.html strips them from
# the address bar after render (history.replaceState), so Back / Forward / reload never re-show the flash.
FLASH_PARAMS = ("follow", "requested", "error", "flash", "c", "code", "done", "app", "search", "future")  # search, future: media-ux5

app.include_router(images_router)
app.include_router(media_write_router)
app.include_router(media_discover_router)
app.include_router(media_plays.router)
app.include_router(media_film.router)
app.include_router(media_person.router)
app.include_router(media_watchlist_router)
app.include_router(media_follow.router)
app.include_router(media_awards_pages.router)
app.include_router(media_requests.router)
app.include_router(media_resume.router)
app.include_router(media_arr_search.router)   # media-ux5: Search now
app.include_router(server_updates.router)
app.mount("/static", StaticFiles(directory=str(HUB_DIR / "static")), name="static")


def identity_of(request) -> Identity:
    """Template global `identity(request)`: the signed-in user (name/email/owner), cached per request."""
    state = getattr(request, "state", None)
    cached = getattr(state, "identity", None) if state is not None else None
    if cached is None:
        cached = resolve_identity(request)
        if state is not None:
            state.identity = cached
    return cached


OWNER_VIEWS = ("both", "you", "her")
OWNER_COOKIE = "owner_view"
OWNER_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days, per device (WP19)


def resolve_owner_view(request: Request) -> tuple[str, bool]:
    """Signed in (Access header): the view IS the signed-in owner — query and cookie are
    ignored and no cookie is set (2026-10-06). Not signed in (local dev, tests): query param
    wins (and sets the cookie); else cookie; else 'both'.

    Semantics per Q9 (answered 2026-08-25): you = you+shared, her = her+shared.
    Returns (view, came_from_query).
    """
    who = resolve_identity(request)
    if who.owner:
        return who.owner, False
    q = request.query_params.get(OWNER_COOKIE)
    if q in OWNER_VIEWS:
        return q, True
    c = request.cookies.get(OWNER_COOKIE)
    return (c if c in OWNER_VIEWS else "both"), False


def owner_visible(tile, view: str) -> bool:
    return view == "both" or tile.owner.value == "shared" or tile.owner.value == view


def _maybe_set_cookie(response, view: str, from_query: bool):
    if from_query:
        response.set_cookie(OWNER_COOKIE, view, max_age=OWNER_COOKIE_MAX_AGE, samesite="lax")
    return response


# Hub weather glimpse (2026-09-11 decision — supersedes D18). The glimpse reuses
# the registry tile that reads this snapshot (Calendar's weather tile), so its
# stale_after/owner/states stay single-sourced in areas.yaml. Connector id, not
# an area name (WP17 grep exception, as in registry.py).
WEATHER_SNAPSHOT_ID = "open_meteo"

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
    for a in registry.areas:
        for t in a.tiles:
            if t.snapshot == WEATHER_SNAPSHOT_ID:
                snap = snaps.get(WEATHER_SNAPSHOT_ID)
                data = snap.data if snap else {}
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
    data = snap.data if snap else None
    if not isinstance(data, dict):
        return None
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
                  "word": d.get("condition_text") or "unknown",
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
    from hub.store import DEFAULT_SNAPSHOT_DIR
    return Path(os.environ.get("SNAPSHOT_DIR", DEFAULT_SNAPSHOT_DIR)) / "radar"


def _radar_clock(iso: str) -> str | None:
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    try:
        from zoneinfo import ZoneInfo
        t = t.astimezone(ZoneInfo(HOME_TZ_NAME))
    except Exception:
        t = t.astimezone()
    return f"{t:%H:%M}"


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


# Calendar upcoming list (2026-09-11 decision: next 7 days, day-grouped).
# Rendered on any area page whose tiles read this snapshot — keyed by connector
# id like the weather glimpse, never an area name (WP17 grep exception).
GCAL_SNAPSHOT_ID = "gcal"
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
    return d.strftime("%a %d %b")


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


# Media sections (2026-10-05): apps health + now playing + up next. Keyed by
# connector id like the upcoming list — never an area name (WP17 grep exception).
JELLYFIN_SNAPSHOT_ID = "jellyfin"
MEDIA_STATUS_SNAPSHOT_ID = "media_status"
ARR_SNAPSHOT_ID = "arr"
JELLYSEERR_SNAPSHOT_ID = "jellyseerr"
QBIT_SNAPSHOT_ID = media_downloads.QB_SNAPSHOT_ID
HISTORY_DETAIL = "/media/history"  # the tile reading the jellyfin snapshot as watch history
HISTORY_PLAYS = "/media/server/history"  # F7 play history (Server > History)
DIARY_DETAIL = "/media/diary"      # the tile reading it as the watch diary
YEARS_DETAIL = "/media/years"      # the tile reading it as the year rankings
LIBRARY_STRIP_MAX = 5  # "Just arrived" strip on the area page
HISTORY_STRIP_MAX = 5  # "Recently watched" strip on the area page
TO_RATE_DAYS = 30      # rating inbox window on /media/history
DIARY_PAGE = 50
MILESTONES_MAX = 5


def find_detail_source(snapshot_id, snaps, detail=None) -> dict | None:
    """The page behind a `detail` tile: the first registry tile reading the
    snapshot (the one whose `detail` route matches, when several tiles share a
    snapshot), its area and the area's first LINK tile (the app
    launcher, as find_media resolves it). None when no tile reads the snapshot."""
    for a in registry.areas:
        for t in a.tiles:
            if t.snapshot == snapshot_id and (detail is None or t.detail == detail):
                snap = snaps.get(snapshot_id)
                href = next((x.href for x in a.tiles if x.tier.value == "link"), None)
                return {"tile": t, "st": tile_state(t, snaps),
                        "data": snap.data if snap else {}, "href": href}
    return None


def _parse_ts(value) -> datetime:
    """ISO timestamp -> aware datetime (Jellyfin's 7-digit fractions tolerated)."""
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value).replace("Z", "+00:00"))
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


LEVEL_KEYS = ("item_key", "show_key", "season_key", "episode_key")


class Ratings(dict):
    """{key: score} plus the owner's rating level, so templates can call score_for(row, ratings)."""
    level = "show"


def _ratings(view: str, *row_lists) -> Ratings:
    """ONE get_ratings() per page render, for the view's owner (her view = her own ratings).
    Fetches every key kind a row carries (show / season / episode) so score_for can pick."""
    owner = media_db.owner_of(view)
    out = Ratings(media_db.get_ratings((r.get(k) for rows in row_lists for r in rows or [] for k in LEVEL_KEYS),
                                       owner))
    out.level = media_db.rating_level(owner)
    return out


def score_for(row, ratings, level=None):
    """A row's score: the current level's key when it has one that is rated, else the show's
    (item_key). Movies and rows without level keys read item_key as ever."""
    level = level or getattr(ratings, "level", "show")
    key = row.get(level + "_key") if level in media_db.LEVELS else None
    if key and key in ratings:
        return ratings[key]
    return ratings.get(row.get("item_key")) if row.get("item_key") else None


templates.env.globals["score_for"] = score_for


def view_jelly(jelly: dict, view: str) -> dict:
    """The Jellyfin data as the owner view sees it. In the her view up_next/history are
    Georgina's own (empty when her block is null — never B.'s), `her_missing` says so;
    sessions, latest and library stay server-wide. Other views are returned untouched."""
    if view != "her" or not jelly:
        return jelly
    her = jelly.get("her")
    return {**jelly, "up_next": (her or {}).get("up_next") or [],
            "history": (her or {}).get("history") or {}, "her_missing": her is None}


def _ago_text(value, now: datetime) -> str:
    """'3 days ago' for an ISO timestamp (Jellyfin's 7-digit fractions tolerated)."""
    try:
        seconds = (now - _parse_ts(value)).total_seconds()
    except Exception:
        return ""
    if seconds < 3600:
        return "just now"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    days = int(seconds // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def _count_text(n, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _library_text(library: dict) -> str:
    parts = [_count_text(library[k], s, p)
             for k, s, p in (("movies", "movie", "movies"), ("episodes", "episode", "episodes"))
             if isinstance(library.get(k), int)]
    return " · ".join(parts)


def find_media(tiles, snaps) -> dict | None:
    """Media sections for an area: each present when a visible tile reads that
    snapshot and it holds data (fresh or stale — never fabricated). Now-playing
    rows link to the first LINK tile in the same area (the Jellyfin launcher)."""
    def reading(snapshot_id, detail=None):
        for row in tiles:
            if (row["tile"].snapshot == snapshot_id and (detail is None or row["tile"].detail == detail)
                    and row["st"]["state"] in ("fresh", "stale")):
                return row["st"], snaps[snapshot_id].data
        return None

    play, apps = reading(JELLYFIN_SNAPSHOT_ID), reading(MEDIA_STATUS_SNAPSHOT_ID)
    library = reading(ARR_SNAPSHOT_ID)
    watched = reading(JELLYFIN_SNAPSHOT_ID, HISTORY_DETAIL)  # B.'s own tile, so a her view never sees it
    recent = ((watched[1].get("history") or {}).get("recent") or [])[:HISTORY_STRIP_MAX] if watched else []
    if not (play or apps or library or recent):
        return None
    link = next((r["st"]["href"] for r in tiles if r["st"]["state"] == "link"), None)
    return {
        "apps": {"st": apps[0], "items": apps[1].get("apps", [])} if apps else None,
        "play": {"st": play[0], "now_playing": play[1].get("now_playing", []),
                 "up_next": play[1].get("up_next", []), "href": link} if play else None,
        "library": {"st": library[0], "items": library[1].get("arrived", [])[:LIBRARY_STRIP_MAX]}
                   if library else None,
        "history": {"st": watched[0], "items": recent} if recent else None,
    }


def _media_rows(media) -> list:
    """Every row list on the area's media sections, for the page's one ratings lookup."""
    if not media:
        return []
    play, library, history = media["play"] or {}, media["library"] or {}, media["history"] or {}
    return [play.get("now_playing"), play.get("up_next"), library.get("items"), history.get("items")]


def build_status(snaps) -> dict:
    """Cockpit status strip: feed health computed from registry vs snapshots."""
    wanted: dict[str, str] = {}   # connector id -> first area name using it
    for a in registry.areas:
        for t in a.tiles:
            if t.snapshot and t.snapshot not in wanted:
                wanted[t.snapshot] = a.name
    stale = sorted({
        wanted[cid] for cid, s in snaps.items()
        if cid in wanted and any(
            t.snapshot == cid and t.stale_after_minutes and s.age_minutes > t.stale_after_minutes
            for a in registry.areas for t in a.tiles)
    })
    return {
        "feeds_total": len(wanted),
        "feeds_ok": sum(1 for cid in wanted if cid in snaps),
        "stale": stale,
    }


SHELF_MAX = 15         # items per poster shelf
TO_RATE_SHELF_MAX = 10
LIBRARY_DETAIL = "/media/library"
PLAYING_DETAIL = "/media/playing"
REQUESTS_DETAIL = "/media/requests"


def item_href(jf_id=None, key=None) -> str | None:
    """Joey item page (F9) for a Jellyfin id, or for a `jf:<id>` rating key; None otherwise."""
    if not jf_id and str(key or "").startswith("jf:"):
        jf_id = key[3:]
    return f"/media/item/{jf_id}" if jf_id and media_item.ITEM_RE.match(str(jf_id)) else None


def row_href(jf_id=None, key=None, kind=None) -> str | None:
    """Whole-row link (B., 2026-10-06): Joey item page, else the tmdb title page, else None."""
    url = item_href(jf_id, key)
    k = str(key or "")
    if not url and kind in ("movie", "tv") and k.startswith("tmdb:") and k[5:].isdigit():
        url = f"/media/title/{kind}/{k[5:]}"
    return url


def _deep_link(link, jf_id, server_id) -> str | None:
    """Jellyfin item page for a row; None rather than a fabricated link."""
    if not link or not jf_id:
        return None
    url = f"{link.rstrip('/')}/web/#/details?id={jf_id}"
    return url + (f"&serverId={server_id}" if server_id else "")


def waiting_counts(recent, ratings, details) -> dict:
    """What waits on the owner: titles to rate (full, uncapped inbox) and years to place.
    `details` = the detail paths of the tiles visible in this owner view; a count whose
    tile is hidden is 0. Shared by the area page and the hub card."""
    to_rate = len(_to_rate(recent, ratings)) if HISTORY_DETAIL in details else 0
    to_place = (sum(y["unranked_count"] for y in media_db.years_overview())
                if YEARS_DETAIL in details else 0)
    return {"to_rate": to_rate, "to_place": to_place}


def area_waiting(area, snaps, view: str) -> dict:
    """waiting_counts for an area straight from snapshots + owner view (hub card, Media frame)."""
    jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
    recent = (view_jelly(jelly.data if jelly else {}, view).get("history") or {}).get("recent") or []
    counts = waiting_counts(recent, _ratings(view, recent),
                            {t.detail for t in area.tiles if t.detail and owner_visible(t, view)})
    if view == "her":
        counts["to_place"] = 0  # rankings are B.'s only
    return counts


def to_rate_tab_counts(snaps, view: str) -> dict:
    """The Movies / TV Shows "To rate" tab counts (media-ux4): the viewer's own inbox split by kind."""
    jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
    recent = (view_jelly(jelly.data if jelly else {}, view).get("history") or {}).get("recent") or []
    rows = _to_rate(recent, _ratings(view, recent)) if recent else []
    return {"to_rate_movie": sum(1 for r in rows if r["kind"] == "movie"),
            "to_rate_tv": sum(1 for r in rows if r["kind"] == "tv")}


def media_frame(request: Request) -> dict:
    """Template global `media_nav(request)`: the Media bar/tabs context (cached per request)."""
    cached = getattr(request.state, "media_nav", None)
    if cached is None:
        view, _ = resolve_owner_view(request)
        area = media_nav.shelves_area(registry)
        snaps = getattr(request.state, "snaps", None)  # media-speed: a route's own read, when it shared one
        snaps = get_snapshots() if snaps is None else snaps
        waiting = area_waiting(area, snaps, view) if area else {}
        try:
            jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
            waiting = {**waiting, **media_watchlist.tab_counts(media_db.owner_of(view), jelly.data if jelly else None)}
        except Exception as exc:  # the Watchlist count is a nicety: never break the frame
            log.warning("watchlist count skipped: %s", type(exc).__name__)
        try:
            waiting = {**waiting, **to_rate_tab_counts(snaps, view)}
        except Exception as exc:  # the To rate tab count is a nicety too (media-ux4)
            log.warning("to rate count skipped: %s", type(exc).__name__)
        cached = request.state.media_nav = media_nav.nav_context(request, registry, waiting, view)
    return cached


templates.env.globals["media_nav"] = media_frame
templates.env.globals["item_href"] = item_href
templates.env.globals["row_href"] = row_href
templates.env.globals["identity"] = identity_of
templates.env.globals["flash_params"] = FLASH_PARAMS
templates.env.globals["resume_flash"] = lambda request: media_resume.flash_text(request.query_params) if request else (None, None)


def resume_acts(row: dict, owner: str) -> dict | None:
    """Move on (2026-10-08): what a Continue watching card offers — Mark watched always, Reset progress only on a
    resume row (not a next-up suggestion). None without a Jellyfin id."""
    jf = str((row or {}).get("jf_id") or "")
    if not media_item.ITEM_RE.match(jf):
        return None
    resume = media_resume.in_progress(row)
    series = None if resume else media_resume.series_of(row)   # media-ux2: a Next Up suggestion can be hidden
    return {"jf_id": jf, "owner": owner, "reset": resume, "hide": bool(series), "series": series}


templates.env.globals["resume_acts"] = resume_acts

# Interim (T3, 2026-10-09): the media routers still build their own Jinja envs; give them EVERY shell global
# (static_v, score_for, resume_acts included) so their pages carry the asset version. A later media WP switches
# those modules to hub.shell.templates and this loop goes.
for _t in (_media_write.templates, _media_discover.templates, media_watchlist.templates):
    _t.env.globals.update(templates.env.globals)


def media_hero(jelly: dict, link: str | None, allow_newest: bool = True) -> dict | None:
    """The one item the Media hero shows: playing now, else first resume item, else the
    newest arrival. Pure; shared by the area page (build_shelves) and the hub card."""
    server_id = jelly.get("server_id")

    def hero(row, kind_word, sub, **extra):
        return {"kind_word": kind_word, "title": row.get("title"), "poster": row.get("poster"),
                "backdrop": row.get("backdrop"), "sub": sub,
                "href": _deep_link(link, row.get("jf_id"), server_id),
                "progress_pct": None, "user": None, "play_method": None, **extra}

    playing = jelly.get("now_playing") or []
    if playing:
        p = playing[0]
        return hero(p, "Playing now", f"{p.get('user')} · {p.get('play_method')} · {p.get('progress_pct')}%",
                    user=p.get("user"), play_method=p.get("play_method"), progress_pct=p.get("progress_pct"))
    up_next = jelly.get("up_next") or []
    if up_next:
        return hero(up_next[0], "Jump back in", up_next[0].get("remaining_text"))
    latest = sorted(jelly.get("latest") or [], key=lambda r: str(r.get("added_at") or ""), reverse=True)
    if allow_newest and latest:
        return hero(latest[0], "Newest arrival", f"Added {_ago_text(latest[0].get('added_at'), datetime.now(timezone.utc))}")
    return None


def build_shelves(area, tiles, snaps, view: str) -> dict:
    """Hero + poster shelves for a `layout: shelves` area. Pure over its inputs (plus the
    ratings DB). A shelf renders only when the registry tile it stands for is visible in
    the owner view; snapshots/DB missing just leave quiet words (years/torate: omitted)."""
    by_detail = {r["tile"].detail: r for r in tiles if r["tile"].detail}
    link = next((r["st"]["href"] for r in tiles if r["st"]["state"] == "link"), None)

    def data_of(snapshot_id):
        snap = snaps.get(snapshot_id)
        return snap.data if snap else {}

    jelly = view_jelly(data_of(JELLYFIN_SNAPSHOT_ID), view)
    her_unset = bool(jelly.get("her_missing"))  # her view, no Georgina user wired yet
    jelly_row = next((r for r in tiles if r["tile"].snapshot == JELLYFIN_SNAPSHOT_ID), None)
    now = datetime.now(timezone.utc)

    up_next = (jelly.get("up_next") or [])
    hero = media_hero(jelly, link, allow_newest=False)
    if hero and hero["href"] is None:
        hero["href"] = link  # no deep link for the row: fall back to the Jellyfin launcher
    if hero and hero["kind_word"] == "Jump back in":
        hero["kind_word"] = "Up next"  # the area page keeps its original word
    kind_word = hero["kind_word"] if hero else "Nothing playing"

    server_id = jelly.get("server_id")

    def item(r, sub, href, **extra):
        return {"title": r.get("title"), "sub": sub, "poster": r.get("poster"),
                "href": href, **{k: r.get(k) for k in LEVEL_KEYS}, **extra}

    def jf_item(r, sub, fallback, **extra):
        """Row that opens its Joey item page (F9) when it carries a jf_id, else a Joey page."""
        return item(r, sub, item_href(r.get("jf_id")) or fallback, **extra)

    shelves: list[dict] = []

    def add(sid, title, detail, items, quiet, omit_empty=False):
        if detail not in by_detail or (omit_empty and not items):
            return
        shelves.append({"id": sid, "title": title, "see_all_href": detail,
                        "items": items, "quiet_text": quiet})

    recent = ((jelly.get("history") or {}).get("recent") or [])
    arrived = list(data_of(ARR_SNAPSHOT_ID).get("arrived") or [])
    latest = sorted(jelly.get("latest") or [], key=lambda r: str(r.get("added_at") or ""), reverse=True)
    added, seen = [], set()
    for r, sub, from_jf in ([(r, _ago_text(r.get("added_at"), now), True) for r in latest]
                            + [(r, r.get("when", ""), False) for r in arrived]):
        key = r.get("item_key") or r.get("title")
        if key in seen:
            continue
        seen.add(key)
        added.append(jf_item(r, sub, LIBRARY_DETAIL) if from_jf else item(r, sub, LIBRARY_DETAIL))
    added = added[:SHELF_MAX]
    arr = data_of(ARR_SNAPSHOT_ID)
    # media-ux2 (2026-10-08, B.): "This week" and "Recently watched" left Media home (Server → Library keeps This week,
    # Diary > To rate keeps Recently watched; the hub page's own Recently watched band is separate).
    downloading = [item(r, r["caption"], LIBRARY_DETAIL) for r in
                   media_downloads.merge_downloading(arr.get("downloading"), data_of(QBIT_SNAPSHOT_ID))][:SHELF_MAX]

    ratings = _ratings(view, up_next, added, recent, downloading)  # ONE query for every shelf

    unset_text = "Set JELLYFIN_USER_HER in deploy/.env"
    add("continue", "Continue watching", PLAYING_DETAIL,
        [jf_item(n, n.get("remaining_text"), PLAYING_DETAIL, acts=resume_acts(n, media_db.owner_of(view)))
         for n in up_next[:SHELF_MAX]],
        unset_text if her_unset else "Nothing up next")
    add("added", "Recently added", LIBRARY_DETAIL, added, "Nothing added recently")
    add("downloading", "Downloading", LIBRARY_DETAIL, downloading, "", omit_empty=True)
    most_shows, most_films = media_plays_db.most_played_30({"you": "you", "her": "her"}.get(view))
    most = ([item({"title": e["title"], "poster": e["poster"], "item_key": e["key"]},
                  f"{e['episodes']} episode{'' if e['episodes'] == 1 else 's'} · {e['hours']} h", item_href(e.get("jf_id"), e["key"]) or HISTORY_PLAYS)
             for e in most_shows]
            + [item({"title": e["title"], "poster": e["poster"], "item_key": e["key"]},
                    f"{e['plays']} play{'' if e['plays'] == 1 else 's'} · {e['hours']} h", item_href(e.get("jf_id"), e["key"]) or HISTORY_PLAYS)
               for e in most_films])
    try:  # Follow (2026-10-07): only once something is followed; behind the Discover tile like /media/following
        followed = media_follow.home_items() if DISCOVER_DETAIL in by_detail else None
    except Exception as exc:  # the home page never fails on the follow shelf
        log.warning("follow shelf skipped: %s", type(exc).__name__)
        followed = None
    if followed is not None:
        shelves.append({"id": "following", "title": "New from people you follow", "see_all_href": media_follow.FOLLOWING,
                        "items": [item(r, r["sub"], r["href"]) for r in followed], "quiet_text": "Nothing new yet"})
    if most:  # F7: not behind a registry tile, so it skips add()'s detail gate
        shelves.append({"id": "mostplayed", "title": "Most played · 30 days", "see_all_href": HISTORY_PLAYS,
                        "items": most, "quiet_text": ""})
    for sh in shelves:
        for it in sh["items"]:
            it["score"] = score_for(it, ratings)
            for k in LEVEL_KEYS:
                it.pop(k, None)

    return {
        "hero": hero, "kind_word": kind_word, "shelves": shelves,
        "waiting": waiting_counts(recent, ratings, set(by_detail)),
        "open_href": link,
        "freshness": jelly_row["st"] if jelly_row else None,
    }


# Hub greeting (Apex shell, 2026-10-06): wall-clock at home, not the container's zone.
HOME_TZ_NAME = "Australia/Melbourne"


def _now_home() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(HOME_TZ_NAME))
    except Exception:  # no tz database in the image: fall back to the container's local time
        return datetime.now().astimezone()


def hub_greeting(now: datetime, name: str | None = None) -> str:
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    hello = f"Good {part}, {name}." if name else f"Good {part}."
    return f"{hello} Here's what's happening at home today, {now:%A} {now.day} {now:%B}."


def per_day_counts(groups, today: date, days: int = UPCOMING_DAYS) -> list[int]:
    """Events per day for today + the next days-1, from build_upcoming's groups (Calendar KPI bars)."""
    by_day = {g["day"]: len(g["events"]) for g in groups}
    return [by_day.get(today + timedelta(days=i), 0) for i in range(days)]


def hub_upcoming(snaps, view: str) -> dict | None:
    """Hub "Next 7 days" card: the first visible tile reading the gcal snapshot, its area's
    page for "View all", and find_upcoming's groups (None data = not connected)."""
    for a in registry.areas:
        rows = [{"tile": t, "st": tile_state(t, snaps)} for t in a.tiles if owner_visible(t, view)]
        row = next((r for r in rows if r["tile"].snapshot == GCAL_SNAPSHOT_ID), None)
        if row:
            up = find_upcoming(rows, snaps, view)
            today = datetime.now().astimezone().date()  # the clock find_upcoming groups on
            return {"href": f"/a/{a.id}", "st": row["st"], "days": UPCOMING_DAYS,
                    "groups": up["groups"] if up else [],
                    "per_day": per_day_counts(up["groups"], today) if up else None}
    return None


def _profile_rows(jelly: dict, view: str, pick) -> list[tuple[dict, str]]:
    """(row, owner) pairs from B.'s and Georgina's Jellyfin profiles as the owner view sees
    them: you = B.'s, her = hers, both = B.'s then hers. `pick(profile_dict)` -> rows."""
    mine = [(r, "you") for r in pick(jelly)]
    hers = [(r, "her") for r in pick(jelly.get("her") or {})]
    return {"you": mine, "her": hers}.get(view, mine + hers)


def _split_title(row) -> tuple[str, str]:
    """'Show · S02E05 · Name' -> ('Show', 'S02E05 · Name'); a film keeps its title + 'Film'."""
    head, _, rest = str(row.get("title") or "").partition(" · ")
    return head, rest or ("Film" if row.get("kind") == "movie" else "")


def hub_shelf(area, snaps, view: str, link) -> dict | None:
    """Hub "Recently watched" band for a `layout: shelves` area (its Continue watching band left the hub in media-ux2,
    2026-10-08; Media home keeps it). Present when that area's jellyfin tile is visible; rows only from the snapshot."""
    tiles = [t for t in area.tiles if owner_visible(t, view)]
    jtile = next((t for t in tiles if t.snapshot == JELLYFIN_SNAPSHOT_ID), None)
    if jtile is None:
        return None
    st = tile_state(jtile, snaps)
    snap = snaps.get(JELLYFIN_SNAPSHOT_ID)
    jelly = snap.data if snap and st["state"] != "off" else {}
    server_id = jelly.get("server_id")

    def item(row, owner, when, fallback, acts=None):
        title, sub = _split_title(row)
        url = item_href(row.get("jf_id"))
        return {"title": title, "sub": " · ".join(x for x in (owner.title(), sub) if x),  # owner first: never ellipsised
                "when": when, "poster": row.get("poster"), "href": url or fallback,
                "external": False, "pct": row.get("progress_pct"), "acts": acts}

    watched = None
    if any(t.detail == DIARY_DETAIL for t in tiles):
        rows = _profile_rows(jelly, view, lambda p: (p.get("history") or {}).get("recent") or [])
        if view == "both":
            def when(pair):
                try:
                    return _parse_ts(pair[0].get("watched_at")).timestamp()
                except Exception:
                    return 0.0
            rows = sorted(rows, key=when, reverse=True)
        watched = [item(r, o, r.get("when"), DIARY_DETAIL) for r, o in rows][:SHELF_MAX]
    return {"href": f"/a/{area.id}", "st": st, "watched": watched}


def server_card_state(st: dict, snaps) -> dict:
    """The Server hub card (WP-U2): hub/server.py's words over the summary tile's state.
    `warn` reuses the stale badge (amber) with the words "Needs attention"."""
    card = server_area.hub_card(snaps, server_updates.get_ignores(), media_backup.current_status(),
                                get_runner(), get_runner_history(),
                                live=server_area.live_snapshot_ids(registry))  # WP-U3
    out = {**st, "value": card["summary"], "secondary": card["secondary"]}
    if card["state"] == "warn":
        stale = st.get("age_text") if st["state"] == "stale" else None
        out.update(state="stale", age_text="Needs attention" + (f" · {stale}" if stale else ""))
    return out


@app.get("/", response_class=HTMLResponse)
def hub_page(request: Request):
    view, from_query = resolve_owner_view(request)
    snaps = get_snapshots()
    cards, shelf = [], None
    upcoming = hub_upcoming(snaps, view)
    for a in registry.visible_areas:
        summary = next(t for t in a.tiles if t.id == a.summary_tile)
        if not owner_visible(summary, view):
            continue  # hub summary cards respect the filter (Q24 assumption)
        card = {"area": a, "tile": summary, "st": tile_state(summary, snaps), "hero": None,
                "per_day": None}
        if summary.snapshot == GCAL_SNAPSHOT_ID and upcoming:  # keyed by connector id, never area name
            card["per_day"] = upcoming["per_day"]
        if a.layout == server_area.SERVER_LAYOUT and card["st"]["state"] != "off":
            try:
                card["st"] = server_card_state(card["st"], snaps)  # WP-U2: the card's own words
            except Exception as exc:  # a malformed envelope never 500s the hub: the plain tile state stays (H-63)
                log.warning("server hub card skipped: %s", type(exc).__name__)
        if a.layout == "shelves":  # hero content keyed by layout, never by area name
            link = next((st["href"] for t in a.tiles if owner_visible(t, view)
                         for st in [tile_state(t, snaps)] if st["state"] == "link"), None)
            jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
            jdata = view_jelly(jelly.data if jelly else {}, view)
            card["hero"] = media_hero(jdata, link)
            qb = snaps.get(QBIT_SNAPSHOT_ID)
            card["downloading"] = (qb.data.get("summary") if qb and qb.data.get("active") else None)
            card["waiting"] = area_waiting(a, snaps, view)
            if shelf is None:
                shelf = hub_shelf(a, snaps, view, link)
        cards.append(card)
    cards.sort(key=lambda c: c["area"].hub_rank)  # stable; the area order itself is untouched
    resp = templates.TemplateResponse(request, "hub.html", {
        "areas": registry.visible_areas, "active_id": None, "cards": cards, "owner_view": view,
        "status": build_status(snaps), "weather": find_weather(snaps),
        "upcoming": upcoming, "shelf": shelf,
        "backup_warn": media_backup.current_status()["warning"],
        "greeting": hub_greeting(_now_home(), identity_of(request).owner and identity_of(request).name),
    })
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/weather", response_class=HTMLResponse)
def weather_page(request: Request):
    """Detail behind the hub glimpse (2026-09-11). Reads the same snapshot; today plus,
    since the 2026-10-06 upgrade, the next 24 hours and 7 days when the snapshot has them."""
    view, from_query = resolve_owner_view(request)
    snaps = get_snapshots()
    resp = templates.TemplateResponse(request, "weather.html", {
        "areas": registry.visible_areas, "active_id": None, "owner_view": view,
        "status": build_status(snaps), "w": find_weather(snaps),
        "fc": weather_forecast(snaps), "radar": weather_radar(snaps),   # radar: parked BOM panel context
        "windy_src": windy_embed_url(),
    })
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/weather/radar/{name}")
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


def _detail_page(request: Request, template: str, snapshot_id: str, build=None, detail=None,
                 always_build=False):
    """Detail page behind a `detail` tile (2026-10-05). Keyed by connector id —
    404 when no registry tile reads that snapshot; 'Not connected' when it has no data
    (`always_build` still runs `build` then — the diary has data of its own)."""
    view, from_query = resolve_owner_view(request)
    snaps = get_snapshots()
    src = find_detail_source(snapshot_id, snaps, detail)
    if src is None:
        return templates.TemplateResponse(request, "404.html", {
            "areas": registry.visible_areas, "active_id": None, "owner_view": view,
            "missing_text": "No page here",
        }, status_code=404)
    if snapshot_id == JELLYFIN_SNAPSHOT_ID:
        src = {**src, "data": view_jelly(src["data"], view)}  # her view reads Georgina's up next/history
    extra = build(src["data"], view) if build and (always_build or src["st"]["state"] != "off") else {}
    resp = templates.TemplateResponse(request, template, {
        "areas": registry.visible_areas, "active_id": None, "owner_view": view,
        "status": build_status(snaps), "src": src, "ratings": {}, **extra,
    })
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/media/apps", response_class=HTMLResponse)
def media_apps_page(request: Request):
    return _detail_page(request, "media_apps.html", MEDIA_STATUS_SNAPSHOT_ID, always_build=True,
                        build=lambda data, view: {"backup": media_backup.current_status()})


@app.get("/media/playing", response_class=HTMLResponse)
def media_playing_page(request: Request):
    def build(data, view):
        now = datetime.now(timezone.utc)
        return {
            "latest": [{**i, "added_text": _ago_text(i.get("added_at"), now)}
                       for i in data.get("latest", [])],
            "library_text": _library_text(data.get("library") or {}),
            "ratings": _ratings(view, data.get("now_playing"), data.get("up_next"), data.get("latest")),
        }
    return _detail_page(request, "media_playing.html", JELLYFIN_SNAPSHOT_ID, build)


def _qb_data() -> dict:
    snap = get_snapshots().get(QBIT_SNAPSHOT_ID)
    return snap.data if snap else {}


def _arr_linker(view):
    """Rows -> rows with `href`: same resolver the Movies/TV pages use, per kind, against the
    view's own Jellyfin lists (media_library.link_arrivals). Rows without an item_key stay None."""
    jelly = get_snapshots().get(JELLYFIN_SNAPSHOT_ID)
    jdata = jelly.data if jelly else {}
    lists = {k: _library_lists(jdata, view, k)[0] for k in ("movie", "tv")}

    def link(rows, need_key=False):
        return [{**r, "href": None} if need_key and not r.get("item_key") else
                media_library.link_arrivals([r], lists[k], k, lambda jf: item_href(jf))[0]
                for r in rows or [] for k in ("movie" if r.get("kind") == "movie" else "tv",)]
    return link


@app.get("/media/downloads", response_class=HTMLResponse)
def media_downloads_page(request: Request):
    def build(data, view):
        # Whole row is the link (2026-10-06) when the torrent is an arr download whose title resolves.
        arr = get_snapshots().get(ARR_SNAPSHOT_ID)
        by_hash = {str(r.get("download_id") or "").lower(): r
                   for r in media_downloads.collapse_packs((arr.data if arr else {}).get("downloading"))
                   if r.get("download_id")}
        link = _arr_linker(view)
        data = {**data, "active": [{**t, "href": (link([by_hash[h]], need_key=True)[0]["href"]
                                                  if (h := str(t.get("hash") or "").lower()) in by_hash else None)}
                                   for t in data.get("active") or []]}
        groups = [{"label": label, "rows": [r for r in data.get("active") or [] if r.get("kind") == kind]}
                  for kind, label in (("movie", "Movies"), ("tv", "TV"))]
        groups.append({"label": "Other", "rows": [r for r in data.get("active") or []
                                                  if r.get("kind") not in ("movie", "tv")]})
        totals = data.get("totals") or {}
        return {"groups": [g for g in groups if g["rows"]],
                "totals_text": f"↓ {totals.get('dl_text', '0 B/s')} · ↑ {totals.get('up_text', '0 B/s')}"
                               f" · {data.get('seeding', 0)} seeding"}
    return _detail_page(request, "media_downloads.html", QBIT_SNAPSHOT_ID, build)


@app.get("/media/library", response_class=HTMLResponse)
def media_library_page(request: Request):
    def build(data, view):
        today = datetime.now().astimezone().date()
        groups: list[dict] = []
        for row in sorted(data.get("this_week", []), key=lambda r: (r["date"], r["title"])):
            day = date.fromisoformat(row["date"])
            if not groups or groups[-1]["day"] != day:
                groups.append({"day": day, "label": _day_label(day, today), "rows": []})
            groups[-1]["rows"].append(row)
        merged = media_downloads.merge_downloading(data.get("downloading"), _qb_data())
        # Whole row is the link (B., 2026-10-06): Joey item page, title page or nothing — same
        # resolver the Movies/TV pages use, per kind, against the view's own Jellyfin lists.
        link = _arr_linker(view)

        for g in groups:
            g["rows"] = link(g["rows"])
        return {
            "arrived": link(data.get("arrived")),
            "updated": link(data.get("updated")),
            "week": groups,
            "downloading": link(merged, need_key=True),  # qBittorrent-only rows have no key: plain
            "dl_badges": media_downloads.badges_by_item_key(merged),
            "app_notes": [f"{app.title()} not answering: {reason}"
                          for app, reason in sorted((data.get("app_errors") or {}).items())],
            "ratings": _ratings(view, *(data.get(k) for k in ("arrived", "updated", "this_week")), merged),
        }
    return _detail_page(request, "media_library.html", ARR_SNAPSHOT_ID, build)


@app.get("/media/requests", response_class=HTMLResponse)
def media_requests_page(request: Request):
    def build(data, view):
        # Remove (2026-10-08): a removed row leaves at once (media_hidden), not at the next hourly sweep.
        snap = get_snapshots().get(JELLYSEERR_SNAPSHOT_ID)
        rows = media_requests.visible_rows(data, snap.updated_at if snap else None)
        c = media_requests.visible_counts(data, rows)
        good, warn = media_requests.flash_text(request.query_params)
        return {"counts_text": " · ".join(f"{c.get(k, 0)} {k}"
                                          for k in ("pending", "approved", "available", "declined")),
                "rows": rows, "flash": good, "flash_warn": warn,
                "ratings": _ratings(view, rows)}
    return _detail_page(request, "media_requests.html", JELLYSEERR_SNAPSHOT_ID, build)


def _to_rate_title(r: dict, kind: str, level: str) -> str:
    """Inbox title for a TV row at its rating level; a row missing the numbers falls back."""
    if level == "season" and r.get("show_title") and r.get("season") is not None:
        return f"{r['show_title']} · Season {r['season']}"
    if level == "episode":
        return r["title"]
    return media_db.base_title(r["title"], kind)


def _to_rate(recent, ratings) -> list[dict]:
    """The rating inbox: unrated titles watched in the last TO_RATE_DAYS, one per rating key.
    TV rows follow the owner's level (ratings.level): one entry per show / season / episode
    (a row without that level's key falls back to its show); movies are always one title."""
    level = getattr(ratings, "level", "show")
    cutoff = datetime.now(timezone.utc) - timedelta(days=TO_RATE_DAYS)
    seen, rows = set(), []
    for r in recent:
        kind = media_db.norm_kind(r.get("kind"))
        row_level = level if kind == "tv" and r.get(level + "_key") else "show"
        key = r.get(row_level + "_key") if row_level != "show" else r.get("item_key")
        try:
            fresh = _parse_ts(r["watched_at"]) >= cutoff
        except Exception:
            continue
        if not key or key in ratings or key in seen or not fresh:
            continue
        seen.add(key)
        rows.append({"item_key": key, "kind": kind, "year": None, "level": row_level,
                     "title": _to_rate_title(r, kind, row_level),
                     "poster": r.get("poster"), "when": r.get("when", ""), "jf_id": r.get("jf_id")})
    return rows


@app.get("/media/history", response_class=HTMLResponse)
def media_history_page(request: Request):
    def build(data, view):
        history = data.get("history") or {}
        shows = history.get("most_played_shows", [])
        top = max((s["episodes"] for s in shows), default=0)
        recent = history.get("recent", [])
        ratings = _ratings(view, recent, shows, history.get("most_played_movies"))
        return {
            "history": history,
            "ratings": ratings,
            "to_rate": _to_rate(recent, ratings),
            "rating_levels": media_db.LEVELS,
            "rating_level": ratings.level,
            "shows": [{**s, "pct": round(s["episodes"] / top * 100)} for s in shows],
            "numbers": " · ".join([
                f"{history.get('week_count', 0)} this week",
                f"{history.get('month_count', 0)} this month",
                f"{history.get('hours_month', 0)} h this month",
                f"{history.get('hours_total', 0)} h all time"]),
        }
    return _detail_page(request, "media_history.html", JELLYFIN_SNAPSHOT_ID, build, detail=HISTORY_DETAIL)


def _group_on_this_day(items) -> list[dict]:
    """Same folding as the diary: several episodes of one show a year ago are one line."""
    lines: dict = {}
    for d in items or []:
        line = lines.setdefault((d.get("item_key"), d.get("years_ago"), d.get("kind")),
                                {**d, "title": media_db.base_title(d["title"], "tv" if d.get("kind") == "episode" else d.get("kind")),
                                 "count": 0})
        line["count"] += 1
    return [{**l, "sub": f"{l['count']} episodes" if l["count"] > 1 else ""} for l in lines.values()]


@app.get("/media/diary", response_class=HTMLResponse)
def media_diary_page(request: Request):
    """Watch diary (2026-10-05): sync Jellyfin's recent history in (a silent no-op
    without a snapshot), then list month-grouped, newest first."""
    kind = request.query_params.get("kind")
    kind = kind if kind in ("movie", "tv") else None
    try:
        offset = max(0, int(request.query_params.get("offset", "0")))
    except ValueError:
        offset = 0

    def build(data, view):
        history = data.get("history") or {}
        owner = media_db.owner_of(view)
        media_db.sync_diary_from_history(history.get("recent"), owner)
        rows = media_db.list_diary(DIARY_PAGE + 1, offset, kind, owner)
        more = len(rows) > DIARY_PAGE
        rows = rows[:DIARY_PAGE]
        stats = media_db.diary_stats(owner=owner)
        months: list[dict] = []
        lines = media_db.group_diary(rows)
        for row in lines:
            label = date.fromisoformat(row["watched_on"]).strftime("%B %Y")
            if not months or months[-1]["label"] != label:
                months.append({"label": label, "rows": []})
            months[-1]["rows"].append(row)
        on_this_day = _group_on_this_day(history.get("on_this_day", []))
        streak = stats["streak_days"]
        return {
            "stats_text": " · ".join([
                f"{stats['this_week']} this week", f"{stats['this_month']} this month",
                f"{stats['total']} all time",
                f"{stats['year_films']} film{'' if stats['year_films'] == 1 else 's'} · "
                f"{stats['year_episodes']} episode{'' if stats['year_episodes'] == 1 else 's'} this year",
                f"{streak}-day streak" if streak else "no current streak"]),
            "milestones": stats["milestones"][:MILESTONES_MAX],
            "months": months, "kind": kind or "", "today": date.today().isoformat(),
            "on_this_day": on_this_day,
            "older": (f"/media/diary?offset={offset + DIARY_PAGE}" + (f"&kind={kind}" if kind else ""))
                     if more else None,
            "ratings": _ratings(view, lines, on_this_day),
        }
    return _detail_page(request, "media_diary.html", JELLYFIN_SNAPSHOT_ID, build,
                        detail=DIARY_DETAIL, always_build=True)


@app.get("/media/years", response_class=HTMLResponse)
def media_years_page(request: Request):
    """Year rankings (2026-10-05): one tile per rating year. Pure media.db — no snapshot data needed."""
    def build(data, view):
        kind = _kind_of(request)
        return {"years": [] if view == "her" else media_db.years_overview(kind), "kind": kind}
    return _detail_page(request, "media_years.html", JELLYFIN_SNAPSHOT_ID, build,
                        detail=YEARS_DETAIL, always_build=True)


def _kind_of(request: Request) -> str | None:
    kind = request.query_params.get("kind")
    return kind if kind in ("movie", "tv") else None


def _lib_href():
    """href_of for media_library rows (F9): the Joey item page for a Jellyfin id, else the title page for a tmdb key."""
    def href_of(row, kind):
        url = item_href(row.get("jf_id"))
        if url:
            return url, False
        key = str(row.get("item_key") or "")
        if key.startswith("tmdb:") and key[5:].isdigit():
            return f"/media/title/{kind}/{key[5:]}", False
        return None, False
    return href_of


def _library_lists(data: dict, view: str, kind: str):
    """(items | None, marks): her view reads her own list; without it the shared list has no marks."""
    field = "movies" if kind == "movie" else "shows"
    if view == "her":
        mine = (data.get("her") or {}).get(field)
        if mine is not None:
            return mine, True
        return data.get(field), False
    return data.get(field), True


def _library_rows(data: dict, view: str, kind: str):
    """(items | None, marks, rows | None) for the view's owner."""
    now = datetime.now(timezone.utc)
    items, marks = _library_lists(data, view, kind)
    if items is None:
        return None, marks, None
    maker = media_library.film_rows if kind == "movie" else media_library.show_rows
    return items, marks, maker(items, _ratings(view, items), lambda v: _ago_text(v, now),
                               _lib_href(), marks)


LIBVIEW_COOKIE = "media_libview"     # media-ux4: Grid / List on /media/movies + /media/tv, remembered per device
LIBVIEWS = ("grid", "list")
LIBVIEW_MAX_AGE = 365 * 24 * 3600


def library_view(request: Request) -> tuple[str, bool]:
    """(grid | list, came_from_query): `?view=` wins (and is remembered in a cookie), else the cookie, else grid."""
    q = request.query_params.get("view")
    if q in LIBVIEWS:
        return q, True
    c = request.cookies.get(LIBVIEW_COOKIE)
    return (c if c in LIBVIEWS else "grid"), False


def library_view_links(request: Request) -> dict:
    """{grid: href, list: href} — this page with the same search / sort / grouping and the other layout."""
    keep = [(k, v) for k, v in request.query_params.multi_items() if k != "view"]
    return {v: request.url.path + "?" + urlencode(keep + [("view", v)]) for v in LIBVIEWS}


def _library_page(request: Request, kind: str):
    template = "media_movies.html" if kind == "movie" else "media_tv.html"
    libview, view_from_query = library_view(request)

    def build(data, view):
        items, marks, rows = _library_rows(data, view, kind)
        # media-ux4: each grid card says Watched / Not watched / In progress (a film is in progress while it sits in the
        # viewer's resume list)
        resume = {str(r.get("jf_id")) for r in data.get("up_next") or [] if media_resume.in_progress(r) and r.get("jf_id")}
        for r in rows or []:
            r["card_state"] = media_library.card_state(r, resume)
        media_awards_badges.attach(rows, kind)   # awards-ui item 3: one query for every poster on the page
        arr = get_snapshots().get(ARR_SNAPSHOT_ID)
        arrived = media_library.arrived_this_week((arr.data if arr else {}).get("arrived"), kind)
        arrived = media_library.link_arrivals(arrived, items, kind, lambda jf: item_href(jf))
        q = request.query_params.get("q", "")
        sort = request.query_params.get("sort", "score")
        sort = sort if sort in media_library.SORTS else "score"
        group = (request.query_params.getlist("group") or ["1"])[-1] != "0"
        return {
            "kind": kind, "marks": marks, "rows": rows, "q": q, "sort": sort, "group": group,
            "sorts": media_library.SORT_LABELS, "new_week": arrived,
            "head_line": media_library.head_line(rows or [], kind, marks),
            "groups": media_library.arrange(rows or [], q, sort, group, kind, marks),
            "ratings": _ratings(view, arrived),
            "libview": libview, "libview_links": library_view_links(request),
        }
    resp = _detail_page(request, template, JELLYFIN_SNAPSHOT_ID, build)
    if view_from_query:
        resp.set_cookie(LIBVIEW_COOKIE, libview, max_age=LIBVIEW_MAX_AGE, samesite="lax", path="/media")
    return resp


def _tonight_page(request: Request, kind: str):
    def build(data, view):
        items, marks, rows = _library_rows(data, view, kind)
        ratings = _ratings(view, items or [])
        cards = media_library.deal_tonight(rows or [], ratings, kind, random.Random()) if marks else []
        return {"kind": kind, "marks": marks, "available": rows is not None, "cards": cards,
                "ratings": ratings, "heading": "Three for tonight"}
    return _detail_page(request, "media_tonight.html", JELLYFIN_SNAPSHOT_ID, build)


def _to_rate_page(request: Request, kind: str):
    """Movies / TV Shows > To rate (media-ux4, 2026-10-08): the viewer's rating inbox for this kind (films; TV at the
    owner's level), the Diary > To rate rows; a plain-form rating returns here (media_write.RATE_BACK)."""
    def build(data, view):
        recent = (data.get("history") or {}).get("recent") or []   # the viewer's own history (view_jelly)
        rows = [{**r, "back": request.url.path} for r in _to_rate(recent, _ratings(view, recent)) if r["kind"] == kind]
        return {"kind": kind, "to_rate": rows}
    return _detail_page(request, "media_to_rate.html", JELLYFIN_SNAPSHOT_ID, build)


@app.get("/media/movies/to-rate", response_class=HTMLResponse)
def media_movies_to_rate_page(request: Request):
    return _to_rate_page(request, "movie")


@app.get("/media/tv/to-rate", response_class=HTMLResponse)
def media_tv_to_rate_page(request: Request):
    return _to_rate_page(request, "tv")


@app.get("/media/movies", response_class=HTMLResponse)
def media_movies_page(request: Request):
    return _library_page(request, "movie")


@app.get("/media/movies/tonight", response_class=HTMLResponse)
def media_movies_tonight_page(request: Request):
    return _tonight_page(request, "movie")


@app.get("/media/tv", response_class=HTMLResponse)
def media_tv_page(request: Request):
    return _library_page(request, "tv")


@app.get("/media/tv/tonight", response_class=HTMLResponse)
def media_tv_tonight_page(request: Request):
    return _tonight_page(request, "tv")


def _year_page(request: Request, slug: str, template: str):
    """Year page / countdown: 404 for a bad slug or a year with nothing rated or ranked."""
    def build(data, view):
        ctx = year_ctx(slug, request.query_params.get("mode", ""), _kind_of(request))
        if view == "her":
            ctx["ranked"] = ctx["unranked"] = []
        return {**ctx, "count": len(ctx["ranked"])}
    try:
        resp = _detail_page(request, template, JELLYFIN_SNAPSHOT_ID, build,
                            detail=YEARS_DETAIL, always_build=True)
    except HTTPException:
        resp = None
    ctx_ok = resp is not None and resp.status_code == 200 and (
        resp.context.get("ranked") or resp.context.get("unranked"))
    if not ctx_ok:
        view, _ = resolve_owner_view(request)
        return templates.TemplateResponse(request, "404.html", {
            "areas": registry.visible_areas, "active_id": None, "owner_view": view,
            "missing_text": "No rankings here",
        }, status_code=404)
    return resp


@app.get("/media/years/{slug}", response_class=HTMLResponse)
def media_year_page(request: Request, slug: str):
    return _year_page(request, slug, "media_year.html")


@app.get("/media/years/{slug}/countdown", response_class=HTMLResponse)
def media_year_countdown(request: Request, slug: str):
    return _year_page(request, slug, "media_countdown.html")


def _server_response(request: Request, area, view: str, from_query: bool):
    """The `layout: server` page (WP-S1, 2026-10-06): bands built by hub/server.py."""
    snaps = get_snapshots()
    sv = server_area.build_server(area, snaps, media_backup.current_status(), get_runner(),
                                  server_updates.get_ignores(), server_updates.last_requested(),
                                  get_runner_history(), server_history.recent(),
                                  live=server_area.live_snapshot_ids(registry))  # WP-U3
    tasks = BackgroundTasks()
    tasks.add_task(server_alerts.sync, sv["attention_items"])  # WP-U2: Discord push after the page
    tasks.add_task(server_history.sample, snaps)  # WP-U4: system sample after the page
    resp = templates.TemplateResponse(request, "server.html", {
        "areas": registry.visible_areas, "active_id": area.id, "area": area, "owner_view": view,
        "status": build_status(snaps), "sv": sv,
        "flash": server_updates.flash_text(request.query_params),
    }, background=tasks)
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/server", response_class=HTMLResponse)
def server_page(request: Request):
    view, from_query = resolve_owner_view(request)
    area = next((a for a in registry.areas if a.layout == server_area.SERVER_LAYOUT), None)
    if area is None:
        return templates.TemplateResponse(request, "404.html", {
            "areas": registry.visible_areas, "active_id": None, "owner_view": view,
            "missing_text": "No page here",
        }, status_code=404)
    return _server_response(request, area, view, from_query)


@app.get("/a/{area_id}", response_class=HTMLResponse)
def area_page(request: Request, area_id: str):
    view, from_query = resolve_owner_view(request)
    area = next((a for a in registry.areas if a.id == area_id), None)
    if area is None:
        return templates.TemplateResponse(request, "404.html", {
            "areas": registry.visible_areas, "active_id": None, "missing_id": area_id,
            "owner_view": view,
        }, status_code=404)
    if area.layout == server_area.SERVER_LAYOUT:  # keyed by layout, never by area name
        return _server_response(request, area, view, from_query)
    snaps = get_snapshots()
    tiles = [{"tile": t, "st": tile_state(t, snaps)}
             for t in area.tiles if owner_visible(t, view)]
    if area.layout == "shelves":
        resp = templates.TemplateResponse(request, "area_shelves.html", {
            "areas": registry.visible_areas, "active_id": area.id, "area": area, "owner_view": view,
            "status": build_status(snaps), "sh": build_shelves(area, tiles, snaps, view),
            "backup_warn": media_backup.current_status()["warning"],
        })
        return _maybe_set_cookie(resp, view, from_query)
    media = find_media(tiles, snaps)
    upcoming = find_upcoming(tiles, snaps, view)
    # Weather renders on the hub and /weather only (2026-10-08, B. — supersedes the
    # Calendar-page card). The registry tile stays: find_weather's config anchor.
    tiles = [r for r in tiles if r["tile"].snapshot != WEATHER_SNAPSHOT_ID]
    resp = templates.TemplateResponse(request, "area.html", {
        "areas": registry.visible_areas, "active_id": area.id, "area": area, "tiles": tiles,
        "owner_view": view, "status": build_status(snaps),
        "upcoming": upcoming,
        "media": media,
        "ratings": _ratings(view, *_media_rows(media)),
    })
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "areas": len(registry.areas) if registry else 0,
        "registry_loaded_at": registry_loaded_at,
    }


@app.get("/whoami")
def whoami(request: Request):
    return JSONResponse({"email": request.headers.get(IDENTITY_HEADER, "-")})
