"""Discover & Search inside Media (2026-10-05): Jellyseerr-style search, discover shelves,
title pages with per-season status, and a two-step Request that goes THROUGH the hub.

A LIVE call path to Jellyseerr (env JELLYSEERR_URL + JELLYSEERR_API_KEY, header X-Api-Key),
server-side only. The key and URL never reach the browser (the one outward link is the
title page's "Open in Jellyseerr", like the existing request rows) and never reach a log
or an error: failures log the exception TYPE only and degrade to words, never a 500.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, quote

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from hub import media_files
from hub.images import REF_RE
from hub.media_watchlist import keys_for
from hub.media_write import MAX_BODY, bad, is_htmx, same_origin

log = logging.getLogger("hub.media_discover")
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

DISCOVER_DETAIL = "/media/discover"
TIMEOUT = 8
CACHE_TTL = 600
ROW_MAX = 20
ON_DISK = ("Available", "Partly available")
SHELVES = (
    ("trending", "Trending", "/api/v1/discover/trending", None),
    ("movies", "Popular films", "/api/v1/discover/movies", "movie"),
    ("tv", "Popular TV", "/api/v1/discover/tv", "tv"),
    ("movies-soon", "Upcoming films", "/api/v1/discover/movies/upcoming", "movie"),
    ("tv-soon", "Upcoming TV", "/api/v1/discover/tv/upcoming", "tv"),
)
ERRORS = {"exists": "Already requested", "declined": "Jellyseerr declined the request",
          "network": "Couldn't send the request"}

_cache: dict[str, tuple[float, list[dict]]] = {}


def clear_cache() -> None:
    _cache.clear()


def status_word(code) -> str:
    """The ONE mapping from Jellyseerr's media status code to a word."""
    return {5: "Available", 4: "Partly available", 3: "Processing", 2: "Requested"}.get(
        code if isinstance(code, int) else None, "Not in library")


def _creds() -> tuple[str, str] | None:
    base, key = os.environ.get("JELLYSEERR_URL", "").strip(), os.environ.get("JELLYSEERR_API_KEY", "").strip()
    return (base.rstrip("/"), key) if base and key else None


def _get(path: str):
    """GET a Jellyseerr JSON path -> parsed body, or None on no env / any failure."""
    creds = _creds()
    if not creds:
        return None
    try:
        resp = requests.get(f"{creds[0]}{path}", headers={"X-Api-Key": creds[1]}, timeout=TIMEOUT)
        if not 200 <= resp.status_code < 300:
            log.warning("jellyseerr read failed: HTTP %s", resp.status_code)
            return None
        return resp.json()
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyseerr read failed: %s", type(exc).__name__)
        return None


def _year(value) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


def _ref(path) -> str | None:
    ref = f"tmdb:{path}" if path else ""
    return ref if REF_RE.match(ref) else None


def _status_of(info) -> int | None:
    return info.get("status") if isinstance(info, dict) else None


def _row(r: dict, kind_hint: str | None = None) -> dict | None:
    """One search/discover result -> the shared row shape (None for people / junk)."""
    kind = r.get("mediaType") or kind_hint
    try:
        tmdb_id = int(r.get("id"))
    except (TypeError, ValueError):
        return None
    title = str(r.get("title") or r.get("name") or "").strip()[:200]
    if kind not in ("movie", "tv") or not title:
        return None
    return {"tmdb_id": tmdb_id, "kind": kind, "title": title,
            "year": _year(r.get("releaseDate") or r.get("firstAirDate")),
            "poster": _ref(r.get("posterPath")), "backdrop": _ref(r.get("backdropPath")),
            "status_word": status_word(_status_of(r.get("mediaInfo"))),
            "href": f"/media/title/{kind}/{tmdb_id}"}


def _rows(results, kind_hint=None) -> list[dict]:
    rows = (_row(r, kind_hint) for r in results if isinstance(r, dict))
    return [r for r in rows if r][:ROW_MAX]


def _shelf_rows(path: str, kind_hint) -> list[dict] | None:
    hit = _cache.get(path)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    body = _get(path)
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        return None  # a failed fetch is not cached
    rows = _rows(body["results"], kind_hint)
    _cache[path] = (time.time(), rows)
    return rows


def _search_outcome(q: str) -> tuple[list[dict], str | None]:
    if len(q) < 2:
        return [], "Type at least two letters"
    body = _get(f"/api/v1/search?query={quote(q, safe='')}")
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        return [], "Search unavailable"
    rows = _rows(body["results"])
    return rows, None if rows else "No matches"


def _page(request: Request, template: str, build):
    """Full page behind the discover tile; 404 (before any upstream call) when no registry
    tile has that detail. `build()` -> the page-specific context."""
    from hub import main as hub  # late: hub.main includes this router

    view, from_query = hub.resolve_owner_view(request)
    snaps = hub.get_snapshots()
    src = hub.find_detail_source(hub.JELLYSEERR_SNAPSHOT_ID, snaps, detail=DISCOVER_DETAIL)
    if src is None:
        return templates.TemplateResponse(request, "404.html", {
            "areas": hub.registry.areas, "active_id": None, "owner_view": view,
            "missing_text": "No page here"}, status_code=404)
    resp = templates.TemplateResponse(request, template, {
        "areas": hub.registry.areas, "active_id": None, "owner_view": view,
        "status": hub.build_status(snaps), "src": src, "connected": _creds() is not None, **build()})
    return hub._maybe_set_cookie(resp, view, from_query)


def _partial(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)


@router.get("/media/discover", response_class=HTMLResponse)
def discover_page(request: Request, q: str = ""):
    q = q.strip()[:100]

    def build():
        ctx = {"q": q, "shelves": [], "rows": [], "note": None, "wl_keys": set()}
        if _creds():
            if q:
                ctx["rows"], ctx["note"] = _search_outcome(q)
            else:
                with ThreadPoolExecutor(max_workers=len(SHELVES)) as pool:
                    got = list(pool.map(lambda s: _shelf_rows(s[2], s[3]), SHELVES))
                ctx["shelves"] = [{"id": s[0], "title": s[1], "rows": rows} for s, rows in zip(SHELVES, got)]
        ctx["wl_keys"] = keys_for(request, [f"tmdb:{r['tmdb_id']}" for r in ctx["rows"]
                                            + [r for s in ctx["shelves"] for r in s["rows"] or []]])
        return ctx

    return _page(request, "media_discover.html", build)


@router.get("/media/discover/search", response_class=HTMLResponse)
def discover_search(request: Request, q: str = ""):
    rows, note = _search_outcome(q.strip()[:100])
    return _partial(request, "_discover_results.html", rows=rows, note=note,
                    wl_keys=keys_for(request, [f"tmdb:{r['tmdb_id']}" for r in rows]))


# ---- Title page + request ----

def _kind(kind: str) -> str:
    if kind not in ("movie", "tv"):
        raise HTTPException(404, "No such title")
    return kind


def _seasons(data: dict, info: dict) -> list[dict]:
    have = {s.get("seasonNumber"): s.get("status") for s in (info.get("seasons") or []) if isinstance(s, dict)}
    out = []
    for s in data.get("seasons") or []:
        n = s.get("seasonNumber") if isinstance(s, dict) else None
        if not isinstance(n, int) or n < 0:
            continue
        code = have.get(n)
        out.append({"number": n, "name": str(s.get("name") or f"Season {n}")[:100],
                    "episodes": s.get("episodeCount") or 0, "year": _year(s.get("airDate")),
                    "code": code, "status_word": status_word(code)})
    out.sort(key=lambda s: (s["number"] == 0, s["number"]))  # Specials last
    for s in out:
        s["ticked"] = s["number"] != 0 and s["code"] not in (5, 3, 2)
        s["disabled"] = s["code"] == 5
    return out


def _title(kind: str, tmdb_id: int) -> dict | None:
    data = _get(f"/api/v1/{kind}/{tmdb_id}")
    if not isinstance(data, dict):
        return None
    info = data.get("mediaInfo") if isinstance(data.get("mediaInfo"), dict) else {}
    code = _status_of(info)
    row = _row({**data, "mediaType": kind, "id": tmdb_id}, kind) or {
        "tmdb_id": tmdb_id, "kind": kind, "title": "Untitled", "year": None, "poster": None,
        "backdrop": None, "status_word": status_word(code), "href": f"/media/title/{kind}/{tmdb_id}"}
    cast = [str(c.get("name"))[:80] for c in ((data.get("credits") or {}).get("cast") or [])[:8]
            if isinstance(c, dict) and c.get("name")]
    vote = data.get("voteAverage")
    creds = _creds()
    return {**row, "code": code, "tagline": str(data.get("tagline") or "")[:300],
            "overview": str(data.get("overview") or "")[:1200],
            "genres": [str(g.get("name")) for g in data.get("genres") or [] if isinstance(g, dict) and g.get("name")],
            "runtime": data.get("runtime") if kind == "movie" and data.get("runtime") else None,
            "n_seasons": data.get("numberOfSeasons"), "n_episodes": data.get("numberOfEpisodes"),
            "vote": f"{vote:.1f} / 10" if isinstance(vote, (int, float)) and vote > 0 else None,
            "cast": cast, "seasons": _seasons(data, info) if kind == "tv" else [],
            "jellyseerr_href": f"{creds[0]}/{kind}/{tmdb_id}" if creds else None}


def _block(t: dict, state: str, msg: str | None = None) -> dict:
    return {"t": t, "state": state, "msg": msg}


def _stub(kind: str, tmdb_id: int) -> dict:
    return {"kind": kind, "tmdb_id": tmdb_id, "title": "", "year": None, "seasons": [], "code": None}


def _dl_badge(title) -> str | None:
    """'Downloading · 43%' when the arr queue / qBittorrent holds this title; never raises."""
    from hub import main as hub  # late: hub.main includes this router
    from hub import media_downloads

    try:
        snaps = hub.get_snapshots()
        arr, qb = snaps.get(hub.ARR_SNAPSHOT_ID), snaps.get(media_downloads.QB_SNAPSHOT_ID)
        merged = media_downloads.merge_downloading((arr.data if arr else {}).get("downloading"),
                                                   qb.data if qb else {})
        return media_downloads.badge_for_title(merged, title)
    except Exception:
        log.warning("downloading badge skipped", exc_info=True)
        return None


@router.get("/media/title/{kind}/{tmdb_id}", response_class=HTMLResponse)
def title_page(request: Request, kind: str, tmdb_id: int, step: str = "", requested: str = "",
               error: str = ""):
    kind = _kind(kind)

    def build():
        connected = _creds() is not None
        t = _title(kind, tmdb_id) if connected else None
        if t is None:
            return {"t": None, "note": "Title unavailable" if connected else "Not connected"}
        if requested == "1":
            block = _block(t, "done")
        elif error in ERRORS:
            block = _block(t, "error", ERRORS[error])
        else:
            block = _block(t, "confirm" if step == "confirm" else "idle")
        files = media_files.file_summary(kind, tmdb_id) if t["status_word"] in ON_DISK else None
        return {"note": None, "dl_badge": _dl_badge(t["title"]), "files": files,
                "on_watchlist": bool(keys_for(request, [f"tmdb:{tmdb_id}"])), **block}

    return _page(request, "media_title.html", build)


@router.get("/media/title/{kind}/{tmdb_id}/request", response_class=HTMLResponse)
def request_step(request: Request, kind: str, tmdb_id: int, step: str = ""):
    kind = _kind(kind)
    t = _title(kind, tmdb_id)
    if t is None:
        return _partial(request, "_request_block.html", **_block(_stub(kind, tmdb_id), "error", "Title unavailable"))
    return _partial(request, "_request_block.html", **_block(t, "confirm" if step == "confirm" else "idle"))


# ---- Season episodes (lazy, TV only) ----

EPISODES_DOWN = "Episodes unavailable right now"


def _date_words(value) -> tuple[str | None, bool]:
    """'2026-03-14' -> ('14 Mar 2026', is_future); junk -> (None, False)."""
    try:
        d = date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None, False
    return f"{d.day} {d.strftime('%b')} {d.year}", d > date.today()


def _episodes(tmdb_id: int, n: int) -> list[dict] | None:
    path = f"/api/v1/tv/{tmdb_id}/season/{n}"
    hit = _cache.get(path)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    body = _get(path)
    if not isinstance(body, dict) or not isinstance(body.get("episodes"), list):
        return None  # a failed fetch is not cached
    out = []
    for e in body["episodes"]:
        num = e.get("episodeNumber") if isinstance(e, dict) else None
        if not isinstance(num, int):
            continue
        text, future = _date_words(e.get("airDate"))
        out.append({"number": num, "name": str(e.get("name") or f"Episode {num}")[:200],
                    "date_text": text, "future": future, "overview": str(e.get("overview") or "")[:600],
                    "still": _ref(e.get("stillPath"))})
    out.sort(key=lambda e: e["number"])
    _cache[path] = (time.time(), out)
    return out


@router.get("/media/title/tv/{tmdb_id}/season/{n}", response_class=HTMLResponse)
def season_episodes(request: Request, tmdb_id: int, n: int):
    eps = _episodes(tmdb_id, n) if n >= 0 else None
    if eps is None:
        return _partial(request, "_season_episodes.html", episodes=[], note=EPISODES_DOWN)
    files = media_files.file_summary("tv", tmdb_id)
    have = {tuple(k) for k in (files or {}).get("episode_keys") or []}
    rows = [{**e, "on_disk": (n, e["number"]) in have} for e in eps]
    return _partial(request, "_season_episodes.html", episodes=rows, note=None if rows else "No episodes listed")


async def _seasons_of(request: Request) -> list[int]:
    body = await request.body()
    if len(body) > MAX_BODY:
        raise bad("Too large")
    values = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get("seasons", [])
    try:
        nums = sorted({int(v) for v in values})
    except ValueError:
        raise bad("Pick at least one season") from None
    if not nums or nums[0] < 1 or len(nums) > 100:
        raise bad("Pick at least one season")
    return nums


def _send(kind: str, tmdb_id: int, seasons: list[int]) -> str | None:
    """POST the request to Jellyseerr -> None on success, else an ERRORS code."""
    creds = _creds()
    if not creds:
        return "network"
    payload: dict = {"mediaType": kind, "mediaId": tmdb_id}
    if kind == "tv":
        payload["seasons"] = seasons
    try:
        resp = requests.post(f"{creds[0]}/api/v1/request", json=payload,
                             headers={"X-Api-Key": creds[1]}, timeout=TIMEOUT)
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyseerr request failed: %s", type(exc).__name__)
        return "network"
    if 200 <= resp.status_code < 300:
        return None
    log.warning("jellyseerr request refused: HTTP %s", resp.status_code)
    return "exists" if resp.status_code == 409 else "declined"


@router.post("/media/title/{kind}/{tmdb_id}/request", dependencies=[Depends(same_origin)])
async def request_title(request: Request, kind: str, tmdb_id: int):
    kind = _kind(kind)
    seasons = await _seasons_of(request) if kind == "tv" else []
    code = _send(kind, tmdb_id, seasons)
    if is_htmx(request):
        stub = _stub(kind, tmdb_id)
        return _partial(request, "_request_block.html",
                        **(_block(stub, "done") if code is None else _block(stub, "error", ERRORS[code])))
    return RedirectResponse(f"/media/title/{kind}/{tmdb_id}?" + ("requested=1" if code is None else f"error={code}"),
                            status_code=303)
