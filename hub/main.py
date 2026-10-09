"""Joey hub — FastAPI skeleton. Every route and the tab bar render from
areas.yaml; no area name appears in this code (WP17 verify greps for that).
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTasks

from hub import media_backup, media_db, media_downloads
from hub.images import router as images_router
from hub.media_discover import router as media_discover_router
from hub import media_film, media_person, media_library, media_plays
from hub import media_awards_badges
from hub import media_write as _media_write
from hub.media_write import PLACES, router as media_write_router, year_ctx
from hub import media_arr_search, media_follow, media_requests, media_resume
from hub import media_awards_pages
from hub import server as server_area
from hub import server_alerts, server_history, server_updates
from hub.media_watchlist import router as media_watchlist_router
from hub import calendar, media_home, shell, tasks, weather
# W3: the shared Media helpers live in hub/media_home.py; re-exported for the old `hub.main.X` paths.
from hub.media_home import (  # noqa: F401
    DIARY_DETAIL, HISTORY_DETAIL, HISTORY_PLAYS, HISTORY_STRIP_MAX, LEVEL_KEYS, LIBRARY_DETAIL, LIBRARY_STRIP_MAX,
    PLAYING_DETAIL, Ratings, SHELF_MAX, TO_RATE_DAYS, YEARS_DETAIL, _ago_text, _library_text, _media_rows,
    _parse_ts, _profile_rows, _ratings, _recent, _split_title, _to_rate, _to_rate_title, area_waiting,
    build_shelves, find_media, hub_shelf, item_href, media_frame, media_hero, resume_acts, row_href, score_for,
    to_rate_tab_counts, view_jelly, waiting_counts,
)
# W3: the calendar helpers live in hub/calendar.py; re-exported for the old `hub.main.X` paths.
from hub.calendar import (UPCOMING_DAYS, _day_label, _event_dt, build_upcoming, find_upcoming,  # noqa: F401
                          hub_upcoming, per_day_counts)
# W3: the weather helpers and routes live in hub/weather.py; re-exported for the old `hub.main.X` paths.
from hub.weather import (RADAR_FILE_RE, RADAR_OVER, RADAR_SLOTS, RADAR_UNDER, WINDY_DEFAULT, WINDY_EMBED,  # noqa: F401
                         WINDY_ZOOM, WX_CHART_H, WX_CHART_PAD, WX_CHART_W, WX_LABEL_EVERY, WX_RAIN_BASE, WX_RAIN_MAX_H,
                         WX_TEMP_BOTTOM, WX_TEMP_TOP, _frame_minutes, _radar_clock, _radar_dir, _wx_chart,
                         _wx_day_label, _wx_num, _wx_uv_word, find_weather, weather_forecast, weather_glyph,
                         weather_page, weather_radar, weather_radar_file, windy_embed_url)
# W3: background loops + lifespan live in hub/tasks.py; re-exported for the old `hub.main.X` paths.
from hub.tasks import (BACKUP_EVERY_S, BACKUP_FIRST_DELAY_S, _backup_loop, _every, _media_awards_loop,  # noqa: F401
                       _media_follow_loop, _media_warmup_loop, _server_alerts_loop, _server_tick, lifespan)
from hub.identity import IDENTITY_HEADER
from hub.ids import (ARR_SNAPSHOT_ID, GCAL_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID,
                     MEDIA_STATUS_SNAPSHOT_ID, QBIT_SNAPSHOT_ID, WEATHER_SNAPSHOT_ID)
# W3 (H-44/H-45): the shared page shell lives in hub/shell.py (ONE Jinja env for every router, H-31); these names
# are re-exported so the old `hub.main.X` paths keep working. Callers use shell.X.
from hub.shell import (OWNER_COOKIE, OWNER_COOKIE_MAX_AGE, OWNER_VIEWS, Compress, ShellMiddleware,  # noqa: F401
                       _deep_link, _maybe_set_cookie, _now_home, _static_version, build_status, find_detail_source,
                       get_snapshots, identity_of, not_found_page, owner_visible, render_page, resolve_owner_view,
                       templates)
from hub.store import get_runner, get_runner_history, tile_state

HUB_DIR = Path(__file__).resolve().parent
REPO_ROOT = HUB_DIR.parent

log = logging.getLogger("hub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
# hub.shell.ShellMiddleware writes the one request line (owner word, quiet paths skipped); uvicorn's access log
# would repeat every request, the 30 s healthcheck and every poster (H-58, N-28).
logging.getLogger("uvicorn.access").disabled = True

app = FastAPI(title="Joey hub", lifespan=tasks.lifespan)


# Request log + Cache-Control (pages no-store, /static/ immutable when ?v= versioned, else an hour) in one pure
# ASGI layer; text bodies gzipped (hub/shell.py).
app.add_middleware(ShellMiddleware)
app.add_middleware(Compress)


# Query params that only carry a one-off flash line after a POST's 303 (2026-10-08). base.html strips them from
# the address bar after render (history.replaceState), so Back / Forward / reload never re-show the flash. Derived
# from the Media modules' registry (media_write.flash_keys, M-17) plus the Server page's own (server_updates).
SERVER_FLASH_PARAMS = ("flash", "c", "code")
FLASH_PARAMS = tuple(dict.fromkeys([*_media_write.FLASH_KEYS, *SERVER_FLASH_PARAMS]))
templates.env.globals["flash_params"] = FLASH_PARAMS

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
app.include_router(weather.router)
app.mount("/static", StaticFiles(directory=str(HUB_DIR / "static")), name="static")

DIARY_PAGE = 50
MILESTONES_MAX = 5


def hub_greeting(now: datetime, name: str | None = None) -> str:
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    hello = f"Good {part}, {name}." if name else f"Good {part}."
    return f"{hello} Here's what's happening at home today, {now:%A} {now.day} {now:%B}."


# The hub page would otherwise pay for the Server page on every load (H-49): the runner history tail (up to
# 2 MB of JSON lines), the ignores table and the sweep stats. The card is kept 60 s while the snapshots and the
# backup word are unchanged; the /server page itself is never cached.
HUB_CARD_TTL_S = 60
_hub_card_cache: tuple | None = None   # (monotonic time, key, card)


def _server_hub_card(snaps, backup: dict) -> dict:
    global _hub_card_cache
    key = (tuple(sorted((cid, s.updated_at, s.status) for cid, s in snaps.items())), backup.get("warning"))
    now = time.monotonic()
    hit = _hub_card_cache
    if hit and hit[1] == key and now - hit[0] < HUB_CARD_TTL_S:
        return hit[2]
    card = server_area.hub_card(snaps, server_updates.get_ignores(), backup, get_runner(), get_runner_history(),
                                live=server_area.live_snapshot_ids(shell.registry))  # WP-U3
    _hub_card_cache = (now, key, card)
    return card


def server_card_state(st: dict, snaps, backup: dict | None = None) -> dict:
    """The Server hub card (WP-U2): hub/server.py's words over the summary tile's state. Something in Attention
    makes it state `warn` (H-34: its own state, no longer a borrowed "stale"), which _kpi.html badges amber like
    stale, with the words "Needs attention" (· the tile's own stale age, when it is stale too)."""
    card = _server_hub_card(snaps, media_backup.current_status() if backup is None else backup)
    out = {**st, "value": card["summary"], "secondary": card["secondary"]}
    if card["state"] == "warn":
        stale = st.get("age_text") if st["state"] == "stale" else None
        out.update(state="warn", age_text="Needs attention" + (f" · {stale}" if stale else ""))
    return out


@app.get("/", response_class=HTMLResponse)
def hub_page(request: Request):
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)
    backup = media_backup.current_status()  # once per request: the Server card and the backup line (H-49)
    cards, shelf = [], None
    upcoming = calendar.hub_upcoming(snaps, view)
    for a in shell.registry.visible_areas:
        summary = next(t for t in a.tiles if t.id == a.summary_tile)
        if not shell.owner_visible(summary, view):
            continue  # hub summary cards respect the filter (Q24 assumption)
        card = {"area": a, "tile": summary, "st": tile_state(summary, snaps), "hero": None,
                "per_day": None}
        if summary.snapshot == GCAL_SNAPSHOT_ID and upcoming:  # keyed by connector id, never area name
            card["per_day"] = upcoming["per_day"]
        if a.layout == server_area.SERVER_LAYOUT and card["st"]["state"] != "off":
            try:
                card["st"] = server_card_state(card["st"], snaps, backup)  # WP-U2: the card's own words
            except Exception as exc:  # a malformed envelope never 500s the hub: the plain tile state stays (H-63)
                log.warning("server hub card skipped: %s", type(exc).__name__)
        if a.layout == "shelves":  # hero content keyed by layout, never by area name
            link = next((st["href"] for t in a.tiles if shell.owner_visible(t, view)
                         for st in [tile_state(t, snaps)] if st["state"] == "link"), None)
            jelly = snaps.get(JELLYFIN_SNAPSHOT_ID)
            jdata = media_home.view_jelly(jelly.data if jelly else {}, view)
            card["hero"] = media_home.media_hero(jdata, link)
            qb = snaps.get(QBIT_SNAPSHOT_ID)
            card["downloading"] = (qb.data.get("summary") if qb and qb.data.get("active") else None)
            card["waiting"] = media_home.area_waiting(a, snaps, view)
            if shelf is None:
                shelf = media_home.hub_shelf(a, snaps, view)
        cards.append(card)
    cards.sort(key=lambda c: c["area"].hub_rank)  # stable; the area order itself is untouched
    resp = shell.render_page(request, "hub.html", {
        "cards": cards,
        "status": shell.build_status(snaps), "weather": weather.find_weather(snaps),  # status: hub.html only (H-50)
        "upcoming": upcoming, "shelf": shelf,
        "backup_warn": backup["warning"],
        "greeting": hub_greeting(shell._now_home(), shell.identity_of(request).owner and shell.identity_of(request).name),
    })
    return shell._maybe_set_cookie(resp, view, from_query)


def _detail_page(request: Request, template: str, snapshot_id: str, build=None, detail=None,
                 always_build=False):
    """Detail page behind a `detail` tile (2026-10-05). Keyed by connector id —
    404 when no registry tile reads that snapshot; 'Not connected' when it has no data
    (`always_build` still runs `build` then — the diary has data of its own)."""
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)
    src = shell.find_detail_source(snapshot_id, snaps, detail)
    if src is None:
        return shell.not_found_page(request)
    if snapshot_id == JELLYFIN_SNAPSHOT_ID:
        src = {**src, "data": media_home.view_jelly(src["data"], view)}  # her view reads Georgina's up next/history
    extra = build(src["data"], view) if build and (always_build or src["st"]["state"] != "off") else {}
    resp = shell.render_page(request, template, {
        "src": src, "ratings": {}, **extra,
        "owner": media_db.owner_of(view),  # media_playing.html's Move on acts (M-16)
    })
    return shell._maybe_set_cookie(resp, view, from_query)


@app.get("/media/apps", response_class=HTMLResponse)
def media_apps_page(request: Request):
    return _detail_page(request, "media_apps.html", MEDIA_STATUS_SNAPSHOT_ID, always_build=True,
                        build=lambda data, view: {"backup": media_backup.current_status()})


@app.get("/media/playing", response_class=HTMLResponse)
def media_playing_page(request: Request):
    def build(data, view):
        now = datetime.now(timezone.utc)
        return {
            "latest": [{**i, "added_text": media_home._ago_text(i.get("added_at"), now)}
                       for i in data.get("latest", [])],
            "library_text": media_home._library_text(data.get("library") or {}),
            "ratings": media_home._ratings(view, data.get("now_playing"), data.get("up_next"), data.get("latest")),
        }
    return _detail_page(request, "media_playing.html", JELLYFIN_SNAPSHOT_ID, build)


def _qb_data(request=None) -> dict:
    snap = shell.get_snapshots(request=request).get(QBIT_SNAPSHOT_ID)
    return snap.data if snap else {}


def _arr_linker(view, request=None):
    """Rows -> rows with `href`: same resolver the Movies/TV pages use, per kind, against the
    view's own Jellyfin lists (media_library.link_arrivals). Rows without an item_key stay None."""
    jelly = shell.get_snapshots(request=request).get(JELLYFIN_SNAPSHOT_ID)
    jdata = jelly.data if jelly else {}
    lists = {k: _library_lists(jdata, view, k)[0] for k in ("movie", "tv")}

    def link(rows, need_key=False):
        return [{**r, "href": None} if need_key and not r.get("item_key") else
                media_library.link_arrivals([r], lists[k], k, lambda jf: media_home.item_href(jf))[0]
                for r in rows or [] for k in ("movie" if r.get("kind") == "movie" else "tv",)]
    return link


@app.get("/media/downloads", response_class=HTMLResponse)
def media_downloads_page(request: Request):
    def build(data, view):
        # Whole row is the link (2026-10-06) when the torrent is an arr download whose title resolves.
        arr = shell.get_snapshots(request=request).get(ARR_SNAPSHOT_ID)
        by_hash = {str(r.get("download_id") or "").lower(): r
                   for r in media_downloads.collapse_packs((arr.data if arr else {}).get("downloading"))
                   if r.get("download_id")}
        link = _arr_linker(view, request)
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
                groups.append({"day": day, "label": calendar._day_label(day, today), "rows": []})
            groups[-1]["rows"].append(row)
        merged = media_downloads.merge_downloading(data.get("downloading"), _qb_data(request))
        # Whole row is the link (B., 2026-10-06): Joey item page, title page or nothing — same
        # resolver the Movies/TV pages use, per kind, against the view's own Jellyfin lists.
        link = _arr_linker(view, request)

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
            "ratings": media_home._ratings(view, *(data.get(k) for k in ("arrived", "updated", "this_week")), merged),
        }
    return _detail_page(request, "media_library.html", ARR_SNAPSHOT_ID, build)


@app.get("/media/requests", response_class=HTMLResponse)
def media_requests_page(request: Request):
    def build(data, view):
        # Remove (2026-10-08): a removed row leaves at once (media_hidden), not at the next hourly sweep.
        snap = shell.get_snapshots(request=request).get(JELLYSEERR_SNAPSHOT_ID)
        rows = media_requests.visible_rows(data, snap.updated_at if snap else None)
        c = media_requests.visible_counts(data, rows)
        good, warn = media_requests.flash_text(request.query_params)
        return {"counts_text": " · ".join(f"{c.get(k, 0)} {k}"
                                          for k in ("pending", "approved", "available", "declined")),
                "rows": rows, "flash": good, "flash_warn": warn,
                "ratings": media_home._ratings(view, rows)}
    return _detail_page(request, "media_requests.html", JELLYSEERR_SNAPSHOT_ID, build)


@app.get("/media/history", response_class=HTMLResponse)
def media_history_page(request: Request):
    def build(data, view):
        history = data.get("history") or {}
        recent = history.get("recent", [])
        ratings = media_home._ratings(view, recent)
        return {
            "history": history,
            "ratings": ratings,
            "to_rate": media_home._to_rate(recent, ratings),
            "rating_levels": media_db.LEVELS,
            "rating_level": ratings.level,
            "numbers": " · ".join([
                f"{history.get('week_count', 0)} this week",
                f"{history.get('month_count', 0)} this month",
                f"{history.get('hours_month', 0)} h this month",
                f"{history.get('hours_total', 0)} h all time"]),
        }
    return _detail_page(request, "media_history.html", JELLYFIN_SNAPSHOT_ID, build, detail=media_home.HISTORY_DETAIL)


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
            "months": months, "kind": kind or "", "today": date.today().isoformat(), "places": PLACES,
            "on_this_day": on_this_day,
            "older": (f"/media/diary?offset={offset + DIARY_PAGE}" + (f"&kind={kind}" if kind else ""))
                     if more else None,
            "ratings": media_home._ratings(view, lines, on_this_day),
        }
    return _detail_page(request, "media_diary.html", JELLYFIN_SNAPSHOT_ID, build,
                        detail=media_home.DIARY_DETAIL, always_build=True)


@app.get("/media/years", response_class=HTMLResponse)
def media_years_page(request: Request):
    """Year rankings (2026-10-05): one tile per rating year. Pure media.db — no snapshot data needed."""
    def build(data, view):
        kind = _kind_of(request)
        return {"years": [] if view == "her" else media_db.years_overview(kind), "kind": kind}
    return _detail_page(request, "media_years.html", JELLYFIN_SNAPSHOT_ID, build,
                        detail=media_home.YEARS_DETAIL, always_build=True)


def _kind_of(request: Request) -> str | None:
    kind = request.query_params.get("kind")
    return kind if kind in ("movie", "tv") else None


def _lib_href():
    """href_of for media_library rows (F9): the Joey item page for a Jellyfin id, else the title page for a tmdb key."""
    def href_of(row, kind):
        url = media_home.item_href(row.get("jf_id"))
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
    return items, marks, maker(items, media_home._ratings(view, items), lambda v: media_home._ago_text(v, now),
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
        arr = shell.get_snapshots(request=request).get(ARR_SNAPSHOT_ID)
        arrived = media_library.arrived_this_week((arr.data if arr else {}).get("arrived"), kind)
        arrived = media_library.link_arrivals(arrived, items, kind, lambda jf: media_home.item_href(jf))
        q = request.query_params.get("q", "")
        sort = request.query_params.get("sort", "score")
        sort = sort if sort in media_library.SORTS else "score"
        group = (request.query_params.getlist("group") or ["1"])[-1] != "0"
        return {
            "kind": kind, "marks": marks, "rows": rows, "q": q, "sort": sort, "group": group,
            "sorts": media_library.SORT_LABELS, "new_week": arrived,
            "head_line": media_library.head_line(rows or [], kind, marks),
            "groups": media_library.arrange(rows or [], q, sort, group, kind, marks),
            "ratings": media_home._ratings(view, arrived),
            "libview": libview, "libview_links": library_view_links(request),
        }
    resp = _detail_page(request, template, JELLYFIN_SNAPSHOT_ID, build)
    if view_from_query:
        resp.set_cookie(LIBVIEW_COOKIE, libview, max_age=LIBVIEW_MAX_AGE, samesite="lax", path="/media")
    return resp


def _tonight_page(request: Request, kind: str):
    def build(data, view):
        items, marks, rows = _library_rows(data, view, kind)
        ratings = media_home._ratings(view, items or [])
        cards = media_library.deal_tonight(rows or [], ratings, kind, random.Random()) if marks else []
        return {"kind": kind, "marks": marks, "available": rows is not None, "cards": cards,
                "ratings": ratings, "heading": "Three for tonight"}
    return _detail_page(request, "media_tonight.html", JELLYFIN_SNAPSHOT_ID, build)


def _to_rate_page(request: Request, kind: str):
    """Movies / TV Shows > To rate (media-ux4, 2026-10-08): the viewer's rating inbox for this kind (films; TV at the
    owner's level), the Diary > To rate rows; a plain-form rating returns here (media_write.RATE_BACK)."""
    def build(data, view):
        recent = (data.get("history") or {}).get("recent") or []   # the viewer's own history (view_jelly)
        rows = [{**r, "back": request.url.path} for r in media_home._to_rate(recent, media_home._ratings(view, recent)) if r["kind"] == kind]
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
                            detail=media_home.YEARS_DETAIL, always_build=True)
    except HTTPException:
        resp = None
    ctx_ok = resp is not None and resp.status_code == 200 and (
        resp.context.get("ranked") or resp.context.get("unranked"))
    if not ctx_ok:
        return shell.not_found_page(request)
    return resp


@app.get("/media/years/{slug}", response_class=HTMLResponse)
def media_year_page(request: Request, slug: str):
    return _year_page(request, slug, "media_year.html")


@app.get("/media/years/{slug}/countdown", response_class=HTMLResponse)
def media_year_countdown(request: Request, slug: str):
    return _year_page(request, slug, "media_countdown.html")


def _server_response(request: Request, area, view: str, from_query: bool):
    """The `layout: server` page (WP-S1, 2026-10-06): bands built by hub/server.py."""
    snaps = shell.get_snapshots(request=request)
    sv = server_area.build_server(area, snaps, media_backup.current_status(), get_runner(),
                                  server_updates.get_ignores(), server_updates.last_requested(),
                                  get_runner_history(), server_history.recent(),
                                  live=server_area.live_snapshot_ids(shell.registry),  # WP-U3
                                  gated=shell.registry.gated_hrefs)
    after = BackgroundTasks()
    after.add_task(server_alerts.sync, sv["attention_items"])  # WP-U2: Discord push after the page
    after.add_task(server_history.sample, snaps)  # WP-U4: system sample after the page
    resp = shell.render_page(request, "server.html", {
        "area": area, "sv": sv,
        "flash": server_updates.flash_text(request.query_params),
    }, active_id=area.id)
    resp.background = after
    return shell._maybe_set_cookie(resp, view, from_query)


@app.get("/server", response_class=HTMLResponse)
def server_page(request: Request):
    view, from_query = shell.resolve_owner_view(request)
    area = next((a for a in shell.registry.areas if a.layout == server_area.SERVER_LAYOUT), None)
    if area is None:
        return shell.not_found_page(request)
    return _server_response(request, area, view, from_query)


@app.get("/a/{area_id}", response_class=HTMLResponse)
def area_page(request: Request, area_id: str):
    view, from_query = shell.resolve_owner_view(request)
    area = next((a for a in shell.registry.areas if a.id == area_id), None)
    if area is None:
        return shell.not_found_page(request)
    if area.layout == server_area.SERVER_LAYOUT:  # keyed by layout, never by area name
        return _server_response(request, area, view, from_query)
    snaps = shell.get_snapshots(request=request)
    tiles = [{"tile": t, "st": tile_state(t, snaps)}
             for t in area.tiles if shell.owner_visible(t, view)]
    if area.layout == "shelves":
        resp = shell.render_page(request, "area_shelves.html", {
            "area": area,
            "sh": media_home.build_shelves(area, tiles, snaps, view),
            "backup_warn": media_backup.current_status()["warning"],
        }, active_id=area.id)
        return shell._maybe_set_cookie(resp, view, from_query)
    media = media_home.find_media(tiles, snaps)
    upcoming = calendar.find_upcoming(tiles, snaps, view)
    # Weather renders on the hub and /weather only (2026-10-08, B. — supersedes the
    # Calendar-page card). The registry tile stays: find_weather's config anchor.
    tiles = [r for r in tiles if r["tile"].snapshot != WEATHER_SNAPSHOT_ID]
    resp = shell.render_page(request, "area.html", {
        "area": area, "tiles": tiles,
        "upcoming": upcoming,
        "media": media,
        "ratings": media_home._ratings(view, *media_home._media_rows(media)),
    }, active_id=area.id)
    return shell._maybe_set_cookie(resp, view, from_query)


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "areas": len(shell.registry.areas) if shell.registry else 0,
        "registry_loaded_at": shell.registry_loaded_at,
    }


@app.get("/whoami")
def whoami(request: Request):
    return JSONResponse({"email": request.headers.get(IDENTITY_HEADER, "-")})
