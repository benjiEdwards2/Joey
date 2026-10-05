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

from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hub import media_backup, media_db, media_nav
from hub.images import router as images_router
from hub import media_discover as _media_discover, media_write as _media_write
from hub.media_discover import DISCOVER_DETAIL, router as media_discover_router
from hub import media_library
from hub.media_write import router as media_write_router, year_ctx
from hub.registry import Registry, load_registry
from hub.store import get_snapshots, tile_state

HUB_DIR = Path(__file__).resolve().parent
REPO_ROOT = HUB_DIR.parent
IDENTITY_HEADER = "Cf-Access-Authenticated-User-Email"

log = logging.getLogger("hub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

registry: Registry | None = None
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the registry at startup, failing fast with the aggregated violation list."""
    global registry, registry_loaded_at
    areas_path = os.environ.get("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    registry = load_registry(areas_path)  # ValueError here aborts startup by design
    registry_loaded_at = datetime.now(timezone.utc).isoformat()
    log.info("registry loaded from %s: %d areas", areas_path, len(registry.areas))
    backup_task = None if media_backup.disabled() else asyncio.create_task(_backup_loop())
    yield
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


app.include_router(images_router)
app.include_router(media_write_router)
app.include_router(media_discover_router)
app.mount("/static", StaticFiles(directory=str(HUB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(HUB_DIR / "templates"))


def _static_version() -> str:
    """Content hash of the stylesheet, appended as ?v= so a deploy that changes
    CSS is never painted with a browser's stale copy (StaticFiles sends no
    Cache-Control; field note 2026-09-11, bit us 2026-10-05)."""
    import hashlib
    try:
        return hashlib.sha1((HUB_DIR / "static" / "control-surface.css").read_bytes()).hexdigest()[:8]
    except OSError:
        return "0"


templates.env.globals["static_v"] = _static_version()


OWNER_VIEWS = ("both", "you", "her")
OWNER_COOKIE = "owner_view"
OWNER_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days, per device (WP19)


def resolve_owner_view(request: Request) -> tuple[str, bool]:
    """Query param wins (and sets the cookie); else cookie; else 'both'.

    Semantics per Q9 (answered 2026-08-25): you = you+shared, her = her+shared.
    Returns (view, came_from_query).
    """
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
                return {"tile": t, "st": tile_state(t, snaps), "accent": a.accent,
                        "glyph": weather_glyph(data.get("condition_text")), "data": data}
    return None


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
HISTORY_DETAIL = "/media/history"  # the tile reading the jellyfin snapshot as watch history
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
    snapshot), its area (for the accent), and the area's first LINK tile (the app
    launcher, as find_media resolves it). None when no tile reads the snapshot."""
    for a in registry.areas:
        for t in a.tiles:
            if t.snapshot == snapshot_id and (detail is None or t.detail == detail):
                snap = snaps.get(snapshot_id)
                href = next((x.href for x in a.tiles if x.tier.value == "link"), None)
                return {"tile": t, "st": tile_state(t, snaps), "accent": a.accent,
                        "data": snap.data if snap else {}, "href": href}
    return None


def _parse_ts(value) -> datetime:
    """ISO timestamp -> aware datetime (Jellyfin's 7-digit fractions tolerated)."""
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value).replace("Z", "+00:00"))
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ratings(view: str, *row_lists) -> dict:
    """ONE get_ratings() per page render, for the view's owner (her view = her own ratings)."""
    return media_db.get_ratings((r.get("item_key") for rows in row_lists for r in rows or []),
                                media_db.owner_of(view))


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
    return waiting_counts(recent, _ratings(view, recent),
                          {t.detail for t in area.tiles if t.detail and owner_visible(t, view)})


def media_frame(request: Request) -> dict:
    """Template global `media_nav(request)`: the Media bar/tabs context (cached per request)."""
    cached = getattr(request.state, "media_nav", None)
    if cached is None:
        view, _ = resolve_owner_view(request)
        area = media_nav.shelves_area(registry)
        waiting = area_waiting(area, get_snapshots(), view) if area else {}
        cached = request.state.media_nav = media_nav.nav_context(request, registry, waiting, view)
    return cached


for _t in (templates, _media_write.templates, _media_discover.templates):
    _t.env.globals["media_nav"] = media_frame


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
                "href": href, "item_key": r.get("item_key"), **extra}

    def jf_item(r, sub, fallback):
        """Row that opens in Jellyfin when it carries a jf_id (new tab), else a Joey page."""
        url = _deep_link(link, r.get("jf_id"), server_id)
        return item(r, sub, url or fallback, **({"external": True} if url else {}))

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
    this_week = [item(r, " · ".join(x for x in (_day_label(date.fromisoformat(r["date"]), now.date()), r.get("label")) if x),
                      LIBRARY_DETAIL) for r in (arr.get("this_week") or [])][:SHELF_MAX]
    downloading = [item(r, f"{r.get('status_text')} · {r.get('time_left')}".strip(" ·"), LIBRARY_DETAIL)
                   for r in (arr.get("downloading") or [])][:SHELF_MAX]

    watched_rows = recent[:SHELF_MAX]
    ratings = _ratings(view, up_next, added, recent, this_week, downloading)  # ONE query for every shelf

    unset_text = "Set JELLYFIN_USER_HER in deploy/.env"
    add("continue", "Continue watching", PLAYING_DETAIL,
        [jf_item(n, n.get("remaining_text"), PLAYING_DETAIL) for n in up_next[:SHELF_MAX]],
        unset_text if her_unset else "Nothing up next")
    add("added", "Recently added", LIBRARY_DETAIL, added, "Nothing added recently")
    add("thisweek", "This week", LIBRARY_DETAIL, this_week, "Nothing due this week")
    add("downloading", "Downloading", LIBRARY_DETAIL, downloading, "", omit_empty=True)
    add("watched", "Recently watched", DIARY_DETAIL,
        [jf_item(r, r.get("when", ""), DIARY_DETAIL) for r in watched_rows],
        unset_text if her_unset else "Nothing watched yet")
    for sh in shelves:
        for it in sh["items"]:
            it["score"] = ratings.get(it.pop("item_key", None))

    return {
        "hero": hero, "kind_word": kind_word, "shelves": shelves,
        "waiting": waiting_counts(recent, ratings, set(by_detail)),
        "open_href": link,
        "freshness": jelly_row["st"] if jelly_row else None,
    }


@app.get("/", response_class=HTMLResponse)
def hub_page(request: Request):
    view, from_query = resolve_owner_view(request)
    snaps = get_snapshots()
    cards = []
    for a in registry.areas:
        summary = next(t for t in a.tiles if t.id == a.summary_tile)
        if not owner_visible(summary, view):
            continue  # hub summary cards respect the filter (Q24 assumption)
        card = {"area": a, "tile": summary, "st": tile_state(summary, snaps), "hero": None}
        if a.layout == "shelves":  # hero content keyed by layout, never by area name
            link = next((st["href"] for t in a.tiles if owner_visible(t, view)
                         for st in [tile_state(t, snaps)] if st["state"] == "link"), None)
            jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
            jdata = view_jelly(jelly.data if jelly else {}, view)
            card["hero"] = media_hero(jdata, link)
            card["waiting"] = area_waiting(a, snaps, view)
        cards.append(card)
    cards.sort(key=lambda c: c["area"].hub_rank)  # stable; the area order itself is untouched
    resp = templates.TemplateResponse(request, "hub.html", {
        "areas": registry.areas, "active_id": None, "cards": cards, "owner_view": view,
        "status": build_status(snaps), "weather": find_weather(snaps),
        "backup_warn": media_backup.current_status()["warning"],
    })
    return _maybe_set_cookie(resp, view, from_query)


@app.get("/weather", response_class=HTMLResponse)
def weather_page(request: Request):
    """Detail behind the hub glimpse (2026-09-11). Reads the same snapshot; today only."""
    view, from_query = resolve_owner_view(request)
    snaps = get_snapshots()
    resp = templates.TemplateResponse(request, "weather.html", {
        "areas": registry.areas, "active_id": None, "owner_view": view,
        "status": build_status(snaps), "w": find_weather(snaps),
    })
    return _maybe_set_cookie(resp, view, from_query)


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
            "areas": registry.areas, "active_id": None, "owner_view": view,
            "missing_text": "No page here",
        }, status_code=404)
    if snapshot_id == JELLYFIN_SNAPSHOT_ID:
        src = {**src, "data": view_jelly(src["data"], view)}  # her view reads Georgina's up next/history
    extra = build(src["data"], view) if build and (always_build or src["st"]["state"] != "off") else {}
    resp = templates.TemplateResponse(request, template, {
        "areas": registry.areas, "active_id": None, "owner_view": view,
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
        return {
            "week": groups,
            "app_notes": [f"{app.title()} not answering: {reason}"
                          for app, reason in sorted((data.get("app_errors") or {}).items())],
            "ratings": _ratings(view, *(data.get(k) for k in ("arrived", "updated", "this_week", "downloading"))),
        }
    return _detail_page(request, "media_library.html", ARR_SNAPSHOT_ID, build)


@app.get("/media/requests", response_class=HTMLResponse)
def media_requests_page(request: Request):
    def build(data, view):
        c = data.get("counts") or {}
        return {"counts_text": " · ".join(f"{c.get(k, 0)} {k}"
                                          for k in ("pending", "approved", "available", "declined")),
                "ratings": _ratings(view, data.get("requests"))}
    return _detail_page(request, "media_requests.html", JELLYSEERR_SNAPSHOT_ID, build)


def _to_rate(recent, ratings) -> list[dict]:
    """The rating inbox: unrated titles watched in the last TO_RATE_DAYS, one per item_key
    (a show's episodes collapse to the show, which is what gets rated)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=TO_RATE_DAYS)
    seen, rows = set(), []
    for r in recent:
        key = r.get("item_key")
        try:
            fresh = _parse_ts(r["watched_at"]) >= cutoff
        except Exception:
            continue
        if not key or key in ratings or key in seen or not fresh:
            continue
        seen.add(key)
        kind = media_db.norm_kind(r.get("kind"))
        rows.append({"item_key": key, "kind": kind, "year": None,
                     "title": media_db.base_title(r["title"], kind),
                     "poster": r.get("poster"), "when": r.get("when", "")})
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
            "shows": [{**s, "pct": round(s["episodes"] / top * 100)} for s in shows],
            "numbers": " · ".join([
                f"{history.get('week_count', 0)} this week",
                f"{history.get('month_count', 0)} this month",
                f"{history.get('hours_month', 0)} h this month",
                f"{history.get('hours_total', 0)} h all time"]),
        }
    return _detail_page(request, "media_history.html", JELLYFIN_SNAPSHOT_ID, build, detail=HISTORY_DETAIL)


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
        for row in rows:
            label = date.fromisoformat(row["watched_on"]).strftime("%B %Y")
            if not months or months[-1]["label"] != label:
                months.append({"label": label, "rows": []})
            months[-1]["rows"].append(row)
        on_this_day = history.get("on_this_day", [])
        streak = stats["streak_days"]
        return {
            "stats_text": " · ".join([
                f"{stats['this_week']} this week", f"{stats['this_month']} this month",
                f"{stats['total']} all time",
                f"{streak}-day streak" if streak else "no current streak"]),
            "milestones": stats["milestones"][:MILESTONES_MAX],
            "months": months, "kind": kind or "", "today": date.today().isoformat(),
            "on_this_day": on_this_day,
            "older": (f"/media/diary?offset={offset + DIARY_PAGE}" + (f"&kind={kind}" if kind else ""))
                     if more else None,
            "ratings": _ratings(view, rows, on_this_day),
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


def _lib_href(link, server_id):
    """href_of for media_library rows: Joey title page for a tmdb key, else the Jellyfin deep link."""
    def href_of(row, kind):
        key = str(row.get("item_key") or "")
        if key.startswith("tmdb:") and key[5:].isdigit():
            return f"/media/title/{kind}/{key[5:]}", False
        url = _deep_link(link, row.get("jf_id"), server_id)
        return url, bool(url)
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
    link = (find_detail_source(JELLYFIN_SNAPSHOT_ID, get_snapshots()) or {}).get("href")
    maker = media_library.film_rows if kind == "movie" else media_library.show_rows
    return items, marks, maker(items, _ratings(view, items), lambda v: _ago_text(v, now),
                               _lib_href(link, data.get("server_id")), marks)


def _library_page(request: Request, kind: str):
    template = "media_movies.html" if kind == "movie" else "media_tv.html"

    def build(data, view):
        items, marks, rows = _library_rows(data, view, kind)
        arr = get_snapshots().get(ARR_SNAPSHOT_ID)
        arrived = media_library.arrived_this_week((arr.data if arr else {}).get("arrived"), kind)
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
        }
    return _detail_page(request, template, JELLYFIN_SNAPSHOT_ID, build)


def _tonight_page(request: Request, kind: str):
    def build(data, view):
        items, marks, rows = _library_rows(data, view, kind)
        ratings = _ratings(view, items or [])
        cards = media_library.deal_tonight(rows or [], ratings, kind, random.Random()) if marks else []
        return {"kind": kind, "marks": marks, "available": rows is not None, "cards": cards,
                "ratings": ratings, "heading": "Three for tonight"}
    return _detail_page(request, "media_tonight.html", JELLYFIN_SNAPSHOT_ID, build)


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
            "areas": registry.areas, "active_id": None, "owner_view": view,
            "missing_text": "No rankings here",
        }, status_code=404)
    return resp


@app.get("/media/years/{slug}", response_class=HTMLResponse)
def media_year_page(request: Request, slug: str):
    return _year_page(request, slug, "media_year.html")


@app.get("/media/years/{slug}/countdown", response_class=HTMLResponse)
def media_year_countdown(request: Request, slug: str):
    return _year_page(request, slug, "media_countdown.html")


@app.get("/a/{area_id}", response_class=HTMLResponse)
def area_page(request: Request, area_id: str):
    view, from_query = resolve_owner_view(request)
    area = next((a for a in registry.areas if a.id == area_id), None)
    if area is None:
        return templates.TemplateResponse(request, "404.html", {
            "areas": registry.areas, "active_id": None, "missing_id": area_id,
            "owner_view": view,
        }, status_code=404)
    snaps = get_snapshots()
    tiles = [{"tile": t, "st": tile_state(t, snaps)}
             for t in area.tiles if owner_visible(t, view)]
    if area.layout == "shelves":
        resp = templates.TemplateResponse(request, "area_shelves.html", {
            "areas": registry.areas, "active_id": area.id, "area": area, "owner_view": view,
            "status": build_status(snaps), "sh": build_shelves(area, tiles, snaps, view),
            "backup_warn": media_backup.current_status()["warning"],
        })
        return _maybe_set_cookie(resp, view, from_query)
    media = find_media(tiles, snaps)
    resp = templates.TemplateResponse(request, "area.html", {
        "areas": registry.areas, "active_id": area.id, "area": area, "tiles": tiles,
        "owner_view": view, "status": build_status(snaps),
        "upcoming": find_upcoming(tiles, snaps, view),
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
