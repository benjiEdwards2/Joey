"""The Media detail pages behind registry `detail` tiles (W3 split of hub/main.py, H-44): /media/apps, /playing,
/downloads, /library, /requests, /history, /diary, /movies and /tv (grid / list,
Tonight, To rate). `_detail_page` is their one frame: 404 when no tile reads the snapshot, 'Not connected' when it has
no data. The Watchlist and Awards pages render through it too.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from hub import (media_awards_badges, media_backup, media_db, media_downloads, media_home, media_library,
                 media_requests, media_resume, media_write, shell, upcoming)
from hub.ids import ARR_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID, MEDIA_STATUS_SNAPSHOT_ID, QBIT_SNAPSHOT_ID

router = APIRouter()

DIARY_PAGE = 50
MILESTONES_MAX = 5


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


@router.get("/media/apps", response_class=HTMLResponse)
def media_apps_page(request: Request):
    return _detail_page(request, "media_apps.html", MEDIA_STATUS_SNAPSHOT_ID, always_build=True,
                        build=lambda data, view: {"backup": media_backup.current_status()})


@router.get("/media/playing", response_class=HTMLResponse)
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


@router.get("/media/downloads", response_class=HTMLResponse)
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


@router.get("/media/library", response_class=HTMLResponse)
def media_library_page(request: Request):
    def build(data, view):
        today = datetime.now().astimezone().date()
        groups: list[dict] = []
        for row in sorted(data.get("this_week", []), key=lambda r: (r["date"], r["title"])):
            day = date.fromisoformat(row["date"])
            if not groups or groups[-1]["day"] != day:
                groups.append({"day": day, "label": upcoming._day_label(day, today), "rows": []})
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


@router.get("/media/requests", response_class=HTMLResponse)
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


@router.get("/media/history", response_class=HTMLResponse)
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


@router.get("/media/diary", response_class=HTMLResponse)
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
            "months": months, "kind": kind or "", "today": date.today().isoformat(), "places": media_write.PLACES,
            "on_this_day": on_this_day,
            "older": (f"/media/diary?offset={offset + DIARY_PAGE}" + (f"&kind={kind}" if kind else ""))
                     if more else None,
            "ratings": media_home._ratings(view, lines, on_this_day),
        }
    return _detail_page(request, "media_diary.html", JELLYFIN_SNAPSHOT_ID, build,
                        detail=media_home.DIARY_DETAIL, always_build=True)


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


@router.get("/media/movies/to-rate", response_class=HTMLResponse)
def media_movies_to_rate_page(request: Request):
    return _to_rate_page(request, "movie")


@router.get("/media/tv/to-rate", response_class=HTMLResponse)
def media_tv_to_rate_page(request: Request):
    return _to_rate_page(request, "tv")


@router.get("/media/movies", response_class=HTMLResponse)
def media_movies_page(request: Request):
    return _library_page(request, "movie")


@router.get("/media/movies/tonight", response_class=HTMLResponse)
def media_movies_tonight_page(request: Request):
    return _tonight_page(request, "movie")


@router.get("/media/tv", response_class=HTMLResponse)
def media_tv_page(request: Request):
    return _library_page(request, "tv")


@router.get("/media/tv/tonight", response_class=HTMLResponse)
def media_tv_tonight_page(request: Request):
    return _tonight_page(request, "tv")
