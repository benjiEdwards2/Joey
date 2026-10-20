"""Discover & Search inside Media (2026-10-05): Jellyseerr-style search, discover shelves,
title pages with per-season status, and a two-step Request that goes THROUGH the hub.

A LIVE call path to Jellyseerr (env JELLYSEERR_URL + JELLYSEERR_API_KEY, header X-Api-Key),
server-side only. The key and URL never reach the browser (the one outward link is the
title page's "Open in Seerr", like the existing request rows) and never reach a log
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

import requests  # noqa: F401 - kept: tests fake upstreams at hub.media_discover.requests (E1: via tests/hub/conftest)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import media_awards_badges, media_files, media_text, shell, upstream
from hub.ids import ARR_SNAPSHOT_ID, JELLYSEERR_SNAPSHOT_ID, QBIT_SNAPSHOT_ID
from hub.images import REF_RE, cache_dir
from hub.media_cache import LRU
from hub.media_watchlist import keys_for
from hub.media_write import MAX_BODY, bad, flash_keys, is_htmx, same_origin
from hub.store import ago_text
from hub.shell import templates  # the ONE shared Jinja env (M-23 / H-31)

log = logging.getLogger("hub.media_discover")
router = APIRouter()

DISCOVER_DETAIL = "/media/discover"
TIMEOUT = 8
CACHE_TTL = 600
# E1 (2026-10-13): Discover never blocks. Shelf and provider-list reads wait SHELF_TIMEOUT, not TIMEOUT; a failed read
# is remembered FAIL_TTL so the next loads don't wait again, and the last good rows (kept in memory AND on disk beside
# the meta cache, so a restart keeps them) are served with their age instead of "Discover unavailable".
SHELF_TIMEOUT = 3
FAIL_TTL = 60
ROW_MAX = 20
ON_DISK = ("Available", "Partly available")
SHELVES = (
    ("trending", "Trending", "/api/v1/discover/trending", None),
    ("movies", "Popular films", "/api/v1/discover/movies", "movie"),
    ("tv", "Popular TV", "/api/v1/discover/tv", "tv"),
    ("movies-soon", "Upcoming films", "/api/v1/discover/movies/upcoming", "movie"),
    ("tv-soon", "Upcoming TV", "/api/v1/discover/tv/upcoming", "tv"),
)
flash_keys("requested", "error", "future")   # the title page after a plain-form Request
ERRORS = {"exists": "Already requested", "declined": "Seerr declined the request",
          "network": "Couldn't send the request"}

# Long-lived metadata (2026-10-07, media-speed): responses that carry NO user state (ratings, a person's
# biography, a season's episode list) are kept META_TTL in memory AND on disk (META_CACHE_DIR, one JSON file per
# path, inside the mounted poster-cache volume), so a deploy restart doesn't empty them. A 404 is remembered
# too (a negative entry): "no ratings for this title" is an answer, not a failure. Anything carrying request /
# availability state stays on CACHE_TTL.
META_TTL = 6 * 3600

# Bounded (M-42): "film:" / "meta:" bodies and shelf rows share one LRU; a disk hit copied in by meta_get evicts the
# least recently used entry instead of growing RAM with every library title the warm-up reads.
_cache: LRU = LRU()
_failed: dict[str, float] = {}   # shelf / provider path -> monotonic time of its last failed read (E1)


def clear_cache() -> None:
    _cache.clear()
    _failed.clear()


def meta_dir() -> Path:
    """META_CACHE_DIR, else a `meta/` folder inside the poster cache (the one cache volume the NAS mounts)."""
    return Path(os.environ.get("META_CACHE_DIR", "").strip() or cache_dir() / "meta")


META_KEEP_S = 7 * 24 * 3600   # the longest any meta file is ever read for (OMDb answers, media_omdb.TTL)


def prune_meta(now: float | None = None, keep_s: float = META_KEEP_S) -> int:
    """Delete meta cache files last written over `keep_s` ago (M-47; the warm-up loop runs it). -> files removed."""
    cut = (time.time() if now is None else now) - keep_s
    removed = 0
    try:
        files = list(meta_dir().glob("*.json"))
    except OSError:
        return 0
    for f in files:
        try:
            if f.stat().st_mtime < cut:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


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


def _fetch(path: str, timeout: float = TIMEOUT) -> tuple[object, int | None]:
    """GET a Jellyseerr JSON path -> (parsed body or None, HTTP status or None when no answer)."""
    creds = _creds()
    if not creds:
        return None, None
    try:
        resp = upstream.session("seerr").get(f"{creds[0]}{path}", headers={"X-Api-Key": creds[1]}, timeout=timeout)
        if not 200 <= resp.status_code < 300:
            log.warning("jellyseerr read failed: HTTP %s", resp.status_code)
            return None, resp.status_code
        return resp.json(), resp.status_code
    except Exception as exc:  # type only — requests errors embed the URL
        log.warning("jellyseerr read failed: %s", type(exc).__name__)
        return None, None


def _get(path: str, timeout: float = TIMEOUT):
    """GET a Jellyseerr JSON path -> parsed body, or None on no env / any failure."""
    return _fetch(path, timeout)[0]


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


def _recently_failed(path: str) -> bool:
    at = _failed.get(path)
    return at is not None and time.monotonic() - at < FAIL_TTL


def _note_failure(path: str) -> None:
    _failed[path] = time.monotonic()
    if len(_failed) > 256:   # bounded: drop the oldest half
        for k in sorted(_failed, key=_failed.get)[:128]:
            _failed.pop(k, None)


def meta_get(path: str, ttl: float = META_TTL, *, timeout: float = TIMEOUT, stale_on_fail: bool = False):
    """A long-lived (META_TTL, or `ttl`), restart-proof read for a path that carries no user state. Returns the body,
    or None for a remembered 404 / any failure (a failure without a 404 answer is not remembered).
    `stale_on_fail` (E1, Discover's provider list): a failed read is remembered FAIL_TTL and the last stored body is
    returned, whatever its age, instead of None."""
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
    if stale_on_fail and _recently_failed(path):
        return hit[1] if hit is not None else None
    body, code = _fetch(path, timeout)
    if body is None and code != 404:
        if stale_on_fail:
            _note_failure(path)
            return hit[1] if hit is not None else None
        return None
    now = time.time()
    _cache[key] = (now, body)
    _meta_store(path, now, body)
    return body


MISSING = object()   # meta_peek: "not cached" (a cached 404 is None)


def meta_peek(path: str, ttl: float = META_TTL):
    """meta_get's answer from memory or disk ONLY — never a call (F2 fast pages, 2026-10-12). MISSING when nothing
    fresh is cached, so a page can render what it has and leave the read to a deferred part or a background fill."""
    key = f"meta:{path}"
    hit = _cache.get(key)
    if hit is None:
        hit = _meta_disk(path)
        if hit is not None:
            _cache[key] = hit
    return hit[1] if hit is not None and time.time() - hit[0] < ttl else MISSING


_year = media_text.year


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


SHELF_DISK = "shelf:"   # the disk copy's key prefix (its own file, never meta_get's)


def _shelf(path: str, kind_hint, ttl: float = CACHE_TTL, key: str | None = None) -> tuple[list[dict] | None, float | None]:
    """(rows, stored_at) for one shelf path (E1). stored_at is None when the rows are fresh (under `ttl`), else the
    time the served rows were read: a failed read (SHELF_TIMEOUT, then remembered FAIL_TTL) falls back to the last
    good rows in memory or on disk, whatever their age. (None, None) = failed with nothing stored.
    `key` names the shelf for the memory / disk copies and the failure memo when the path itself changes from day
    to day (a service's "New this month" carries today's date): without it, the last good rows could never be found
    after midnight (seen 2026-10-13 as a clock-crossing test failure)."""
    k = key or path
    hit = _cache.get(k)
    if hit is None:
        disk = _meta_disk(SHELF_DISK + k)
        if disk is not None and isinstance(disk[1], list):
            hit = _cache[k] = disk
    if hit and time.time() - hit[0] < ttl:
        return hit[1], None
    if not _recently_failed(k):
        body = _get(path, SHELF_TIMEOUT)
        if isinstance(body, dict) and isinstance(body.get("results"), list):
            rows, now = _rows(body["results"], kind_hint), time.time()
            _cache[k] = (now, rows)
            _meta_store(SHELF_DISK + k, now, rows)
            return rows, None
        _note_failure(k)
    return (hit[1], hit[0]) if hit else (None, None)


def _shelf_rows(path: str, kind_hint, ttl: float = CACHE_TTL) -> list[dict] | None:
    return _shelf(path, kind_hint, ttl)[0]


def _aged(title: str, stored_at: float | None) -> str:
    """A shelf heading, plus the age of its rows when they are the last good ones ("Trending · 12m ago")."""
    return title if stored_at is None else f"{title} · {ago_text((time.time() - stored_at) / 60.0)}"


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
    view, from_query = shell.resolve_owner_view(request)
    snaps = shell.get_snapshots(request=request)   # M-41: kept on request.state.snaps for the frame and builders
    src = shell.find_detail_source(JELLYSEERR_SNAPSHOT_ID, snaps, detail=DISCOVER_DETAIL)
    if src is None:
        return shell.not_found_page(request)
    resp = shell.render_page(request, template, {
        "status": shell.build_status(snaps), "src": src, "connected": _creds() is not None, **build()})
    return shell._maybe_set_cookie(resp, view, from_query)


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
                    got = list(pool.map(lambda s: _shelf(s[2], s[3]), SHELVES))
                ctx["shelves"] = [{"id": s[0], "title": _aged(s[1], at), "rows": rows}
                                  for s, (rows, at) in zip(SHELVES, got)]
                ctx["services"] = svc.result()
                ages = [at for _, at in got if at is not None]   # E1: for a page-level line, should the page want one
                ctx["stale_note"] = f"Shelves from {ago_text((time.time() - min(ages)) / 60.0)}" if ages else None
        ctx["wl_keys"] = keys_for(request, [f"tmdb:{r['tmdb_id']}" for r in ctx["rows"]
                                            + [r for s in ctx["shelves"] for r in s["rows"] or []]])
        media_awards_badges.attach(ctx["rows"] + [r for s in ctx["shelves"] for r in s["rows"] or []])  # awards-ui 3
        return ctx

    return _page(request, "media_discover.html", build)


@router.get("/media/discover/search", response_class=HTMLResponse)
def discover_search(request: Request, q: str = ""):
    rows, note = _search_outcome(q.strip()[:100])
    media_awards_badges.attach(rows)
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
        body = meta_get(f"/api/v1/watchproviders/{kind}?watchRegion={WATCH_REGION}", ttl=PROVIDER_TTL,
                        timeout=SHELF_TIMEOUT, stale_on_fail=True)   # E1: 3 s, then the last list kept on disk
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


def _service_paths(pid: int, today: date) -> dict[str, list[tuple[str, str, str]]]:
    """Shelf title -> [(Jellyseerr path, kind, store key)] for one provider. The key names the shelf for the
    last-good copy and the failure memo (`_shelf`): stable across days even where the path carries today's date."""
    base = f"watchRegion={WATCH_REGION}&watchProviders={pid}"
    since, until = (today - timedelta(days=NEW_DAYS)).isoformat(), today.isoformat()
    paths = {
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
    return {title: [(path, kind, f"svc:{pid}:{title}:{kind}") for path, kind in rows] for title, rows in paths.items()}


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
    cached SERVICE_TTL; a failed read serves the last good rows with their age (E1, `_shelf`)."""
    paths = _service_paths(pid, today or date.today())
    flat = [pk for title in SERVICE_SHELVES for pk in paths[title]]
    with ThreadPoolExecutor(max_workers=len(flat)) as pool:
        got = dict(zip(flat, pool.map(lambda pk: _shelf(pk[0], pk[1], SERVICE_TTL, key=pk[2]), flat)))

    def oldest(t):
        ages = [got[pk][1] for pk in paths[t] if got[pk][1] is not None]
        return min(ages) if ages else None
    return [{"title": _aged(t, oldest(t)), "rows": _interleave([got[pk][0] for pk in paths[t]])}
            for t in SERVICE_SHELVES]


@router.get("/media/discover/service/{provider_id}", response_class=HTMLResponse)
def service_page(request: Request, provider_id: int):
    """One streaming service's shelves. 404 for an id the AU provider list does not carry; with the list down the
    page still renders (shelves by id under a plain heading)."""
    if shell.find_detail_source(JELLYSEERR_SNAPSHOT_ID, shell.get_snapshots(request=request),
                                detail=DISCOVER_DETAIL) is None:
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
        media_awards_badges.attach([r for s in ctx["shelves"] for r in s["rows"] or []])
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
        s["ticked"] = False  # nothing pre-ticked (2026-10-12): the user picks seasons or ticks "All seasons + future"
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


def _dl_pct(keys, snaps=None) -> int | None:
    """The download % when the arr queue / qBittorrent holds a title with one of `keys` (tmdb: / tvdb:); never raises."""
    from hub import media_downloads

    try:
        snaps = shell.get_snapshots() if snaps is None else snaps
        arr, qb = snaps.get(ARR_SNAPSHOT_ID), snaps.get(QBIT_SNAPSHOT_ID)
        merged = media_downloads.merge_downloading((arr.data if arr else {}).get("downloading"),
                                                   qb.data if qb else {})
        return media_downloads.pct_for_keys(merged, keys)
    except Exception as exc:
        log.warning("downloading badge skipped: %s", type(exc).__name__)
        return None


@router.get("/media/title/{kind}/{tmdb_id}/request", response_class=HTMLResponse)
def request_step(request: Request, kind: str, tmdb_id: int, step: str = ""):
    kind = _kind(kind)
    t = _title(kind, tmdb_id)
    if t is None:
        return _partial(request, "_request_block.html", **_block(_stub(kind, tmdb_id), "error", "Title unavailable"))
    if step != "confirm":
        return _partial(request, "_request_block.html", **_block(t, "idle"))
    from hub import media_quality   # late: it imports this module
    return _partial(request, "_request_block.html", **_block(t, "confirm"), profiles=media_quality.choices(kind))


# ---- Season episodes (lazy, TV only) ----

EPISODES_DOWN = "Episodes unavailable right now"


_date_words = media_text.date_words   # '2026-03-14' -> ('14 Mar 2026', is_future)


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
    files = media_files.file_summary("tv", tmdb_id, snaps=shell.get_snapshots(request=request))
    have = {tuple(k) for k in (files or {}).get("episode_keys") or []}
    rows = [{**e, "on_disk": (n, e["number"]) in have} for e in eps]
    return _partial(request, "_season_episodes.html", episodes=rows, note=None if rows else "No episodes listed")


async def _seasons_of(request: Request) -> list[int] | str:
    """The ticked season numbers, or "all" when ONLY "All seasons + future" is ticked (media-ux5; 2026-10-12: specific
    season ticks win over "all" when both arrive, so one Season tick never requests the whole show)."""
    body = await request.body()
    if len(body) > MAX_BODY:
        raise bad("Too large")
    values = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get("seasons", [])
    specific = [v for v in values if v != "all"]
    if "all" in values and not specific:
        return "all"
    try:
        nums = sorted({int(v) for v in specific})
    except ValueError:
        raise bad("Pick at least one season") from None
    if not nums or nums[0] < 1 or len(nums) > 100:
        raise bad("Pick at least one season")
    return nums


async def _profile_of(request: Request) -> str | None:
    """The Request form's `profile` (WP-R1: the Quality chips), or None when it sent none. Validated in _request_title."""
    body = await request.body()   # Starlette keeps the body: _seasons_of may have read it already
    if len(body) > MAX_BODY:
        raise bad("Too large")
    values = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get("profile", [])
    return values[-1] if values and values[-1] != "" else None


def _send(kind: str, tmdb_id: int, seasons: list[int] | str, profile_id: int | None = None) -> str | None:
    """POST the request to Jellyseerr -> None on success, else an ERRORS code. `seasons` may be "all" (TV): the API's
    `seasons: number[] | "all"` (seerr-api.yml, POST /request) — every season, Specials excepted. `profile_id`
    (WP-R1): the arr quality profile; Seerr applies it to its default server without a `serverId`."""
    creds = _creds()
    if not creds:
        return "network"
    payload: dict = {"mediaType": kind, "mediaId": tmdb_id}
    if kind == "tv":
        payload["seasons"] = seasons
    if profile_id is not None:
        payload["profileId"] = profile_id
    try:
        resp = upstream.session("seerr").post(f"{creds[0]}/api/v1/request", json=payload,
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
    """The body is read on the event loop; the Jellyseerr POST and Sonarr's follow (up to two 2 s waits) run in a
    worker thread, so a slow upstream never stalls other requests or /healthz (M-40)."""
    kind = _kind(kind)
    seasons = await _seasons_of(request) if kind == "tv" else []
    profile = await _profile_of(request)
    return await run_in_threadpool(_request_title, request, kind, tmdb_id, seasons, profile)


def _tvdb_cached(kind: str, tmdb_id: int) -> int | None:
    """A show's TheTVDB id from the cached title body (the confirm step read it), else None - never a call."""
    hit = _cache.get(f"film:/api/v1/{kind}/{tmdb_id}") if kind == "tv" else None
    body = hit[1] if isinstance(hit, tuple) and len(hit) == 2 else None
    v = ((body or {}).get("externalIds") or {}).get("tvdbId") if isinstance(body, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _request_title(request: Request, kind: str, tmdb_id: int, seasons, profile=None):
    from hub import media_quality   # late: it imports this module
    prof = media_quality.pick(kind, profile)   # WP-R1: 422 for a profile the app does not offer
    code = _send(kind, tmdb_id, seasons, prof["id"] if prof else None)
    future = qnet = None
    special = prof if prof and not prof["default"] else None
    if code is None:
        tvdb = _tvdb_cached(kind, tmdb_id)
        _cache.pop(f"film:/api/v1/{kind}/{tmdb_id}", None)  # the film page re-reads the new request status
        from hub import media_requests   # late: it imports this module
        media_requests.forget_lookups()   # E1: the title is on its way into Radarr / Sonarr - Search now re-reads
        if special:   # WP-R1 safety net: the arr entry carries the picked profile (before Sonarr's follow searches)
            qnet = media_quality.ensure(kind, tmdb_id, special["id"], tvdb)
        if seasons == "all":   # media-ux5 item 7: Sonarr follows new seasons too, then searches
            from hub import media_arr_search  # late: it imports this module
            future = media_arr_search.follow_all(tmdb_id)
    if is_htmx(request):
        stub = _stub(kind, tmdb_id)
        if code is None:
            from hub import media_arr_search
            return _partial(request, "_request_block.html", **_block(stub, "done"),
                            future=media_arr_search.future_note(future), quality=(special or {}).get("name"),
                            qnote=media_quality.net_note(qnet, kind))
        return _partial(request, "_request_block.html", **_block(stub, "error", ERRORS[code]))
    done = ("requested=1" + (f"&future={future}" if future else "") + (f"&quality={special['id']}" if special else "")
            + (f"&qnet={qnet}" if media_quality.net_note(qnet, kind) else ""))
    return RedirectResponse(f"/media/title/{kind}/{tmdb_id}?" + (done if code is None else f"error={code}"),
                            status_code=303)
