"""The Media detail pages behind registry `detail` tiles (W3 split of hub/main.py, H-44): /media/apps, /playing,
/downloads, /library, /requests, /history, /diary, /movies and /tv (grid / list,
Tonight, To rate). `_detail_page` is their one frame: 404 when no tile reads the snapshot, 'Not connected' when it has
no data. The Watchlist and Awards pages render through it too.
"""

from __future__ import annotations

import os
import random
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from hub import guest   # Joey TV WP-B3: the diary's owner switch is private-front only
from hub import (media_awards_badges, media_backup, media_db, media_downloads, media_home, media_item, media_library,
                 media_plays_db, media_quality, media_requests, media_resume, media_season_state, media_upgrade_why, media_upgrades, media_wrapped, media_write,
                 server, shell, upcoming)
from hub.ids import ARR_SNAPSHOT_ID, JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID, MEDIA_STATUS_SNAPSHOT_ID, QBIT_SNAPSHOT_ID

router = APIRouter()

DIARY_PAGE = 50
MILESTONES_MAX = 5

# E1 (2026-10-13): every Diary visit used to write (the history sync: INSERT OR IGNORE + commit) and then load every
# diary row for the stats. The sync now runs only when the jellyfin snapshot moved since the last one for that owner
# and file; the stats are kept per (owner, file, snapshot, today, diary row count + newest id) - diary rows are only
# ever inserted, so a new row is a new key.
_diary_synced: dict = {}   # (db path, owner) -> the jellyfin updated_at last synced
_diary_stats: dict = {}    # (db path, owner) -> (key, stats)


def clear_diary_memo() -> None:
    _diary_synced.clear()
    _diary_stats.clear()


def _diary_sync_and_stats(recent, owner: str, stamp) -> dict:
    where = (str(media_db.db_path()), owner)
    if stamp is None or _diary_synced.get(where) != stamp:
        media_db.sync_diary_from_history(recent, owner)
        if stamp is not None:
            _diary_synced[where] = stamp
    key = (stamp, date.today().isoformat(), media_db.diary_signature(owner))
    kept = _diary_stats.get(where)
    if kept is not None and kept[0] == key:
        return kept[1]
    stats = media_db.diary_stats(owner=owner)
    if len(_diary_stats) > 16:
        _diary_stats.clear()
    _diary_stats[where] = (key, stats)
    return stats


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


def app_link(request: Request, app_id: str) -> dict | None:
    """WP-L1 (2026-10-21): the Health row's card for one app (`server.service_card`: logo, gated hostname else the
    snapshot's address with `lan`), read from the media_status snapshot - None when that snapshot or the app is absent."""
    snap = shell.get_snapshots(request=request).get(MEDIA_STATUS_SNAPSHOT_ID)
    app = next((a for a in ((snap.data if snap else None) or {}).get("apps") or [] if a.get("id") == app_id), None)
    if app is None:
        return None
    return server.service_card(app, [], shell.registry.gated_hrefs if shell.registry else {})


@router.get("/media/apps", response_class=HTMLResponse)
def media_apps_page(request: Request):
    # 2026-10-19 (WP-H1): each row takes the Server card's logo / initial and gated hostname (one `service_card`).
    gated = shell.registry.gated_hrefs if shell.registry else {}
    return _detail_page(request, "media_apps.html", MEDIA_STATUS_SNAPSHOT_ID, always_build=True,
                        build=lambda data, view: {"backup": media_backup.current_status(),
                                                  "health_apps": [server.service_card(a, [], gated)
                                                                  for a in data.get("apps", [])]})


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
    index = {k: media_library.library_index(lists[k]) for k in lists}   # E1: once per request, not once per row

    def link(rows, need_key=False):
        return [{**r, "href": None} if need_key and not r.get("item_key") else
                media_library.link_arrivals([r], None, k, lambda jf: media_home.item_href(jf), index[k])[0]
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
        # F4b: the "Upgrades" block - the arr snapshot's cutoff-unmet titles, each row linked like the rows above
        snaps = shell.get_snapshots(request=request)
        upgrades = media_upgrades.block(snaps)
        why = {}
        if upgrades and upgrades.get("rows"):
            upgrades["rows"] = [{**r, "why_key": ("radarr:" if r.get("kind") == "movie" else "sonarr:") + str(r.get("arr_id"))}
                                for r in link(upgrades["rows"])]
            # WP-U1: each row's "Why?" (the kept answer only for the row ?why= names - never a call)
            why = media_upgrade_why.page_ctx(request.query_params, upgrades["rows"])
        return {"groups": [g for g in groups if g["rows"]], "upgrades": upgrades, "why": why,
                "last_search": media_upgrades.last_search(snaps),
                "app_link": app_link(request, "qbittorrent"),
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
        # F4b: "Below cutoff" on a request whose title is on the arr cutoff-unmet lists (copies: the counts above
        # match rows by identity, and the snapshot's own dicts stay untouched)
        rows = [dict(r) for r in rows]
        media_upgrades.attach(rows, shell.get_snapshots(request=request), None, lambda r: r.get("tvdb_id"))
        tv = [r for r in rows if r.get("kind") == "tv"]
        for r in tv:   # WP-T1: Sonarr's words (cache only; the read runs after the response)
            request_words(r, media_season_state.season_states(r.get("tvdb_id"), r.get("tmdb_id")))
        # WP-R1: a "4K" chip on a row whose arr entry is not on the default profile - caches only, the reads after
        later[0] = media_season_state.chain(media_season_state.later([(r.get("tvdb_id"), r.get("tmdb_id")) for r in tv]),
                                            media_quality.later(rows))
        media_quality.attach(rows)
        good, warn = media_requests.flash_text(request.query_params)
        return {"counts_text": " · ".join(f"{c.get(k, 0)} {k}"
                                          for k in ("pending", "approved", "available", "declined")),
                "rows": rows, "flash": good, "flash_warn": warn, "app_link": app_link(request, "jellyseerr"),
                "ratings": media_home._ratings(view, rows)}
    later = [None]
    resp = _detail_page(request, "media_requests.html", JELLYSEERR_SNAPSHOT_ID, build)
    if later[0] is not None:
        resp.background = BackgroundTask(later[0])
    return resp


def request_words(row: dict, state: dict | None) -> None:
    """WP-T1 (2026-10-19): a TV request row's Sonarr words, in place. A show Sonarr holds no file of reads "Requested"
    (even when Seerr says Available - nothing is on disk) with "Waiting for the first episode · airs 5 Dec" beside it;
    a partly downloaded one keeps Seerr's word and gains "3 of 8 episodes · 5 to come · next airs 2 Nov". Without a
    state (Sonarr not connected / not read yet / not there) the row is unchanged."""
    if not state or not state.get("word"):
        return
    if media_season_state.waiting(state):
        if row.get("status_text") not in ("Pending", "Declined", "Failed"):
            row["status_text"] = "Requested"
        row["state_word"] = state["word"]
    elif state.get("to_come") or state.get("missing"):
        row["state_word"] = " · ".join(x for x in (media_season_state.episodes_words(state, ""), state["word"]) if x)


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
            "skipped": media_db.skips(ratings.owner),   # E5 (M3): the Skipped group, Unskip each
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
        jsnap = shell.get_snapshots(request=request).get(JELLYFIN_SNAPSHOT_ID)
        stats = _diary_sync_and_stats(history.get("recent"), owner, jsnap.updated_at if jsnap else None)
        # Diary scope (2026-10-13): only owner "you" may list everyone's rows (like Jellyfin's admin); each row then
        # names whose it is in words. Stats, streak and "Log a watch" stay the viewer's own.
        scope = media_db.diary_scope(owner)
        everyone = scope == "everyone"
        rows = media_db.list_diary(DIARY_PAGE + 1, offset, kind, None if everyone else owner)
        more = len(rows) > DIARY_PAGE
        rows = rows[:DIARY_PAGE]
        months: list[dict] = []
        lines = media_db.group_diary(rows)
        her_name = os.environ.get("OWNER_NAME_HER") or "Georgina"
        for row in lines:
            if everyone:
                row["who"] = "You" if row.get("owner") == owner else her_name
                row["theirs"] = row.get("owner") != owner   # 2026-10-13: no 1-10 picker / score on her rows
            label = date.fromisoformat(row["watched_on"]).strftime("%B %Y")
            if not months or months[-1]["label"] != label:
                months.append({"label": label, "rows": []})
            months[-1]["rows"].append(row)
        on_this_day = _group_on_this_day(history.get("on_this_day", []))
        streak = stats["streak_days"]
        # E6 (M1): the Month in Review card, read after the sync above so it counts today's history
        raw = jsnap.data if jsnap else {}
        month = media_wrapped.month_card(view, raw, jsnap.updated_at if jsnap else None)
        return {
            "month": month,
            "stats_text": " · ".join([
                f"{stats['this_week']} this week", f"{stats['this_month']} this month",
                f"{stats['total']} all time",
                f"{stats['year_films']} film{'' if stats['year_films'] == 1 else 's'} · "
                f"{stats['year_episodes']} episode{'' if stats['year_episodes'] == 1 else 's'} this year",
                f"{streak}-day streak" if streak else "no current streak"]),
            "milestones": stats["milestones"][:MILESTONES_MAX],
            "months": months, "kind": kind or "", "today": date.today().isoformat(), "places": media_write.PLACES,
            "on_this_day": on_this_day, "scope_eligible": owner == "you" and not guest.is_media(), "diary_scope": scope,
            "older": (f"/media/diary?offset={offset + DIARY_PAGE}" + (f"&kind={kind}" if kind else ""))
                     if more else None,
            "ratings": media_home._ratings(view, lines, on_this_day),
        }
    return _detail_page(request, "media_diary.html", JELLYFIN_SNAPSHOT_ID, build,
                        detail=media_home.DIARY_DETAIL, always_build=True)


WRAPPED_YEARS = (1900, 2100)


@router.get("/media/diary/year", response_class=HTMLResponse)
def media_wrapped_now(request: Request):
    """Wrapped without a year (no tab since nav-tidy): this home-time year's Wrapped."""
    return RedirectResponse(f"/media/diary/year/{media_wrapped._now().year}", status_code=307)


@router.get("/media/diary/year/{year}", response_class=HTMLResponse)
def media_wrapped_page(request: Request, year: str):
    """Wrapped (E6, 2026-10-13; review_features M1): one year in words — Numbers, Top rated, Most watched shows, Firsts
    and lasts, Rewatches, Award winners you saw and where the numbers come from. A summary, never a ranking UI."""
    if not year.isdigit() or not WRAPPED_YEARS[0] <= int(year) <= WRAPPED_YEARS[1]:
        return shell.not_found_page(request)
    y = int(year)

    def build(data, view):
        history = data.get("history") or {}
        jsnap = shell.get_snapshots(request=request).get(JELLYFIN_SNAPSHOT_ID)
        stamp = jsnap.updated_at if jsnap else None
        _diary_sync_and_stats(history.get("recent"), media_db.owner_of(view), stamp)   # the year counts today's history
        w = media_wrapped.summary(view, jsnap.data if jsnap else {}, y, None, stamp)
        return {"w": w, "year": y, "step": media_wrapped.stepper(view, y)}
    return _detail_page(request, "media_wrapped.html", JELLYFIN_SNAPSHOT_ID, build,
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


def _all_lists(data: dict, view: str, kind: str):
    field = "movies" if kind == "movie" else "shows"
    if view == "her":
        mine = (data.get("her") or {}).get(field)
        if mine is not None:
            return mine, True
        return data.get(field), False
    return data.get(field), True


def _library_lists(data: dict, view: str, kind: str):
    """(items | None, marks): her view reads her own list; without it the shared list has no marks. WP-T1 (2026-10-19):
    a show with no episode yet (Sonarr's empty folder, media_library.empty_series) is not a library entry - it is left
    out here, so the grids, the counts, the Activity links and the awards matches never treat it as one."""
    items, marks = _all_lists(data, view, kind)
    return (None if items is None else [i for i in items if not media_library.empty_series(i)]), marks


def _show_keys(row: dict) -> tuple:
    """(tvdb, tmdb) for a library show row: its item_key, plus the TheTVDB id its page has cached (no read)."""
    key = str(row.get("item_key") or "")
    tvdb = key[5:] if key.startswith("tvdb:") else _cached_tvdb(row)
    return tvdb, key[5:] if key.startswith("tmdb:") else None


def waiting_shows(data: dict, view: str) -> list[dict]:
    """WP-T1: the shows Jellyfin lists with no episode yet, as rows for My shows' "Waiting for the first episode"
    block: "Requested · waiting for the first episode · airs 5 Dec" (Sonarr's cached state; "date TBA" without a date,
    the bare words without Sonarr)."""
    items, _marks = _all_lists(data, view, "tv")
    out = []
    for it in items or []:
        if not media_library.empty_series(it):
            continue
        st = media_season_state.season_states(*_show_keys(it))
        word = (st or {}).get("word") or ""
        out.append({"title": it.get("title") or "Untitled", "year": it.get("year"), "poster": it.get("poster"),
                    "href": media_home.item_href(it.get("jf_id")), "keys": _show_keys(it),
                    "word": "Requested · " + (media_season_state.waiting_words(st)
                                              if not word or word.startswith("Waiting") else word)})
    return out


def _library_rows(data: dict, view: str, kind: str):
    """(items | None, marks, rows | None) for the view's owner."""
    now = datetime.now(timezone.utc)
    items, marks = _library_lists(data, view, kind)
    if items is None:
        return None, marks, None
    ratings, ago = media_home._ratings(view, items), lambda v: media_home._ago_text(v, now)
    if kind == "movie":
        return items, marks, media_library.film_rows(items, ratings, ago, _lib_href(), marks)
    runtimes = media_plays_db.show_runtimes(f"jf:{i.get('jf_id')}" for i in items if i.get("jf_id")) if marks else {}
    return items, marks, media_library.show_rows(items, ratings, ago, _lib_href(), marks, runtimes)   # E5 (M2)


def _cached_tvdb(row: dict):
    """A show row's TheTVDB id from the item data its page last read (media_item.peek - never a Jellyfin read)."""
    return ((media_item.peek(row.get("jf_id")) or {}).get("item") or {}).get("tvdb") if row.get("jf_id") else None


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
    """{grid: href, list: href} — this page with the same search / sort / filter and the other layout."""
    return _links_with(request, "view", LIBVIEWS)


def _links_with(request: Request, name: str, values, drop=None) -> dict:
    """{value: href} — this page with every other query param kept and `name` set to each value (`drop`: omitted)."""
    keep = [(k, v) for k, v in request.query_params.multi_items() if k != name]
    return {v: request.url.path + ("?" + urlencode(keep + ([] if v == drop else [(name, v)]))
                                   if keep or v != drop else "") for v in values}


# Suggestions carousel (2026-10-13, B.): New · Continue watching · Not yet watched; `?s=` wins and is remembered in a
# cookie scoped to /media like the Grid / List choice, else the cookie, else New.
SUGGEST_COOKIE = "media_libsugg"


def library_suggest(request: Request) -> tuple[str, bool]:
    q = request.query_params.get("s")
    if q in media_library.SUGGESTIONS:
        return q, True
    c = request.cookies.get(SUGGEST_COOKIE)
    return (c if c in media_library.SUGGESTIONS else "new"), False


def _library_page(request: Request, kind: str):
    template = "media_movies.html" if kind == "movie" else "media_tv.html"
    libview, view_from_query = library_view(request)
    suggest, suggest_from_query = library_suggest(request)

    def build(data, view):
        items, marks, rows = _library_rows(data, view, kind)
        waiting = []
        if kind == "tv":   # WP-T1: Sonarr's words from its cache; the reads run after the response
            media_library.apply_season_state(rows, lambda r: media_season_state.season_states(*_show_keys(r)))
            waiting = waiting_shows(data, view)
            later[0] = media_season_state.later([_show_keys(r) for r in rows or []] + [w["keys"] for w in waiting])
        # media-ux4: each grid card says Watched / Not watched / In progress (a film is in progress while it sits in the
        # viewer's resume list). 2026-10-13: the list keeps its order (Jellyfin's most recently played first) for
        # the Continue watching suggestions.
        resume_rows = [r for r in data.get("up_next") or [] if media_resume.in_progress(r) and r.get("jf_id")]
        resume = {str(r["jf_id"]) for r in resume_rows}
        for r in rows or []:
            r["card_state"] = media_library.card_state(r, resume)
        media_awards_badges.attach(rows, kind)   # awards-ui item 3: one query for every poster on the page
        # F4b: "Below cutoff" under the title - the arr snapshot's cutoff-unmet lists; a show also by the TheTVDB id
        # its page has cached (media_item.peek, no read), else its unique title
        media_upgrades.attach(rows, shell.get_snapshots(request=request), kind, _cached_tvdb)
        arr = shell.get_snapshots(request=request).get(ARR_SNAPSHOT_ID)
        arrived = media_library.arrived_this_week((arr.data if arr else {}).get("arrived"), kind)
        arrived = media_library.link_arrivals(arrived, items, kind, lambda jf: media_home.item_href(jf))
        q = request.query_params.get("q", "")
        sorts = media_library.sort_labels(kind)
        sort = request.query_params.get("sort", "score")
        sort = sort if sort in sorts else "score"
        # 2026-10-13 (B.): one flat grid narrowed by a filter chip (the Grouped chip is gone; an old `group=` is ignored)
        filters = media_library.FILTERS[kind]
        f = request.query_params.get("f", "all")
        f = f if marks and f in filters else "all"
        shown = media_library.arrange(rows or [], q, sort, f, kind, resume)
        suggested = arrived if suggest == "new" else media_library.suggestions(rows or [], kind, suggest, resume_rows, marks)
        return {
            "kind": kind, "marks": marks, "rows": rows, "q": q, "sort": sort, "sorts": sorts,
            "head_line": media_library.head_line(rows or [], kind, marks),
            "filters": filters, "filter": f, "filter_links": _links_with(request, "f", filters, drop="all"),
            "shown": shown,
            "suggest": suggest, "suggestions": media_library.SUGGESTIONS, "suggested": suggested,
            "suggest_links": _links_with(request, "s", media_library.SUGGESTIONS),
            "suggest_empty": media_library.SUGGESTION_EMPTY[suggest],
            "ratings": media_home._ratings(view, arrived),
            "libview": libview, "libview_links": library_view_links(request), "waiting": waiting,
        }
    later = [None]
    resp = _detail_page(request, template, JELLYFIN_SNAPSHOT_ID, build)
    if later[0] is not None:
        resp.background = BackgroundTask(later[0])
    if view_from_query:
        resp.set_cookie(LIBVIEW_COOKIE, libview, max_age=LIBVIEW_MAX_AGE, samesite="lax", path="/media")
    if suggest_from_query:
        resp.set_cookie(SUGGEST_COOKIE, suggest, max_age=LIBVIEW_MAX_AGE, samesite="lax", path="/media")
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
        skipped = [s for s in media_db.skips(media_db.owner_of(view)) if s["kind"] == kind]   # E5 (M3)
        return {"kind": kind, "to_rate": rows, "skipped": skipped}
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
