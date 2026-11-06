"""JY-266 Collections pages (spec docs/specs/JY-266-collections.md).

P2: the franchise page `GET /media/collections/{col_id}`: the collection's banner, then its films in release order -
owned in colour (the title page), missing dimmed with Request (the normal confirm step in the card, the existing
request path: the household's own goes straight through, a friend's is pending for B.'s approval); a part already
requested reads its word instead. Reads media.db only; a collection not stored yet (the monthly pass has not reached
it) falls back to the title page's cached Seerr read. On the TV (Q4 A) the owned films only, read-only.
A friend (media front) sees it through their scrubbed library: owned = what they can see.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from hub import media_collections as mc, media_front, media_home, shell
from hub import media_watchlist_db as wl
from hub.ids import JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID

log = logging.getLogger("hub.media_collections_pages")
router = APIRouter()

PAGE = "/media/collections"


def owned_of(request: Request) -> set[str]:
    """The viewer's owned film keys: the jellyfin snapshot's movie library as this view sees it."""
    view, _ = shell.resolve_owner_view(request)
    src = shell.find_detail_source(JELLYFIN_SNAPSHOT_ID, shell.get_snapshots(request=request))
    if src is None:
        return set()
    return mc.owned_keys(media_home.view_jelly(src["data"], view))


def _fallback(col_id: int, owned: set[str]) -> dict | None:
    """A collection the pass has not stored yet: the title page's cached Seerr read (warm when its banner link was
    followed); None when Seerr has nothing."""
    from hub import media_film
    body = media_film._cget(f"/api/v1/collection/{col_id}")
    if not isinstance(body, dict) or not mc.parts_of(body):
        return None
    from hub import media_discover as md
    row = {"id": col_id, "name": str(body.get("name") or "Collection")[:mc.NAME_MAX],
           "poster": md._ref(body.get("posterPath")), "backdrop": md._ref(body.get("backdropPath")),
           "parts_json": json.dumps(mc.parts_of(body))}
    return mc.summary(row, owned)


def _words() -> dict:
    from hub.media_requests import snapshot_rows   # late, as media_watchlist
    return wl.request_words(snapshot_rows(shell.get_snapshots(), JELLYSEERR_SNAPSHOT_ID))


def franchise_ctx(col: dict, tv: bool, words: dict) -> dict:
    parts = []
    for p in col["parts"]:
        if tv and not p["on"]:
            continue
        word = None if p["on"] else words.get(("movie", p["id"]))
        parts.append({**p, "word": word, "can_request": not tv and not p["on"] and word is None})
    line = [col["count_line"], col["on_line"]]
    return {"col": col, "parts": parts, "line": line}


@router.get(PAGE + "/{col_id}", response_class=HTMLResponse)
def franchise_page(request: Request, col_id: int):
    if not 0 < col_id < 10 ** 9:
        return shell.not_found_page(request)
    request.state.media_section = "movies"
    owned = owned_of(request)
    col = mc.one(col_id, owned) or _fallback(col_id, owned)
    if col is None:
        return shell.not_found_page(request, "No collection here")
    ctx = franchise_ctx(col, media_front.tv_mode(request), _words())
    return shell.render_page(request, "media_collection.html", ctx)
