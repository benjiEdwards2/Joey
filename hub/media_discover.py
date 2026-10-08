"""Discover & Search inside Media (2026-10-05): Jellyseerr-style search, discover shelves,
title pages with per-season status, and a two-step Request that goes THROUGH the hub.

A LIVE call path to Jellyseerr (env JELLYSEERR_URL + JELLYSEERR_API_KEY, header X-Api-Key),
server-side only. The key and URL never reach the browser (the one outward link is the
title page's "Open in Jellyseerr", like the existing request rows) and never reach a log
or an error: failures log the exception TYPE only and degrade to words, never a 500.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, quote

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from hub import media_files
from hub.images import REF_RE, cache_dir
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

# Long-lived metadata (2026-10-07, media-speed): responses that carry NO user state (ratings, a person's
# biography, a season's episode list) are kept META_TTL in memory AND on disk (META_CACHE_DIR, one JSON file per
# path, inside the mounted poster-cache volume), so a deploy restart doesn't empty them. A 404 is remembered
# too (a negative entry): "no ratings for this title" is an answer, not a failure. Anything carrying request /
# availability state stays on CACHE_TTL.
META_TTL = 6 * 3600

_cache: dict[str, tuple[float, list[dict]]] = {}


def clear_cache() -> None:
    _cache.clear()


def meta_dir() -> Path:
    """META_CACHE_DIR, else a `meta/` folder inside the poster cache (the one cache volume the NAS mounts)."""
    return Path(os.environ.get("META_CACHE_DIR", "").strip() or cache_dir() / "meta")


def clear_meta(disk: bool = False) -> None:
    for k in [k for k in _cache if k.startswith("meta:")]:
        _cache.pop(k, None)
    if disk:
        for f in meta_dir().glob("*.json"):
            try:
                f.unlink()
            except OSError:
                pass


def status_word(code) -> str:
    """The ONE mapping from Jellyseerr's media status code to a word."""
    return {5: "Available", 4: "Partly available", 3: "Processing", 2: "Requested"}.get(
        code if isinstance(code, int) else None, "Not in library")


def _creds() -> tuple[str, str] | None:
    base, key = os.environ.get("JELLYSEERR_URL", "").strip(), os.environ.get("JELLYSEERR_API_KEY", "").strip()
    return (base.rstrip("/"), key) if base and key else None


def _fetch(path: str) -> tuple[object, int | None]:
    """GET a Jellyseerr JSON path -> (parsed body or None, HTTP status or None when no answer)."""
    creds = _creds()
    if not creds:
        return None, None
    try:
        resp = requests.get(f"{creds[0]}{path}", headers={"X-Api-Key": creds[1]}, timeout=TIMEOUT)
        if not 200 <= resp.status_code < 300:
            log.warning("jellyseerr read failed: HTTP %s", resp.status_code)
            return None, resp.status_code
        return resp.json(), resp.status_code
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyseerr read failed: %s", type(exc).__name__)
        return None, None


def _get(path: str):
    """GET a Jellyseerr JSON path -> parsed body, or None on no env / any failure."""
    return _fetch(path)[0]


def _meta_file(path: str) -> Path:
    return meta_dir() / (hashlib.sha256(path.encode("utf-8")).hexdigest() + ".json")


def _meta_disk(path: str) -> tuple[float, object] | None:
    try:
        got = json.loads(_meta_file(path).read_text(encoding="utf-8"))
        return (float(got["at"]), got["body"]) if got.get("path") == path else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _meta_store(path: str, at: float, body) -> None:
    folder = meta_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dest = _meta_file(path)
        tmp = dest.with_suffix(f".{os.getpid()}.{time.monotonic_ns()}.tmp")
        tmp.write_text(json.dumps({"path": path, "at": at, "body": body}), encoding="utf-8")
        os.replace(tmp, dest)  # atomic — a reader never sees half a file
    except (OSError, TypeError, ValueError) as exc:
        log.warning("meta cache write failed (%s)", type(exc).__name__)


def meta_get(path: str, ttl: float = META_TTL):
    """A long-lived (META_TTL, or `ttl`), restart-proof read for a path that carries no user state. Returns the body,
    or None for a remembered 404 / any failure (a failure without a 404 answer is not remembered)."""
    key = f"meta:{path}"
    hit = _cache.get(key)
    if hit is None:
        hit = _meta_disk(path)
        if hit is not None:
            _cache[key] = hit
    if hit is not None and time.time() - hit[0] < ttl:
        return hit[1]
    if not _creds():
        return None
    body, code = _fetch(path)
    if body is None and code != 404:
        return None
    now = time.time()
    _cache[key] = (now, body)
    _meta_store(path, now, body)
    return body


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


def _shelf_rows(path: str, kind_hint, ttl: float = CACHE_TTL) -> list[dict] | None:
    hit = _cache.get(path)
    if hit and time.time() - hit[0] < ttl:
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
            "areas": hub.registry.visible_areas, "active_id": None, "owner_view": view,
            "missing_text": "No page here"}, status_code=404)
    resp = templates.TemplateResponse(request, template, {
        "areas": hub.registry.visible_areas, "active_id": None, "owner_view": view,
        "status": hub.build_status(snaps), "src": src, "connected": _creds() is not None, **build()})
    return hub._maybe_set_cookie(resp, view, from_query)


def _partial(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)


@router.get("/media/discover", response_class=HTMLResponse)
def discover_page(request: Request, q: str = ""):
    q = q.strip()[:100]

    def build():
        ctx = {"q": q, "shelves": [], "rows": [], "note": None, "wl_keys": set(), "services": []}
        if _creds():
            if q:
                ctx["rows"], ctx["note"] = _search_outcome(q)
            else:
                with ThreadPoolExecutor(max_workers=len(SHELVES) + 1) as pool:
                    svc = pool.submit(services)
                    got = list(pool.map(lambda s: _shelf_rows(s[2], s[3]), SHELVES))
                ctx["shelves"] = [{"id": s[0], "title": s[1], "rows": rows} for s, rows in zip(SHELVES, got)]
                ctx["services"] = svc.result()
        ctx["wl_keys"] = keys_for(request, [f"tmdb:{r['tmdb_id']}" for r in ctx["rows"]
                                            + [r for s in ctx["shelves"] for r in s["rows"] or []]])
        return ctx

    return _page(request, "media_discover.html", build)


@router.get("/media/discover/search", response_class=HTMLResponse)
def discover_search(request: Request, q: str = ""):
    rows, note = _search_outcome(q.strip()[:100])
    return _partial(request, "_discover_results.html", rows=rows, note=note,
                    wl_keys=keys_for(request, [f"tmdb:{r['tmdb_id']}" for r in rows]))


# ---- Browse by streaming service (media-ux2, 2026-10-08) ----
# TMDB watch-provider discovery through Jellyseerr: the AU provider lists (/api/v1/watchproviders/{movies|tv}
# ?watchRegion=AU -> [{id, name, logoPath, displayPriority}]) and /api/v1/discover/{movies|tv} with watchRegion +
# watchProviders. The tiles on /media/discover are SERVICES, in this order, matched by name (tolerant of "+" vs
# "Plus", case and spacing); a name the AU list does not carry is skipped (logged once per provider-list read).

WATCH_REGION = "AU"
SERVICES = ("Netflix", "Disney Plus", "Amazon Prime Video", "Stan", "Binge", "Apple TV Plus", "Paramount Plus",
            "HBO Max", "Foxtel Now", "SBS On Demand", "ABC iview", "9Now", "7plus")
PROVIDER_TTL = 24 * 3600   # the provider list barely changes
SERVICE_TTL = 6 * 3600     # a service page's shelves
NEW_DAYS = 30              # "New this month": released in the last NEW_DAYS days
TOP_VOTES = 200            # "Top rated" ignores titles with fewer TMDB votes than this
SERVICE_SHELVES = ("Popular films", "Popular TV", "New this month", "Top rated")


def norm_provider(name) -> str:
    """'Apple TV+' / 'Apple TV Plus' / 'apple tv plus' -> 'appletvplus'."""
    return "".join(c for c in str(name or "").lower().replace("+", "plus") if c.isalnum())


def providers() -> list[dict] | None:
    """The AU watch providers, films' list then TV's, de-duplicated by id: [{id, name, logo}] (logo a tmdb: ref or
    None). None when neither list can be read. Each list is a 24 h restart-proof meta read."""
    out, seen, any_ok = [], set(), False
    for kind in ("movies", "tv"):
        body = meta_get(f"/api/v1/watchproviders/{kind}?watchRegion={WATCH_REGION}", ttl=PROVIDER_TTL)
        if not isinstance(body, list):
            continue
        any_ok = True
        for p in body:
            if not isinstance(p, dict):
                continue
            pid, name = p.get("id"), str(p.get("name") or "").strip()[:80]
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or not name or pid in seen:
                continue
            seen.add(pid)
            out.append({"id": pid, "name": name, "logo": _ref(p.get("logoPath"))})
    return out if any_ok else None


def services() -> list[dict] | None:
    """SERVICES in order, each matched to its AU provider: [{id, name, logo, href}]. None when the provider list is
    unavailable. The match is cached with the list (PROVIDER_TTL) so a miss is logged once per read, not per page."""
    hit = _cache.get("services")
    if hit and time.time() - hit[0] < PROVIDER_TTL:
        return hit[1]
    listed = providers()
    if listed is None:
        return None
    by_norm: dict[str, dict] = {}
    for p in listed:
        by_norm.setdefault(norm_provider(p["name"]), p)
    out = []
    for name in SERVICES:
        p = by_norm.get(norm_provider(name))
        if p is None:
            log.info("watch provider not listed for %s: %s", WATCH_REGION, name)
            continue
        out.append({"id": p["id"], "name": name, "logo": p["logo"], "href": f"/media/discover/service/{p['id']}"})
    _cache["services"] = (time.time(), out)
    return out


def _service_paths(pid: int, today: date) -> dict[str, list[tuple[str, str]]]:
    """Shelf title -> [(Jellyseerr path, kind)] for one provider."""
    base = f"watchRegion={WATCH_REGION}&watchProviders={pid}"
    since, until = (today - timedelta(days=NEW_DAYS)).isoformat(), today.isoformat()
    return {
        "Popular films": [(f"/api/v1/discover/movies?{base}&sortBy=popularity.desc", "movie")],
        "Popular TV": [(f"/api/v1/discover/tv?{base}&sortBy=popularity.desc", "tv")],
        "New this month": [
            (f"/api/v1/discover/movies?{base}&sortBy=primary_release_date.desc"
             f"&primaryReleaseDateGte={since}&primaryReleaseDateLte={until}", "movie"),
            (f"/api/v1/discover/tv?{base}&sortBy=first_air_date.desc&firstAirDateGte={since}&firstAirDateLte={until}",
             "tv")],
        "Top rated": [(f"/api/v1/discover/movies?{base}&sortBy=vote_average.desc&voteCountGte={TOP_VOTES}", "movie"),
                      (f"/api/v1/discover/tv?{base}&sortBy=vote_average.desc&voteCountGte={TOP_VOTES}", "tv")],
    }


def _interleave(lists: list) -> list[dict] | None:
    """Films and TV alternating (each list keeps its own order), ROW_MAX long; None only when every read failed."""
    if all(rows is None for rows in lists):
        return None
    lists = [rows or [] for rows in lists]
    out = []
    for i in range(max((len(r) for r in lists), default=0)):
        out += [r[i] for r in lists if i < len(r)]
    return out[:ROW_MAX]


def service_shelves(pid: int, today: date | None = None) -> list[dict]:
    """[{title, rows}] for a provider; rows None = unavailable, [] = nothing to show. Reads run in parallel, each
    cached SERVICE_TTL (a failed read is not cached)."""
    paths = _service_paths(pid, today or date.today())
    flat = [pk for title in SERVICE_SHELVES for pk in paths[title]]
    with ThreadPoolExecutor(max_workers=len(flat)) as pool:
        got = dict(zip(flat, pool.map(lambda pk: _shelf_rows(pk[0], pk[1], SERVICE_TTL), flat)))
    return [{"title": t, "rows": _interleave([got[pk] for pk in paths[t]])} for t in SERVICE_SHELVES]


@router.get("/media/discover/service/{provider_id}", response_class=HTMLResponse)
def service_page(request: Request, provider_id: int):
    """One streaming service's shelves. 404 for an id the AU provider list does not carry; with the list down the
    page still renders (shelves by id under a plain heading)."""
    from hub import main as hub  # late: hub.main includes this router

    if hub.find_detail_source(hub.JELLYSEERR_SNAPSHOT_ID, hub.get_snapshots(), detail=DISCOVER_DETAIL) is None:
        return _page(request, "media_service.html", dict)   # the 404, before any upstream call
    listed = providers() if _creds() else None
    match = next((p for p in listed or [] if p["id"] == provider_id), None)
    if provider_id <= 0 or (listed is not None and match is None):
        raise HTTPException(404, "No such service")
    named = next((s for s in services() or [] if s["id"] == provider_id), None) if listed is not None else None

    def build():
        ctx = {"service": {"id": provider_id, "name": (named or match or {}).get("name") or "Streaming service",
                           "logo": (match or {}).get("logo")}, "shelves": [], "wl_keys": set()}
        if _creds():
            ctx["shelves"] = service_shelves(provider_id)
        ctx["wl_keys"] = keys_for(request, [f"tmdb:{r['tmdb_id']}" for s in ctx["shelves"] for r in s["rows"] or []])
        return ctx

    return _page(request, "media_service.html", build)


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
    return title_from(_get(f"/api/v1/{kind}/{tmdb_id}"), kind, tmdb_id)


def title_from(data, kind: str, tmdb_id: int) -> dict | None:
    """The title payload from an already-fetched Jellyseerr /movie|tv/{id} body (the film page caches it)."""
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


def _dl_badge(title, snaps=None) -> str | None:
    """'Downloading · 43%' when the arr queue / qBittorrent holds this title; never raises."""
    from hub import main as hub  # late: hub.main includes this router
    from hub import media_downloads

    try:
        snaps = hub.get_snapshots() if snaps is None else snaps
        arr, qb = snaps.get(hub.ARR_SNAPSHOT_ID), snaps.get(media_downloads.QB_SNAPSHOT_ID)
        merged = media_downloads.merge_downloading((arr.data if arr else {}).get("downloading"),
                                                   qb.data if qb else {})
        return media_downloads.badge_for_title(merged, title)
    except Exception:
        log.warning("downloading badge skipped", exc_info=True)
        return None


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
    body = meta_get(f"/api/v1/tv/{tmdb_id}/season/{n}")  # a season's episode list: metadata only
    if not isinstance(body, dict) or not isinstance(body.get("episodes"), list):
        return None
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


async def _seasons_of(request: Request) -> list[int] | str:
    """The ticked season numbers, or "all" when "All seasons + future" is ticked (media-ux5: it wins over any ticks)."""
    body = await request.body()
    if len(body) > MAX_BODY:
        raise bad("Too large")
    values = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get("seasons", [])
    if "all" in values:
        return "all"
    try:
        nums = sorted({int(v) for v in values})
    except ValueError:
        raise bad("Pick at least one season") from None
    if not nums or nums[0] < 1 or len(nums) > 100:
        raise bad("Pick at least one season")
    return nums


def _send(kind: str, tmdb_id: int, seasons: list[int] | str) -> str | None:
    """POST the request to Jellyseerr -> None on success, else an ERRORS code. `seasons` may be "all" (TV): the API's
    `seasons: number[] | "all"` (seerr-api.yml, POST /request) — every season, Specials excepted."""
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
    future = None
    if code is None:
        _cache.pop(f"film:/api/v1/{kind}/{tmdb_id}", None)  # the film page re-reads the new request status
        if seasons == "all":   # media-ux5 item 7: Sonarr follows new seasons too, then searches
            from hub import media_arr_search  # late: it imports this module
            future = media_arr_search.follow_all(tmdb_id)
    if is_htmx(request):
        stub = _stub(kind, tmdb_id)
        if code is None:
            from hub import media_arr_search
            return _partial(request, "_request_block.html", **_block(stub, "done"),
                            future=media_arr_search.future_note(future))
        return _partial(request, "_request_block.html", **_block(stub, "error", ERRORS[code]))
    done = "requested=1" + (f"&future={future}" if future else "")
    return RedirectResponse(f"/media/title/{kind}/{tmdb_id}?" + (done if code is None else f"error={code}"),
                            status_code=303)
