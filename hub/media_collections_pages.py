"""JY-266 Collections pages (spec docs/specs/JY-266-collections.md).

P2: the franchise page `GET /media/collections/{col_id}`: the collection's banner, then its films in release order -
owned in colour (the title page), missing dimmed with Request (the normal confirm step in the card, the existing
request path: the household's own goes straight through, a friend's is pending for B.'s approval); a part already
requested reads its word instead. Reads media.db only; a collection not stored yet (the monthly pass has not reached
it) falls back to the title page's cached Seerr read. On the TV (Q4 A) the owned films only, read-only.
A friend (media front) sees it through their scrubbed library: owned = what they can see.

P3: the grid `GET /media/collections` (Movies > Collections): one card per franchise with at least one film on Joey -
a poster stack, the name, "4 films · 2001-2011", a "3 of 4 on Joey" bar (a tick when complete). Filters `f` all /
complete / missing, single-film collections hidden unless `single=1` (Q1 A), sort `s` name (A-Z, default, with the A-Z
jump bar) / size / newest / complete. The owner ("you", private front) gets "Check now" (`POST
/media/collections/refresh`: the monthly pass's manual kick, run after the response). Tables only on render.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from hub import guest, media_collections as mc, media_front, media_home, media_text, shell
from hub import media_watchlist_db as wl
from hub.ids import JELLYFIN_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID
from hub.media_write import flash_keys, owner_for, same_origin

log = logging.getLogger("hub.media_collections_pages")
router = APIRouter()

PAGE = "/media/collections"
REFRESH = PAGE + "/refresh"
FILTERS = {"all": "All", "complete": "Complete", "missing": "Missing some"}
SORTS = {"name": "A-Z", "size": "Size", "newest": "Newest", "complete": "Most complete"}
flash_keys("kicked")


def is_owner(request: Request) -> bool:
    """Owner "you" on the private front: the one who may start a check."""
    return not guest.is_media() and owner_for(request) == "you"


def href(f: str = "all", s: str = "name", single: bool = False) -> str:
    q = {k: v for k, v in (("f", f if f != "all" else ""), ("s", s if s != "name" else ""),
                           ("single", "1" if single else "")) if v}
    return PAGE + (f"?{urlencode(q)}" if q else "")


def letter(name: str) -> str:
    """The A-Z jump bar's letter ("The Matrix Collection" -> M); a digit or symbol -> "#"."""
    words = name.split()
    if len(words) > 1 and words[0].lower() in ("the", "a", "an"):
        name = " ".join(words[1:])
    c = name[:1].upper()
    return c if "A" <= c <= "Z" else "#"


def _by_name(c: dict) -> tuple:
    return (letter(c["name"]) != "#", letter(c["name"]), c["name"].lower(), c["id"])


def sort_cards(cards: list[dict], s: str) -> list[dict]:
    out = sorted(cards, key=_by_name)
    if s == "size":
        out.sort(key=lambda c: -c["n"])
    elif s == "newest":
        out.sort(key=lambda c: c["newest"] or "", reverse=True)
    elif s == "complete":
        out.sort(key=lambda c: (-c["pct"], -c["n"]))
    return out


def grid_ctx(cards: list[dict] | None, f: str, s: str, single: bool, tv: bool) -> dict:
    f = f if f in FILTERS else "all"
    s = s if s in SORTS else "name"
    base = {"f": f, "s": s, "single": single, "filters": FILTERS, "sorts": SORTS,
            "filter_links": {k: href(k, s, single) for k in FILTERS},
            "sort_links": {k: href(f, k, single) for k in SORTS}, "single_link": href(f, s, not single)}
    if cards is None:
        return {**base, "failed": True, "cards": [], "jump": {}, "total": 0}
    pool = [c for c in cards if single or c["n"] > 1]
    shown = [c for c in pool if f == "all" or (f == "complete") == c["complete"]]
    shown = [dict(c) for c in sort_cards(shown, s)]
    jump: dict[str, str] = {}
    if s == "name" and not tv:
        for c in shown:
            k = letter(c["name"])
            if k not in jump:
                jump[k] = c["anchor"] = "az-" + ("0" if k == "#" else k)
    complete = sum(1 for c in pool if c["complete"])
    return {**base, "failed": False, "cards": shown, "jump": jump, "total": len(pool),
            "singles": len(cards) - len([c for c in cards if c["n"] > 1]),
            "head_line": f"{media_text.plural(len(pool), 'collection')} · {complete} complete"}


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
def franchise_page(request: Request, col_id: str):
    if not col_id.isdigit() or not 0 < int(col_id) < 10 ** 9:
        return shell.not_found_page(request)
    col_id = int(col_id)
    request.state.media_section = "movies"
    owned = owned_of(request)
    col = mc.one(col_id, owned) or _fallback(col_id, owned)
    if col is None:
        return shell.not_found_page(request, "No collection here")
    ctx = franchise_ctx(col, media_front.tv_mode(request), _words())
    return shell.render_page(request, "media_collection.html", ctx)


@router.get(PAGE, response_class=HTMLResponse)
def grid_page(request: Request, f: str = "", s: str = "", single: str = "", kicked: str = ""):
    request.state.media_section = "movies"
    tv = media_front.tv_mode(request)
    ctx = grid_ctx(mc.summaries(owned_of(request)), f[:12], s[:12], single == "1", tv)
    owner = is_owner(request)
    last = mc.last_pass() if owner else None
    ctx.update(owner=owner, refresh=REFRESH, kicked=owner and kicked == "1", enabled=not mc.disabled(),
               last_words=media_text.short_date(last) if last else None)
    return shell.render_page(request, "media_collections.html", ctx)


@router.post(REFRESH, dependencies=[Depends(same_origin)])
def refresh(request: Request):
    """The owner's "Check now": every film and collection is due again; one pass runs after the response (the hourly
    loop carries on with the rest, PER_PASS a tick)."""
    if not is_owner(request):
        return shell.not_found_page(request)
    mc.kick()
    return RedirectResponse(PAGE + "?kicked=1", status_code=303,
                            background=BackgroundTask(mc.tick, lambda: shell.get_snapshots()))
