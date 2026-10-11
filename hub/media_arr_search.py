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

3. Search all monitored (F3, 2026-10-12). Activity › Requests and › Downloads: "Search missing" / "Search upgrades"
   (GET /media/arr/sweep?step=confirm, then the same-origin POST) send Radarr MissingMoviesSearch / CutoffUnmetMoviesSearch
   and Sonarr MissingEpisodeSearch / CutoffUnmetEpisodeSearch, both apps in parallel, 10 s each.

4. Search for upgrade (F4b, 2026-10-12). When the title's file is below its quality cutoff (the arr snapshot's
   `upgrades`, matched on the app's own id from the lookup above), the lazy fragment adds "Search for upgrade": an
   inline confirm (details), then the same-origin POST /media/title/{kind}/{tmdb}/upgrade sends the title's
   MoviesSearch / SeriesSearch; the app grabs the best release its profile allows. Flash: ?upgrade=started|failed.

Upstream failures are words; logs carry an exception TYPE or an HTTP status only (requests errors embed URLs/keys).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import media_discover as md, media_requests as mr, media_text, media_upgrades, shell
from hub.media_write import flash_keys, form_of, is_htmx, safe_back, same_origin

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


_why = media_text.why   # log-safe words: 'HTTP 503' or the exception type, never its message


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


def _command(app: str, base: str, headers: dict, entry: dict | None, body: dict | None = None,
             timeout: float = TIMEOUT) -> None:
    """POST /api/v3/command: the title's search for `entry`, or the given `body` (a whole-library sweep)."""
    if body is None:
        body = ({"name": "MoviesSearch", "movieIds": [int(entry["id"])]} if app == "radarr"
                else {"name": "SeriesSearch", "seriesId": int(entry["id"])})
    _ok(requests.post(f"{base}/api/v3/command", json=body, headers=headers, timeout=timeout))


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


flash_keys("search", "app", "code")


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
    """A local Media page to return to (media_write.safe_back), else the title page — never Server."""
    return safe_back(value, f"/media/title/{kind}/{tmdb}")


def lazy_href(kind: str | None, tmdb, tvdb, back: str) -> str | None:
    """The film page's lazy-load URL for the Search now form, or None (no TMDB id / app not connected)."""
    if kind not in ("movie", "tv") or not isinstance(tmdb, int) or tmdb <= 0 or not connected(kind):
        return None
    q = {"back": back, **({"tvdb": tvdb} if _tvdb(tvdb) else {})}
    return f"/media/title/{kind}/{tmdb}/arr?" + urlencode(q)


# ---- All seasons + future (item 7) ----

FUTURE = {"set": ("Sonarr: every season monitored, new seasons too · search started", True),
          "searchfail": ("Sonarr: every season monitored, new seasons too · couldn't start the search", False),
          "notyet": ("Sonarr hasn't added it yet — new seasons are not set to follow", False),
          "unset": ("Sonarr is not connected — new seasons are not set to follow", False),
          "failed": ("Couldn't set Sonarr to follow new seasons", False)}


def future_note(code) -> dict | None:
    """{text, ok} for the request block's second line, or None for an unknown / absent code."""
    hit = FUTURE.get(str(code or ""))
    return {"text": hit[0], "ok": hit[1]} if hit else None


def follow_all(tmdb: int, tvdb: int | None = None) -> str:
    """After an all-seasons Jellyseerr request: Sonarr series -> monitored + monitorNewItems "all" (the app's own resource
    PUT back, every other field kept), then SeriesSearch. Returns a FUTURE code. The series appears in Sonarr a few
    seconds after Jellyseerr hands it over: up to FOLLOW_TRIES reads, FOLLOW_WAIT s apart, else "notyet"."""
    creds = mr._arr_creds("sonarr")
    if creds is None:
        return "unset"
    base, headers = creds
    try:
        entry = None
        for attempt in range(FOLLOW_TRIES):
            if attempt:
                time.sleep(FOLLOW_WAIT)
            entry = mr._find("sonarr", base, headers, tmdb, tvdb)
            if entry is not None:
                break
        if entry is None:
            return "notyet"
        _ok(requests.put(f"{base}/api/v3/series/{int(entry['id'])}",
                         json={**entry, "monitored": True, "monitorNewItems": "all"}, headers=headers, timeout=TIMEOUT))
    except Exception as exc:
        log.warning("sonarr follow-new-seasons failed: %s", _why(exc))
        return "failed"
    try:
        _command("sonarr", base, headers, entry)
    except Exception as exc:
        log.warning("sonarr search after follow failed: %s", _why(exc))
        return "searchfail"
    return "set"


@router.get("/media/title/{kind}/{tmdb_id}/arr", response_class=HTMLResponse)
def search_button(request: Request, kind: str, tmdb_id: int, tvdb: str = "", back: str = ""):
    kind = md._kind(kind)
    entry = find(kind, tmdb_id, _tvdb(tvdb)) if tmdb_id > 0 else None
    if entry is None:
        return HTMLResponse("")   # not in the app (or unreachable): no button, the Request flow applies
    return md._partial(request, "_arr_search.html", kind=kind, tmdb_id=tmdb_id, tvdb=_tvdb(tvdb),
                       back=_back(back, kind, tmdb_id), app=NAMES[app_of(kind)], monitored=bool(entry.get("monitored")),
                       upgrade=upgrade_row(request, kind, entry))


@router.post("/media/title/{kind}/{tmdb_id}/search", dependencies=[Depends(same_origin)])
async def search_now(request: Request, kind: str, tmdb_id: int):
    kind = md._kind(kind)
    form = await form_of(request)
    back = _back(form.get("back"), kind, tmdb_id)
    code, status = (await run_in_threadpool(start_search, kind, tmdb_id, _tvdb(form.get("tvdb")))  # M-40: off the loop
                    if tmdb_id > 0 else ("missing", None))
    q = {"search": code, "app": app_of(kind), **({"code": status} if status else {})}
    return RedirectResponse(f"{back}?" + urlencode(q), status_code=303)


# ---- Search all monitored (F3, 2026-10-12) ----
# B.: "a search button in Requests and on the Activity page … search for all monitored on Sonarr and Radarr". The
# Activity › Requests and › Downloads tabs both include `_arr_sweep.html`: "Search missing" / "Search upgrades", each a
# two-step confirm (GET ?step=confirm swaps the card in place, the same_origin POST runs it) like Update now.

SWEEP_TIMEOUT = 10                  # seconds, per app
THROTTLE_S = 600                    # a second sweep of the same kind inside 10 min is allowed, but the card says so
SWEEPS = {"missing": {"radarr": "MissingMoviesSearch", "sonarr": "MissingEpisodeSearch"},
          "upgrades": {"radarr": "CutoffUnmetMoviesSearch", "sonarr": "CutoffUnmetEpisodeSearch"}}
SWEEP_ASK = {"missing": "Search every monitored title that has no file yet?",
             "upgrades": "Search for better copies of every monitored title below its quality cutoff?"}
SWEEP_LABEL = {"missing": "Search missing", "upgrades": "Search upgrades"}
SWEEP_BACK = "/media/requests"
_started: dict[str, float] = {}     # kind -> clock() of the last sweep that started (in-process only)
_clock = time.monotonic


def sweep_apps() -> list[str]:
    """The connected apps, Radarr first: ["radarr", "sonarr"], one of them, or []."""
    return [app for app in NAMES if mr._arr_creds(app) is not None]


def sweep_since(kind: str) -> int | None:
    """Whole minutes since this kind last started, while under THROTTLE_S; else None."""
    at = _started.get(kind)
    if at is None or _clock() - at >= THROTTLE_S:
        return None
    return int((_clock() - at) // 60)


def _sweep_one(app: str, kind: str) -> bool:
    creds = mr._arr_creds(app)
    if creds is None:
        return False
    try:
        _command(app, *creds, None, body={"name": SWEEPS[kind][app]}, timeout=SWEEP_TIMEOUT)
        return True
    except Exception as exc:
        log.warning("%s sweep failed: %s", app, _why(exc))
        return False


flash_keys("sweep", "ran")


def sweep_flash(params) -> tuple[str | None, str | None]:
    """(good line, warning line) from `?sweep=<code>&ran=<app>[,<app>]`; anything odd -> (None, None)."""
    code = params.get("sweep") or ""
    ran = [NAMES[a] for a in (params.get("ran") or "").split(",") if a in NAMES]
    if code == "started" and ran:
        return " · ".join(["Search started", *ran]), None
    if code == "partial" and len(ran) == 1:
        return f"Search started · {ran[0]} only", None
    if code == "failed":
        return None, "Couldn't start the search"
    return None, None


def sweep_ctx(request, ask: str | None = None, back: str | None = None) -> dict:
    """What `_arr_sweep.html` draws: connected app names, the kind being confirmed (else the two buttons), the
    throttle note, the page to return to and the flash. Pages call it as the `arr_sweep(request)` global."""
    params = request.query_params if request is not None else {}
    page = back or (safe_back(request.url.path, SWEEP_BACK) if request is not None else SWEEP_BACK)
    if ask is None and back is None:
        ask = params.get("sweep_ask")       # the no-JS confirm step, drawn by the page itself
    ask = ask if ask in SWEEPS else None
    good, warn = sweep_flash(params) if ask is None else (None, None)
    return {"apps": [NAMES[a] for a in sweep_apps()], "ask": ask, "since": sweep_since(ask) if ask else None,
            "back": page, "flash": good, "flash_warn": warn, "ask_text": SWEEP_ASK.get(ask or ""),
            "labels": SWEEP_LABEL}


shell.templates.env.globals["arr_sweep"] = sweep_ctx


@router.get("/media/arr/sweep", response_class=HTMLResponse)
def sweep_step(request: Request, step: str = "", kind: str = "", back: str = ""):
    """htmx: the row with the confirm card (step=confirm) or the plain buttons (Cancel). Without htmx: back to the page,
    which draws the same card from `?sweep_ask=<kind>`."""
    back = safe_back(back, SWEEP_BACK)
    ask = kind if step == "confirm" and kind in SWEEPS else None
    if not is_htmx(request):
        return RedirectResponse(back + (f"?sweep_ask={ask}" if ask else ""), status_code=303)
    return md._partial(request, "_arr_sweep.html", sw=sweep_ctx(request, ask, back))


@router.post("/media/arr/sweep", dependencies=[Depends(same_origin)])
async def sweep_now(request: Request):
    form = await form_of(request)
    kind = form.get("kind") or ""
    if kind not in SWEEPS:
        raise HTTPException(422, "Unknown search")
    back = safe_back(form.get("back"), SWEEP_BACK)
    apps = sweep_apps()
    # wave-2 rule: off the event loop; one thread per app so a stuck one never holds the other past its own timeout
    oks = await asyncio.gather(*(run_in_threadpool(_sweep_one, app, kind) for app in apps))
    ran = [app for app, ok in zip(apps, oks) if ok]
    if not ran:
        q = {"sweep": "failed"}
    else:
        _started[kind] = _clock()
        q = {"sweep": "started" if len(ran) == len(apps) else "partial", "ran": ",".join(ran)}
    return RedirectResponse(f"{back}?" + urlencode(q), status_code=303)


# ---- Search for upgrade (F4b, 2026-10-12) ----
# B.: "show me if an upgrade is available … and allow me to decide if I want to download that upgrade." The film / show
# hero says "Upgrade available · <have> → <want>" from the arr snapshot; the Search-now fragment adds the button when
# the app's own id for this title is on the snapshot's cutoff-unmet list (exact, whatever key Jellyfin uses).

flash_keys("upgrade")
UPGRADE_FLASH = {"started": ("Upgrade search started", None), "failed": (None, "Couldn't start the search")}


def upgrade_row(request, kind: str, entry: dict) -> dict | None:
    """The snapshot's upgrade row for this app entry (matched on `arr_id`), or None."""
    app = app_of(kind)
    for row in media_upgrades.index(shell.get_snapshots(request=request)).values():
        if row["app"] == app and str(row.get("arr_id")) == str(entry.get("id")):
            return row
    return None


def upgrade_flash(params) -> tuple[str | None, str | None]:
    """(good line, warning line) from `?upgrade=started|failed`; anything else -> (None, None)."""
    return UPGRADE_FLASH.get(params.get("upgrade") or "", (None, None))


def start_upgrade(kind: str, tmdb: int, tvdb: int | None = None) -> bool:
    """Ask Radarr / Sonarr to search the title now (MoviesSearch / SeriesSearch on its own id): True when the command
    was accepted. The app replaces the file only with a release its profile ranks higher."""
    app = app_of(kind)
    creds = mr._arr_creds(app)
    if creds is None:
        return False
    base, headers = creds
    try:
        entry = mr._find(app, base, headers, tmdb, tvdb)
        if entry is None:
            return False
        _command(app, base, headers, entry)
        return True
    except Exception as exc:
        log.warning("%s upgrade search failed: %s", app, _why(exc))
        return False


@router.post("/media/title/{kind}/{tmdb_id}/upgrade", dependencies=[Depends(same_origin)])
async def upgrade_now(request: Request, kind: str, tmdb_id: int):
    kind = md._kind(kind)
    form = await form_of(request)
    back = _back(form.get("back"), kind, tmdb_id)
    ok = tmdb_id > 0 and await run_in_threadpool(start_upgrade, kind, tmdb_id, _tvdb(form.get("tvdb")))  # off the loop
    return RedirectResponse(f"{back}?" + urlencode({"upgrade": "started" if ok else "failed"}), status_code=303)
