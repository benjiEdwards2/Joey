"""Search now + "All seasons + future" (media-ux5, 2026-10-09): two live Radarr / Sonarr writes, server-side only
(env RADARR_URL / RADARR_API_KEY, SONARR_URL / SONARR_API_KEY, header X-Api-Key; creds + title lookup reused from
media_requests: Radarr GET /api/v3/movie?tmdbId=, Sonarr GET /api/v3/series?tvdbId= else the full list by tmdbId).

1. Search now (item 6). The film / series page (also a Discover title page — one template) lazy-loads
   GET /media/title/{kind}/{tmdb}/arr: the "Search now" form when the title is in the app, else nothing (the
   Request flow applies). POST /media/title/{kind}/{tmdb}/search (same-origin) sends Radarr
   `POST /api/v3/command {"name": "MoviesSearch", "movieIds": [id]}` or Sonarr
   `POST /api/v3/command {"name": "SeriesSearch", "seriesId": id}` and 303s back with `?search=<code>&app=<app>`.
   The apps search MONITORED items only (Sonarr: monitored episodes of the series); an unmonitored title is still
   sent, and the flash says it may find nothing.
2. All seasons + future (item 7). After a successful Jellyseerr TV request that asked for every season, the series is
   looked up in Sonarr (it appears a few seconds after Jellyseerr hands it over: up to FOLLOW_TRIES reads, FOLLOW_WAIT s
   apart, else skipped and said so), then `PUT /api/v3/series/{id}` with the app's own resource plus
   `monitored: true, monitorNewItems: "all"` (every other field kept), then SeriesSearch.

Upstream failures are words; logs carry an exception TYPE or an HTTP status only (requests errors embed URLs/keys).
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub import media_discover as md, media_requests as mr, media_resume
from hub.media_write import form_of, same_origin

log = logging.getLogger("hub.media_arr_search")
router = APIRouter()

TIMEOUT = 8
FOLLOW_TRIES = 3     # item 7: Sonarr reads after the request, at most
FOLLOW_WAIT = 2.0    # seconds between them
NAMES = {"radarr": "Radarr", "sonarr": "Sonarr"}
FLASH_OK = {"started": "Search started in {app}",
            "unmonitored": "Search started in {app} · not monitored there, so it may find nothing"}
FLASH_BAD = {"missing": "Not in {app} — use Request", "unset": "{app} is not connected",
             "unreachable": "Couldn't reach {app}", "refused": "{app} refused"}


def app_of(kind: str) -> str:
    return mr.APPS["tv" if kind == "tv" else "movie"]


def connected(kind: str) -> bool:
    return mr._arr_creds(app_of(kind)) is not None


def _ok(resp) -> None:
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")


def _why(exc: Exception) -> str:
    """Log-safe words for a failure: the HTTP status, else the exception type (never its message)."""
    return str(exc) if isinstance(exc, RuntimeError) and re.fullmatch(r"HTTP \d{3}", str(exc)) else type(exc).__name__


def find(kind: str, tmdb: int, tvdb: int | None = None) -> dict | None:
    """The app's own resource for this title, or None (not there / not connected / unreachable — logged)."""
    app = app_of(kind)
    creds = mr._arr_creds(app)
    if creds is None:
        return None
    try:
        return mr._find(app, *creds, tmdb, tvdb)
    except Exception as exc:
        log.warning("%s lookup failed: %s", app, _why(exc))
        return None


def _command(app: str, base: str, headers: dict, entry: dict) -> None:
    body = ({"name": "MoviesSearch", "movieIds": [int(entry["id"])]} if app == "radarr"
            else {"name": "SeriesSearch", "seriesId": int(entry["id"])})
    _ok(requests.post(f"{base}/api/v3/command", json=body, headers=headers, timeout=TIMEOUT))


def start_search(kind: str, tmdb: int, tvdb: int | None = None) -> tuple[str, int | None]:
    """Ask Radarr / Sonarr to search for the title now -> (code, HTTP status or None). Codes: FLASH_OK / FLASH_BAD."""
    app = app_of(kind)
    creds = mr._arr_creds(app)
    if creds is None:
        return "unset", None
    base, headers = creds
    try:
        entry = mr._find(app, base, headers, tmdb, tvdb)
        if entry is None:
            return "missing", None
        _command(app, base, headers, entry)
        return ("started" if entry.get("monitored") else "unmonitored"), None
    except Exception as exc:
        why = _why(exc)
        log.warning("%s search failed: %s", app, why)
        status = int(why[5:]) if why.startswith("HTTP ") else None
        return ("refused" if status else "unreachable"), status


def flash_text(params) -> tuple[str | None, str | None]:
    """(good line, warning line) from `?search=<code>&app=<app>[&code=<status>]`; anything odd -> (None, None)."""
    code, app, status = params.get("search") or "", NAMES.get(params.get("app") or ""), params.get("code") or ""
    if not app:
        return None, None
    if code in FLASH_OK:
        return FLASH_OK[code].format(app=app), None
    if code in FLASH_BAD:
        word = FLASH_BAD[code].format(app=app)
        return None, word + (f" (HTTP {status})" if code == "refused" and re.fullmatch(r"\d{3}", status) else "")
    return None, None


def _tvdb(value) -> int | None:
    v = str(value or "")
    return int(v) if v.isdigit() and 0 < len(v) <= 10 and int(v) > 0 else None


def _back(value, kind: str, tmdb: int) -> str:
    """A local Media page to return to (media_resume's rule), else the title page."""
    raw = str(value or "")
    v = media_resume._back(raw)
    if v == media_resume.DEFAULT_BACK and not raw.startswith(media_resume.DEFAULT_BACK):
        return f"/media/title/{kind}/{tmdb}"   # missing / foreign / odd -> the title page, not Server
    return v


def lazy_href(kind: str | None, tmdb, tvdb, back: str) -> str | None:
    """The film page's lazy-load URL for the Search now form, or None (no TMDB id / app not connected)."""
    if kind not in ("movie", "tv") or not isinstance(tmdb, int) or tmdb <= 0 or not connected(kind):
        return None
    q = {"back": back, **({"tvdb": tvdb} if _tvdb(tvdb) else {})}
    return f"/media/title/{kind}/{tmdb}/arr?" + urlencode(q)


@router.get("/media/title/{kind}/{tmdb_id}/arr", response_class=HTMLResponse)
def search_button(request: Request, kind: str, tmdb_id: int, tvdb: str = "", back: str = ""):
    kind = md._kind(kind)
    entry = find(kind, tmdb_id, _tvdb(tvdb)) if tmdb_id > 0 else None
    if entry is None:
        return HTMLResponse("")   # not in the app (or unreachable): no button, the Request flow applies
    return md._partial(request, "_arr_search.html", kind=kind, tmdb_id=tmdb_id, tvdb=_tvdb(tvdb),
                       back=_back(back, kind, tmdb_id), app=NAMES[app_of(kind)], monitored=bool(entry.get("monitored")))


@router.post("/media/title/{kind}/{tmdb_id}/search", dependencies=[Depends(same_origin)])
async def search_now(request: Request, kind: str, tmdb_id: int):
    kind = md._kind(kind)
    form = await form_of(request)
    back = _back(form.get("back"), kind, tmdb_id)
    code, status = start_search(kind, tmdb_id, _tvdb(form.get("tvdb"))) if tmdb_id > 0 else ("missing", None)
    q = {"search": code, "app": app_of(kind), **({"code": status} if status else {})}
    return RedirectResponse(f"{back}?" + urlencode(q), status_code=303)
