"""Media write routes (2026-10-05) — the hub's first write path: rate a title,
log a watch, and the Jellyseerr title search behind the log form. Small on
purpose: same-origin guard, strict validation, urlencoded bodies parsed by hand
(no multipart dependency), partial templates for htmx and a 303 for plain forms.

Nothing here ever echoes a URL or key: the search says "Search unavailable" in words.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date
from urllib.parse import parse_qs, quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from hub import media_db, shell
from hub.images import REF_RE
from hub.shell import templates  # the ONE shared Jinja env (M-23 / H-31)

log = logging.getLogger("hub.media_write")
router = APIRouter()

MAX_BODY = 8192
SEARCH_MAX = 8
PLACES = ("Cinema", "Netflix", "Friend's", "Other")   # the diary log form's place suggestions (<datalist>)
# Where a plain-form rating may return (media-ux2): the pages that hold a To rate list. Anything else -> history.
# media-ux4: the Movies / TV Shows "To rate" tabs (the list pages keep their entries for forms already open).
RATE_BACK = {p: p for p in ("/media/history", "/media/movies", "/media/tv", "/media/movies/to-rate", "/media/tv/to-rate")}


def same_origin(request: Request) -> None:
    """403 unless the write is an htmx request (a custom header a cross-site page
    can't send) or its Origin is absent / matches the host the hub was reached on."""
    if request.headers.get("hx-request") == "true":
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
    if urlparse(origin).netloc in hosts - {None}:
        return
    raise HTTPException(403, "Cross-site write refused")


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def bad(detail: str) -> HTTPException:
    return HTTPException(422, detail)


def valid_key(key: str) -> str:
    if not media_db.KEY_RE.match(key or ""):
        raise bad("Invalid item")
    return key


def clean_item(f: dict) -> dict:
    """Validated identity fields shared by the rate and log forms."""
    year = f.get("year") or ""
    poster = f.get("poster") or ""
    title = (f.get("title") or "").strip()
    if not title or len(title) > 200:
        raise bad("Invalid title")
    return {
        "item_key": valid_key(f.get("item_key", "")),
        "kind": media_db.norm_kind(f.get("kind")),
        "title": title,
        "year": int(year) if re.fullmatch(r"(18|19|20|21)\d\d", str(year)) else None,
        "poster": poster if REF_RE.match(poster) else None,
    }


async def form_of(request: Request) -> dict:
    body = await request.body()
    if len(body) > MAX_BODY:
        raise bad("Too large")
    return {k: v[-1] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}


def owner_for(request: Request) -> str:
    """THE request-level owner (M-16): 'her' in the her view, else 'you' (media_db.owner_of over the owner view)."""
    return media_db.owner_of(shell.resolve_owner_view(request)[0])


def safe_back(value, default: str, keep_query: bool = False, prefixes=("/media/", "/a/"), exact=("/",)) -> str:
    """THE redirect-target rule for Media writes (M-17): a local page path — one of `exact`, or under `prefixes` —
    with no scheme, no '//', no backslash and under 300 characters; anything else is `default`. A fragment is always
    dropped; the query too unless `keep_query` (a stale flash never rides along)."""
    v = str(value or "").split("#", 1)[0]
    if not keep_query:
        v = v.split("?", 1)[0]
    ok = v in exact or v.startswith(prefixes)
    return v if ok and "//" not in v and "\\" not in v and len(v) < 300 else default


# One-off flash lines ride on query params after a POST's 303 (2026-10-08); base.html strips them from the address
# bar after render. Each module registers the params it reads here, and hub.main's FLASH_PARAMS is derived from this
# registry (M-17) instead of a hand-kept list.
FLASH_KEYS: dict[str, None] = {}


def flash_keys(*keys: str) -> tuple[str, ...]:
    """Register flash query params (idempotent); returns them."""
    for k in keys:
        FLASH_KEYS.setdefault(k, None)
    return keys


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)


@router.post("/media/settings/rating_level", dependencies=[Depends(same_origin)])
async def set_rating_level(request: Request):
    """'Rate TV by' choice for the owner; back to the To rate inbox it reshapes."""
    return await run_in_threadpool(_set_rating_level, request, await form_of(request))


def _set_rating_level(request: Request, f: dict):
    value = f.get("value") or ""
    if value not in media_db.LEVELS:
        raise bad("Invalid rating level")
    try:
        media_db.set_setting(owner_for(request), "rating_level", value)
    except (sqlite3.Error, OSError) as exc:
        log.warning("setting not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the setting") from None
    return RedirectResponse("/media/history", status_code=303)


@router.post("/media/rate", dependencies=[Depends(same_origin)])
async def rate(request: Request):
    return await run_in_threadpool(_rate, request, await form_of(request))


def _rate(request: Request, f: dict):
    item = clean_item(f)
    try:
        score = int(f.get("score", ""))
    except ValueError:
        raise bad("Score must be 1 to 10") from None
    if not 1 <= score <= 10:
        raise bad("Score must be 1 to 10")
    level = f.get("level") or "show"
    if level not in media_db.LEVELS:
        raise bad("Invalid rating level")
    try:
        media_db.set_rating(score=score, owner=owner_for(request), level=level, **item)
    except (sqlite3.Error, OSError) as exc:
        log.warning("rating not saved: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't save the rating") from None
    if is_htmx(request):
        return render(request, "_rated_row.html", r=item, score=score)
    return RedirectResponse(RATE_BACK.get(f.get("back"), "/media/history"), status_code=303)


def _unrate(item_key: str, owner: str) -> dict | None:
    """Delete the rating; return its identity fields so undo can show the picker again."""
    valid_key(item_key)
    try:
        row = media_db.get_rating(item_key, owner)
        media_db.delete_rating(item_key, owner)
    except (sqlite3.Error, OSError) as exc:
        log.warning("rating not removed: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't remove the rating") from None
    return row


@router.delete("/media/rate/{item_key}", dependencies=[Depends(same_origin)])
def unrate(request: Request, item_key: str):
    row = _unrate(item_key, owner_for(request))
    if row is None:
        return Response(status_code=200)  # nothing to restore: the swap just empties the box
    return render(request, "_rate_picker.html", r=row)


@router.post("/media/rate/{item_key}/delete", dependencies=[Depends(same_origin)])
def unrate_form(request: Request, item_key: str):
    _unrate(item_key, owner_for(request))
    return RedirectResponse("/media/history", status_code=303)


# To rate: Skip / Skip show (E5, M3, 2026-10-13). Plain forms (hx-swap "innerHTML show:none": the boosted 303 re-renders
# the page in place, scroll kept); owner-scoped like ratings; back to the To rate page the form came from.
SKIP_FLASH = {"item": ("Skipped", None), "show": ("Show skipped", None), "unskip": ("Back in To Rate", None),
              "failed": (None, "Couldn't save that")}
flash_keys("skip")


def skip_flash(request) -> tuple[str | None, str | None]:
    """(good, warn) words for the `?skip=` flash; (None, None) otherwise. Jinja global `skip_flash(request)`."""
    return SKIP_FLASH.get((request.query_params.get("skip") or "") if request else "", (None, None))


shell.templates.env.globals["skip_flash"] = skip_flash


def _skip_back(f: dict, word: str):
    return RedirectResponse(f"{RATE_BACK.get(f.get('back'), '/media/history')}?skip={word}", status_code=303)


@router.post("/media/rate/skip", dependencies=[Depends(same_origin)])
async def skip_item(request: Request):
    return await run_in_threadpool(_skip, request, await form_of(request), False)


@router.post("/media/rate/skip-show", dependencies=[Depends(same_origin)])
async def skip_show(request: Request):
    return await run_in_threadpool(_skip, request, await form_of(request), True)


def _skip(request: Request, f: dict, forever: bool):
    item = clean_item(f)   # item_key = the inbox key (Skip) or the show key (Skip show)
    if forever and item["kind"] != "tv":
        raise bad("Only a show can be skipped as a whole")
    try:
        media_db.skip(owner_for(request), item["item_key"], item["kind"], item["title"], item["poster"], forever)
    except (sqlite3.Error, OSError) as exc:
        log.warning("skip not saved: %s", type(exc).__name__)
        return _skip_back(f, "failed")
    return _skip_back(f, "show" if forever else "item")


@router.post("/media/rate/unskip", dependencies=[Depends(same_origin)])
async def unskip(request: Request):
    return await run_in_threadpool(_unskip, request, await form_of(request))


def _unskip(request: Request, f: dict):
    key = valid_key(f.get("key", ""))
    try:
        media_db.unskip(owner_for(request), key)
    except (sqlite3.Error, OSError) as exc:
        log.warning("unskip not saved: %s", type(exc).__name__)
        return _skip_back(f, "failed")
    return _skip_back(f, "unskip")


@router.post("/media/log", dependencies=[Depends(same_origin)])
async def log_watch(request: Request):
    return await run_in_threadpool(_log_watch, request, await form_of(request))


def _log_watch(request: Request, f: dict):
    try:
        pick = json.loads(f.get("pick") or "")
    except ValueError:
        raise bad("Pick a title first") from None
    if not isinstance(pick, dict):
        raise bad("Pick a title first")
    item = clean_item({k: (str(v) if v is not None else "") for k, v in pick.items()})
    try:
        watched_on = date.fromisoformat(f.get("watched_on") or date.today().isoformat())
    except ValueError:
        raise bad("Invalid date") from None
    if watched_on > date.today():
        raise bad("Date is in the future")
    try:
        row = media_db.add_manual_watch(**item, watched_on=watched_on.isoformat(),
                                        place=(f.get("place") or "").strip()[:60] or None,
                                        note=(f.get("note") or "").strip()[:500] or None,
                                        owner=owner_for(request))
    except (sqlite3.Error, OSError) as exc:
        log.warning("watch not logged: %s", type(exc).__name__)
        raise HTTPException(503, "Couldn't log the watch") from None
    if not is_htmx(request):
        return RedirectResponse("/media/diary", status_code=303)
    if row is None:
        return HTMLResponse('<div class="sub appnote">Already in the diary for that day.</div>')
    return render(request, "_diary_row.html", row=row, score=None)


def _search(query: str) -> list[dict] | None:
    """Jellyseerr title search -> rows, or None when unavailable (no env or any failure). The call goes through
    media_discover's one Jellyseerr reader (M-13); this maps its results to the diary log's rows."""
    from hub import media_discover as md  # late: media_discover imports this module

    if md._creds() is None:
        return None
    body = md._get(f"/api/v1/search?query={quote(query, safe='')}")
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        return None
    rows = []
    for r in results:
        if r.get("mediaType") not in ("movie", "tv") or not r.get("id"):
            continue
        year = str(r.get("releaseDate") or r.get("firstAirDate") or "")[:4]
        path = r.get("posterPath") or ""
        rows.append({"item_key": f"tmdb:{int(r['id'])}", "kind": r["mediaType"],
                     "title": str(r.get("title") or r.get("name") or "")[:200],
                     "year": int(year) if year.isdigit() else None,
                     "poster": f"tmdb:{path}" if REF_RE.match(f"tmdb:{path}") else None})
    return [r for r in rows if r["title"]][:SEARCH_MAX]


@router.get("/media/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    q = q.strip()[:100]
    if len(q) < 2:
        return render(request, "_search_results.html", rows=[], note="Type at least two letters")
    rows = _search(q)
    if rows is None:
        return render(request, "_search_results.html", rows=[], note="Search unavailable")
    return render(request, "_search_results.html", rows=rows, note=None if rows else "No matches")

