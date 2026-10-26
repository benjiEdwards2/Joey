"""Joey's own web and phone player page (JY-054, 2026-10-27): `/media/watch/<item>`, look A "Classic overlay"
(B., 2026-10-27: "JY-052: A"). Spec: docs/specs/JY-054-web-phone-player.md. The player itself is hub/static/player.js,
calling the playback API (hub/player_api.py, docs/playback-contract.md) after the page has loaded.

* Behind the JY-053 flag (`PLAYER_API=on`, read on every request). Off, every method on /media/watch and anything under
  it answers exactly what an unknown path answers (`HTTPException(404)`): a method-agnostic catch-all, so there is never
  a 405, an Allow header or a trailing-slash redirect to say the route exists.
* Household only (JY-050 Q2 A): the private front, `you` or `her`. Anyone else gets the same 404; the media front never
  reaches here (PRIVATE in hub/guest.py, its gate answers the ordinary Joey 404 page).
* CLAUDE.md rule 7: the render calls nothing live. Title, episode line and up next come from the item read the title /
  episode page has just cached (`media_item.peek`); a cold cache renders neutral words and warms the cache AFTER the
  response (a BackgroundTask, as the film page's deferred reads).
* `available(request)` is the one switch the title / episode pages use to point Play here instead of Jellyfin.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from starlette.background import BackgroundTask

from hub import guest, media_item, player_api, shell
from hub.identity import resolve_identity

PREFIX = "/media/watch"
_HEX32 = re.compile(r"[0-9a-f]{32}")

router = APIRouter()


def available(request: Request | None) -> bool:
    """The player serves this viewer: the flag is on, the private front, and `you` or `her` is signed in."""
    if request is None or not player_api.enabled() or guest.is_media():
        return False
    return resolve_identity(request).owner in player_api.HOUSEHOLD


def href(jf_id) -> str:
    return f"{PREFIX}/{jf_id}"


def _item_id(rest: str) -> str | None:
    text = rest.replace("-", "").lower()
    return text if _HEX32.fullmatch(text) else None


def _up_next(item: dict) -> dict | None:
    """The aired episode after this one in the show's cached seasons (never a read), else None."""
    show = media_item.peek(item.get("show_id")) if item.get("kind") == "episode" else None
    eps = [(s.get("number"), e) for s in (show or {}).get("seasons") or [] for e in s.get("episodes") or []]
    at = next((i for i, (_, e) in enumerate(eps) if e.get("jf_id") == item.get("id")), None)
    if at is None:
        return None
    for season, e in eps[at + 1:]:
        if e.get("aired") and _item_id(str(e.get("jf_id") or "")):
            return {"href": href(_item_id(e["jf_id"])), "still": e.get("still"), "runtime": e.get("runtime"),
                    "label": f"S{season} · E{e.get('number')} · {e.get('name') or 'Episode'}"}
        return None   # the next one has not aired: nothing to play next
    return None


def page_data(jf_id: str) -> dict | None:
    """The overlay's words from the cached item read, or None when nothing is cached."""
    item = (media_item.peek(jf_id) or {}).get("item")
    if not item:
        return None
    episode = item.get("kind") == "episode"
    line = None
    if episode and item.get("season_no") is not None and item.get("episode_no") is not None:
        line = f"S{item['season_no']} · E{item['episode_no']} · {item.get('title') or 'Episode'}"
    elif episode:
        line = item.get("title")
    title = (item.get("show_title") if episode else None) or item.get("title") or "Jellyfin item"
    meta = [str(m) for m in (item.get("year"), item.get("runtime"), item.get("official_rating")) if m]
    return {"title": title, "line": line, "meta": meta, "up_next": _up_next(item)}


ALL_METHODS = player_api.ALL_METHODS


@router.api_route(PREFIX, methods=ALL_METHODS, include_in_schema=False)
@router.api_route(f"{PREFIX}/{{rest:path}}", methods=ALL_METHODS, include_in_schema=False)
def watch_page(request: Request, rest: str = ""):
    if request.method not in ("GET", "HEAD") or not available(request):
        raise HTTPException(404)
    jf_id = _item_id(rest)
    if jf_id is None:
        raise HTTPException(404)
    data = page_data(jf_id)
    page = data or {"title": "Jellyfin item", "line": None, "meta": [], "up_next": None}
    resp = shell.templates.TemplateResponse(request, "media_watch.html", {
        "item_id": jf_id, "back_href": f"/media/item/{jf_id}", **page})
    resp.headers["Cache-Control"] = "no-store"
    if data is None:   # rule 7: never a read before the render; the next load finds the words
        resp.background = BackgroundTask(media_item.warm, jf_id)
    return resp
