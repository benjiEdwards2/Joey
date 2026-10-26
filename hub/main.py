"""Joey hub — FastAPI skeleton. Every route and the tab bar render from
areas.yaml; no area name appears in this code (WP17 verify greps for that).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask, BackgroundTasks

from hub import access_jwt, guest, guest_signin, media_backup
from hub import media_front, media_guest_home   # Joey TV WP-B3: the guest surface
from hub.images import router as images_router
from hub.media_discover import router as media_discover_router
from hub import media_film, media_person, media_plays
from hub import media_write as _media_write
from hub.media_write import router as media_write_router
from hub import media_arr_search, media_follow, media_quality, media_requests, media_resume, media_upgrade_why
from hub import media_requests_approve   # WP-RQ1: Approve / Decline on the Requests page
from hub import media_awards_pages
from hub import server as server_area
from hub import server_alerts, server_history, server_stack, server_updates, server_uptime, server_visits
from hub import server_quiet   # P4 quiet mode (2026-10-22)
from hub import server_digest  # P2 (2026-10-22)
from hub import player_api   # JY-053: playback-session API, off unless PLAYER_API=on
from hub import media_watch   # JY-054: the web / phone player page, off unless PLAYER_API=on
from hub import server_space   # P1a free space (2026-10-22)
from hub.media_watchlist import router as media_watchlist_router
from hub import media_watchlist_everyone
from hub import media_home, media_pages, media_season_state, shell, tasks, today, tv_app, weather
# W3: the Media detail pages live in hub/media_pages.py; re-exported for the old `hub.main.X` paths.
from hub.media_pages import (  # noqa: F401
    DIARY_PAGE, LIBVIEWS, LIBVIEW_COOKIE, LIBVIEW_MAX_AGE, MILESTONES_MAX, _arr_linker, _detail_page,
    _group_on_this_day, _lib_href, _library_lists, _library_page, _library_rows, _qb_data, _to_rate_page,
    _tonight_page, library_view, library_view_links, media_apps_page, media_diary_page,
    media_downloads_page, media_history_page, media_library_page, media_movies_page, media_movies_to_rate_page,
    media_movies_tonight_page, media_playing_page, media_requests_page, media_tv_page, media_tv_to_rate_page,
    media_tv_tonight_page,
)
# W3: the shared Media helpers live in hub/media_home.py; re-exported for the old `hub.main.X` paths.
from hub.media_home import (  # noqa: F401
    DIARY_DETAIL, HISTORY_DETAIL, HISTORY_PLAYS, LEVEL_KEYS, LIBRARY_DETAIL,
    PLAYING_DETAIL, Ratings, SHELF_MAX, TO_RATE_DAYS, _ago_text, _library_text,
    _parse_ts, _profile_rows, _ratings, _recent, _split_title, _to_rate, _to_rate_title, area_waiting,
    build_shelves, hub_shelf, item_href, media_frame, media_hero, resume_acts, row_href, score_for,
    to_rate_tab_counts, view_jelly, waiting_counts,
)
# W3: the calendar helpers live in hub/upcoming.py; re-exported for the old `hub.main.X` paths.
from hub.upcoming import (UPCOMING_DAYS, _day_label, _event_dt, build_upcoming, find_upcoming,  # noqa: F401
                          hub_upcoming, per_day_counts)
# W3: the weather helpers and routes live in hub/weather.py; re-exported for the old `hub.main.X` paths.
from hub.weather import (WINDY_DEFAULT, WINDY_EMBED,  # noqa: F401
                         WINDY_ZOOM, WX_CHART_H, WX_CHART_PAD, WX_CHART_W, WX_LABEL_EVERY, WX_RAIN_BASE, WX_RAIN_MAX_H,
                         WX_TEMP_BOTTOM, WX_TEMP_TOP, _wx_chart,
                         _wx_day_label, _wx_num, _wx_uv_word, find_weather, weather_forecast, weather_glyph,
                         weather_page, windy_embed_url)
# W3: background loops + lifespan live in hub/tasks.py; re-exported for the old `hub.main.X` paths.
from hub.tasks import (BACKUP_EVERY_S, BACKUP_FIRST_DELAY_S, _backup_loop, _every, _media_awards_loop,  # noqa: F401
                       _media_follow_loop, _media_warmup_loop, _server_alerts_loop, _server_tick, lifespan)
from hub.identity import IDENTITY_HEADER
from hub.ids import GCAL_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, QBIT_SNAPSHOT_ID, WEATHER_SNAPSHOT_ID
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


# Guest front gate (Joey TV WP-B1): the FIRST add_middleware call = the innermost layer (Starlette makes the last-added
# outermost), so the request line below logs its 404 / 303 and sees the identity it stored. JOEY_FRONT=media
# (joey-media): deny-by-default route allow-list (hub/guest.py); the private front: the media-host guard only (Q25a).
app.add_middleware(guest.GuestGate)
# Cloudflare Access JWT gate (Joey TV WP-A6a, Q25b): second = innermost but one, so the request line below still logs
# its 401. Private front only (the media front passes straight through). Off unless ACCESS_JWT_VERIFY is set; a flag
# without ACCESS_AUD stops the import here.
app.add_middleware(access_jwt.AccessGate)
access_jwt.check_config()

# Request log + Cache-Control (pages no-store, /static/ immutable when ?v= versioned, else an hour) in one pure
# ASGI layer; text bodies gzipped (hub/shell.py).
app.add_middleware(ShellMiddleware)
app.add_middleware(Compress)


# Query params that only carry a one-off flash line after a POST's 303 (2026-10-08). base.html strips them from
# the address bar after render (history.replaceState), so Back / Forward / reload never re-show the flash. Derived
# from the Media modules' registry (media_write.flash_keys, M-17) plus the Server page's own (server_updates).
SERVER_FLASH_PARAMS = ("flash", "c", "code", "n", "m", "u", "stack")   # n / m / u: Update all; stack: stackctl
FLASH_PARAMS = tuple(dict.fromkeys([*_media_write.FLASH_KEYS, *SERVER_FLASH_PARAMS]))
templates.env.globals["flash_params"] = FLASH_PARAMS

app.include_router(images_router)
app.include_router(media_write_router)
app.include_router(media_discover_router)
app.include_router(media_plays.router)
app.include_router(media_film.router)
app.include_router(media_person.router)
app.include_router(media_watchlist_router)
app.include_router(media_watchlist_everyone.router)   # WP-RQ3: Everyone's watchlist (owner you)
app.include_router(media_follow.router)
app.include_router(media_awards_pages.router)
app.include_router(media_requests.router)
app.include_router(media_requests_approve.router)   # WP-RQ1: Approve / Decline a pending request
app.include_router(media_resume.router)
app.include_router(media_arr_search.router)   # media-ux5: Search now
app.include_router(media_quality.router)   # WP-R1: Quality · 1080p / Switch to 4K
app.include_router(media_upgrade_why.router)   # WP-U1: Why? + Grab anyway on Downloads › Upgrades
app.include_router(server_updates.router)
app.include_router(server_stack.router)   # 2026-10-12: Restart + update media stack
app.include_router(server_quiet.router)   # P4 (2026-10-22): Downloads Quiet (5 Mbps) / Full speed
app.include_router(server_space.router)   # P1a free space (2026-10-22): list only
app.include_router(weather.router)
app.include_router(media_pages.router)
app.include_router(tv_app.router)   # Joey TV WP-B8: /app download + version.json (media front only)
app.include_router(guest_signin.router)   # Joey TV WP-B2: the media front's sign-in (404 on the private front)
app.include_router(player_api.router)   # JY-053: /api/play/* (docs/playback-contract.md), 404 while PLAYER_API is off
app.include_router(media_watch.router)   # JY-054: /media/watch/<item>, 404 while PLAYER_API is off
# JY-054 verifier: with PLAYER_API off, ANY method under /api/play and /media/watch is the unknown-path 404 (no 405 /
# Allow); first in the router so it answers before the method-filtered routes, and never matches while the flag is on.
app.router.routes[0:0] = player_api.flag_off_routes(player_api.PREFIX, media_watch.PREFIX)
app.mount("/static", StaticFiles(directory=str(HUB_DIR / "static")), name="static")


def hub_greeting(now: datetime, name: str | None = None) -> str:
    """The hub page's H1 (E3, U3, 2026-10-13): "Good evening, Benji" — a short phrase, so no full stop (guide §9);
    the date is the sub-line ("Mon 13 Oct", hub_page)."""
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    return f"Good {part}, {name}" if name else f"Good {part}"


# The hub page would otherwise pay for the Server page on every load (H-49): the runner history tail (up to
# 2 MB of JSON lines), the ignores table and the sweep stats. The card is kept 60 s while the snapshots and the
# backup word are unchanged; the /server page itself is never cached.
HUB_CARD_TTL_S = 60
_hub_card_cache: tuple | None = None   # (monotonic time, key, card)


def _server_hub_card(snaps, backup: dict) -> dict:
    global _hub_card_cache
    forecast = server_history.forecast_peek()   # JY-031: the hub loop's cached disk forecast; no media.db read here
    key = (tuple(sorted((cid, s.updated_at, s.status) for cid, s in snaps.items())), backup.get("warning"),
           forecast and forecast["text"])
    now = time.monotonic()
    hit = _hub_card_cache
    if hit and hit[1] == key and now - hit[0] < HUB_CARD_TTL_S:
        return hit[2]
    card = server_area.hub_card(snaps, server_updates.get_ignores(), backup, get_runner(), get_runner_history(),
                                live=server_area.live_snapshot_ids(shell.registry),  # WP-U3
                                forecast=forecast)
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
    cards, shelf, server_card = [], None, None
    upcoming = hub_upcoming(snaps, view)
    now = shell._now_home()
    wx = weather.find_weather(snaps, now)
    for a in shell.registry.visible_areas:
        summary = next(t for t in a.tiles if t.id == a.summary_tile)
        if not shell.owner_visible(summary, view):
            continue  # hub summary cards respect the filter (Q24 assumption)
        card = {"area": a, "tile": summary, "st": tile_state(summary, snaps), "hero": None,
                "per_day": None}
        if summary.snapshot == GCAL_SNAPSHOT_ID and upcoming:  # keyed by connector id, never area name
            card["per_day"] = upcoming["per_day"]
            card["next"] = upcoming["next"]   # E3: the event title is the value, its day / time the meta line
            card["dup"] = True                # E3 (U3): repeats the Next 7 days band below — hidden under 640 px
        if a.layout == server_area.SERVER_LAYOUT and card["st"]["state"] != "off":
            try:
                card["st"] = server_card_state(card["st"], snaps, backup)  # WP-U2: the card's own words
            except Exception as exc:  # a malformed envelope never 500s the hub: the plain tile state stays (H-63)
                log.warning("server hub card skipped: %s", type(exc).__name__)
            server_card = {"name": a.name, "state": card["st"]["state"]}   # E5: the Today line's state word
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
        "status": shell.build_status(snaps), "weather": wx,  # status: hub.html only (H-50)
        "upcoming": upcoming, "shelf": shelf,
        "backup_warn": backup["warning"],
        "greeting": hub_greeting(now, shell.identity_of(request).owner and shell.identity_of(request).name),
        "today": f"{now:%a} {now.day} {now:%b}",   # "Mon 13 Oct" (guide §9: no zero padding)
        "today_line": today.today_line(snaps, upcoming, wx, server_card, view, now),   # E5 (H1): rain · events · new
    })
    return shell._maybe_set_cookie(resp, view, from_query)


def _server_response(request: Request, area, view: str, from_query: bool):
    """The `layout: server` page (WP-S1, 2026-10-06): bands built by hub/server.py."""
    snaps = shell.get_snapshots(request=request)
    samples = server_history.recent()
    forecast, keep = server_alerts.forecast_or_keep(server_history.forecast, samples)   # JY-031: the loop's cache
    requested, history = server_updates.last_requested(), get_runner_history()
    live = server_area.live_snapshot_ids(shell.registry)  # WP-U3
    sv = server_area.build_server(area, snaps, media_backup.current_status(), get_runner(),
                                  server_updates.get_ignores(), requested,
                                  history, samples,
                                  live=live,
                                  gated=shell.registry.gated_hrefs,
                                  forecast=forecast,
                                  uptime=server_uptime.peek())   # JY-133: memory only, summed on the hub loop
    # JY-134 (P8, 2026-10-26): "Since your last visit …" for the signed-in viewer; read here, the visit written after.
    owner = shell.identity_of(request).owner
    since_visit = server_visits.sentence(owner, server_visits.since_for(owner), requested, history, live,
                                         waiting=server_visits.waiting_updates(snaps))
    after = BackgroundTasks()
    after.add_task(server_alerts.sync, sv["attention_items"], keep=keep)  # WP-U2: Discord push after the page
    after.add_task(server_history.sample, snaps)  # WP-U4: system sample after the page
    after.add_task(server_visits.touch, owner)  # JY-134: this view ends the viewer's visit so far
    resp = shell.render_page(request, "server.html", {
        "area": area, "sv": sv, "since_visit": since_visit,
        "flash": server_updates.flash_text(request.query_params) or server_stack.flash_text(request.query_params),
        "stack": server_stack.status(),   # 2026-10-12: stackctl's last run (2 s cap; no env = no call)
        "quiet": server_quiet.page(snaps, request.query_params),   # P4 (2026-10-22): the cap row; no call, the snapshot
        "digest": server_digest.last_sent(),   # P2 (2026-10-22): "Digest · sent 07:31" / None without a webhook
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
    if area.layout == "shelves" and guest.is_media():
        # Joey TV WP-B3: the guest Overview - three shelves, the viewer's own live reads, no household rows, no
        # backup warning; the one-time Set up Jellyfin card until `?setup=done` sets its cookie (Q39)
        resp = shell.render_page(request, "area_shelves.html", {
            "area": area, "sh": media_guest_home.build(request, snaps, view), "backup_warn": None,
            "setup": media_front.setup_card(request, shell.public_jellyfin()),
        }, active_id=area.id)
        if media_front.setup_dismissed_now(request):
            resp.headers.append("set-cookie", media_front.setup_cookie_header())
        return resp
    if area.layout == "shelves":
        sh = media_home.build_shelves(area, tiles, snaps, view)
        resp = shell.render_page(request, "area_shelves.html", {
            "area": area,
            "sh": sh,
            "backup_warn": media_backup.current_status()["warning"],
        }, active_id=area.id)
        later = media_season_state.later(sh["season_keys"])   # JY-114: Sonarr's list re-read after the page, when stale
        if later is not None:
            resp.background = BackgroundTask(later)
        return shell._maybe_set_cookie(resp, view, from_query)
    upcoming = find_upcoming(tiles, snaps, view)
    # Weather renders on the hub and /weather only (2026-10-08, B. — supersedes the
    # Calendar-page card). The registry tile stays: find_weather's config anchor.
    tiles = [r for r in tiles if r["tile"].snapshot != WEATHER_SNAPSHOT_ID]
    resp = shell.render_page(request, "area.html", {
        "area": area, "tiles": tiles,
        "upcoming": upcoming,
    }, active_id=area.id)
    return shell._maybe_set_cookie(resp, view, from_query)


@app.get("/healthz")
def healthz():
    """`front` names the process (private / media); on the media front `home` is the guest home `/a/<shelves id>` -
    the contract the TV shell's BackPolicy reads (D-P18)."""
    out = {
        "status": "ok",
        "areas": len(shell.registry.areas) if shell.registry else 0,
        "registry_loaded_at": shell.registry_loaded_at,
        "front": guest.front(),
    }
    if out["front"] == guest.MEDIA_FRONT:
        out["home"] = guest.home_path()
    return out


@app.get("/whoami")
def whoami(request: Request):
    return JSONResponse({"email": request.headers.get(IDENTITY_HEADER, "-")})
