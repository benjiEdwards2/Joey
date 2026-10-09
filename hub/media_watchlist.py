"""Watchlist routes + pages (F6, 2026-10-06): add/remove a title, and the Movies / TV Shows
Watchlist pages. Storage and pure helpers live in hub/media_watchlist_db.py. Status is a WORD
(On disk / Requested / Processing / Partly available / Not on server); a title B. has watched
leaves the list by itself when the page renders."""
from __future__ import annotations

import logging
import re
import sqlite3
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import media_db, media_watchlist_db as wl
from hub.media_write import bad, clean_item, form_of, is_htmx, owner_for, same_origin
from hub.shell import templates  # the ONE shared Jinja env (M-23 / H-31)

log = logging.getLogger("hub.media_watchlist")
router = APIRouter()

PAGES = {"movie": "/media/movies/watchlist", "tv": "/media/tv/watchlist"}
FIELD = {"movie": "movies", "tv": "shows"}


def keys_for(request: Request, keys) -> set:
    """Watchlist keys among `keys` for the requester's owner; never raises (empty on a DB problem)."""
    try:
        return wl.contains(owner_for(request), keys)
    except (sqlite3.Error, OSError) as exc:
        log.warning("watchlist read skipped: %s", type(exc).__name__)
        return set()


def on_server_keys(jelly: dict, kind: str) -> set:
    return {i.get("item_key") for i in (jelly or {}).get(FIELD[kind]) or [] if i.get("item_key")}


def tab_counts(owner: str, jelly: dict | None) -> dict:
    """{'wl_movie': n, 'wl_tv': n} not-on-server counts for the nav tabs; {} with no library data."""
    if not jelly:
        return {}
    return {f"wl_{k}": wl.count_not_on_server(owner, k, on_server_keys(jelly, k)) for k in PAGES}


def _item(f: dict) -> dict:
    tmdb = f.get("tmdb_id", "")
    if not re.fullmatch(r"\d{1,9}", tmdb):
        raise bad("Invalid item")
    item = clean_item({**f, "item_key": f"tmdb:{tmdb}"})
    return {**item, "tmdb_id": int(tmdb)}


def _button(request: Request, item: dict, on: bool, compact: bool):
    return templates.TemplateResponse(request, "_watchlist_btn.html", {"w": item, "on": on, "compact": compact})


def _back(request: Request, kind: str) -> RedirectResponse:
    ref = urlparse(request.headers.get("referer") or "")
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")} - {None}
    if ref.netloc in hosts and ref.path.startswith("/"):
        return RedirectResponse(ref.path + (f"?{ref.query}" if ref.query else ""), status_code=303)
    return RedirectResponse(PAGES[kind], status_code=303)


async def _write(request: Request, adding: bool):
    """The form is read on the event loop; the SQLite write and the render run in a worker thread (M-40)."""
    return await run_in_threadpool(_apply, request, adding, await form_of(request))


def _apply(request: Request, adding: bool, f: dict):
    item = _item(f)
    owner = owner_for(request)
    try:
        if adding:
            wl.add(owner, item)
        else:
            wl.remove(owner, item["item_key"])
    except (sqlite3.Error, OSError) as exc:
        log.warning("watchlist not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the watchlist") from None
    if is_htmx(request):
        return _button(request, item, adding, f.get("compact") == "1")
    return _back(request, item["kind"])


@router.post("/media/watchlist/add", dependencies=[Depends(same_origin)])
async def watchlist_add(request: Request):
    return await _write(request, True)


@router.post("/media/watchlist/remove", dependencies=[Depends(same_origin)])
async def watchlist_remove(request: Request):
    return await _write(request, False)


def _page(request: Request, kind: str):
    from hub import main as hub  # late: hub.main includes this router

    def build(data, view):
        owner = media_db.owner_of(view)
        left = 0
        try:
            _items, marks, lrows = hub._library_rows(data, view, kind)
            if marks and lrows:
                played = {r["item_key"] for r in lrows
                          if r["played"] and r["item_key"] and (kind == "movie" or r["episodes"])}
                left = wl.prune_played(owner, played, kind)
            rows, failed = wl.list(owner, kind), False
        except (sqlite3.Error, OSError) as exc:
            log.warning("watchlist read failed: %s", type(exc).__name__)
            rows, failed = [], True
        on_keys = on_server_keys(data, kind)
        from hub.media_requests import snapshot_rows  # a removed request stops showing at once (2026-10-08)
        words = wl.request_words(snapshot_rows(hub.get_snapshots(), hub.JELLYSEERR_SNAPSHOT_ID))
        sort = request.query_params.get("sort", "added")
        sort = sort if sort in wl.SORTS else "added"
        rows = [{**r, "status_word": wl.status_word(r, on_keys, words),
                 "href": f"/media/title/{kind}/{r['tmdb_id']}"} for r in wl.sort_rows(rows, sort, owner, kind)]
        missing = sum(1 for r in rows if r["status_word"] != wl.ON_DISK)
        return {"kind": kind, "rows": rows, "sort": sort, "sorts": wl.SORT_LABELS, "left": left,
                "failed": failed, "page_href": PAGES[kind],
                "head_line": f"{len(rows)} on your watchlist · {missing} not on the server"}

    return hub._detail_page(request, "media_watchlist.html", hub.JELLYFIN_SNAPSHOT_ID, build, always_build=True)


@router.get("/media/movies/watchlist", response_class=HTMLResponse)
def movies_watchlist(request: Request):
    return _page(request, "movie")


@router.get("/media/tv/watchlist", response_class=HTMLResponse)
def tv_watchlist(request: Request):
    return _page(request, "tv")
